"""Kleiner lokaler Webserver: liefert die Oberfläche und die Daten.

Nur auf 127.0.0.1 erreichbar und jede API-Anfrage braucht einen zufälligen
Schlüssel, damit keine fremde Webseite etwas auslösen kann."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import core, winsys

PREVIEW_KINDS = {"image", "video", "audio", "pdf", "text"}
BROWSER_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".avif"}
BROWSER_VIDEO_EXT = {".mp4", ".webm", ".m4v", ".mov"}


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


class App:
    def __init__(self, scanner: core.Scanner | None = None):
        self.token = secrets.token_urlsafe(24)
        self.scanner = scanner or core.Scanner()
        self.last_ping = time.time()
        self.junk_cache: dict | None = None
        self.junk_lock = threading.Lock()
        self.uninstall_queue: list[int] = []
        self.uninstall_state = {"running": False, "current": "", "done": [], "left": 0}

    # -------------------------------------------------- Daten

    def disks(self) -> list[dict]:
        roots = self.scanner.roots or winsys.fixed_drives()
        out = []
        for root in roots:
            info = winsys.disk_info(root)
            info["label"] = winsys.volume_label(root)
            info["freeText"] = core.human_size(info["free"])
            info["totalText"] = core.human_size(info["total"])
            out.append(info)
        return out

    def state(self) -> dict:
        st = self.scanner.state
        data = {
            "phase": st.phase,
            "running": st.running,
            "filesSeen": st.files_seen,
            "bytesSeen": st.bytes_seen,
            "bytesText": core.human_size(st.bytes_seen),
            "current": st.current,
            "dupProgress": round(st.dup_progress, 3),
            "error": st.error,
            "seconds": round((st.finished or time.time()) - st.started, 1) if st.started else 0,
            "disks": self.disks(),
            "isAdmin": winsys.is_admin(),
            "uninstall": self.uninstall_state,
        }
        if st.phase in ("duplicates", "done"):
            data["categories"] = self.scanner.summary()
        return data

    def junk(self, refresh: bool = False) -> dict:
        with self.junk_lock:
            if self.junk_cache is None or refresh:
                self.junk_cache = core.measure_junk()
            return self.junk_cache

    def start_uninstalls(self, ids: list[int]) -> None:
        records = [self.scanner.by_id.get(i) for i in ids]
        records = [r for r in records if r and r["type"] == "program"]
        if not records or self.uninstall_state["running"]:
            return
        self.uninstall_state = {"running": True, "current": "", "done": [], "left": len(records)}

        def worker():
            for rec in records:
                self.uninstall_state["current"] = rec["name"]
                try:
                    proc = winsys.run_uninstaller(rec["uninstall"])
                    if proc is not None:
                        proc.wait()
                except Exception:  # noqa: BLE001
                    pass
                # Manche Deinstaller laufen im Hintergrund weiter – kurz warten
                for _ in range(60):
                    if not winsys.program_still_installed(rec["key"]):
                        break
                    time.sleep(2)
                if not winsys.program_still_installed(rec["key"]):
                    self.scanner.mark_program_removed(rec["id"])
                    self.uninstall_state["done"].append(rec["id"])
                self.uninstall_state["left"] -= 1
            self.uninstall_state["running"] = False
            self.uninstall_state["current"] = ""

        threading.Thread(target=worker, daemon=True).start()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PCAufraeumen/1.0"

        def log_message(self, *args):  # keine Konsole
            pass

        # ---------------- Hilfen
        def _send_json(self, data, status=HTTPStatus.OK):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self, query: dict) -> bool:
            token = self.headers.get("X-Token") or (query.get("t") or [""])[0]
            return secrets.compare_digest(token, app.token)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 5_000_000:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except ValueError:
                return {}

        # ---------------- GET
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                if not self._authorized(query):
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                html = resource_path("ui", "index.html").read_text(encoding="utf-8")
                body = html.replace("__TOKEN__", app.token).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if url.path == "/favicon.ico":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not self._authorized(query):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            app.last_ping = time.time()
            if url.path == "/api/state":
                self._send_json(app.state())
            elif url.path == "/api/items":
                cat = (query.get("cat") or [""])[0]
                items = app.scanner.items(cat)
                # Die größten zuerst – mehr als 3000 schaut sowieso niemand an
                self._send_json({"items": items[:3000], "total": len(items)})
            elif url.path == "/api/junk":
                refresh = (query.get("refresh") or ["0"])[0] == "1"
                self._send_json(app.junk(refresh))
            elif url.path == "/api/file":
                self._serve_file(query)
            elif url.path == "/api/text":
                self._serve_text(query)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def _record(self, query):
            try:
                rec = app.scanner.by_id.get(int((query.get("id") or ["0"])[0]))
            except ValueError:
                return None
            if not rec or rec["type"] != "file" or rec["kind"] not in PREVIEW_KINDS:
                return None
            return rec

        def _serve_text(self, query):
            rec = self._record(query)
            if not rec:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                with open(rec["path"], "rb") as fh:
                    raw = fh.read(6000)
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            for enc in ("utf-8", "cp1252", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            self._send_json({"text": text})

        def _serve_file(self, query):
            """Datei für die Vorschau – mit Range, damit Videos spulen können."""
            rec = self._record(query)
            if not rec:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            path = rec["path"]
            try:
                size = os.path.getsize(path)
                fh = open(path, "rb")  # noqa: SIM115
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            start, end = 0, size - 1
            status = HTTPStatus.OK
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                try:
                    a, _, b = rng[6:].split(",")[0].partition("-")
                    if a:
                        start = int(a)
                        end = int(b) if b else size - 1
                    else:
                        start = max(0, size - int(b))
                    end = min(end, size - 1)
                    status = HTTPStatus.PARTIAL_CONTENT
                except ValueError:
                    start, end = 0, size - 1
            if start > end or start >= max(size, 1):
                fh.close()
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(1024 * 1024, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (ConnectionError, OSError):
                pass
            finally:
                fh.close()

        # ---------------- POST
        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            if not self._authorized(parse_qs(url.query)):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            app.last_ping = time.time()
            body = self._body()
            scanner = app.scanner
            ids = [int(i) for i in body.get("ids", []) if str(i).isdigit()]
            item_id = int(body["id"]) if str(body.get("id", "")).isdigit() else 0

            if url.path == "/api/scan":
                self._send_json({"started": scanner.start()})
            elif url.path == "/api/keep":
                scanner.keep(item_id)
                self._send_json({"ok": True})
            elif url.path == "/api/unkeep":
                scanner.unkeep(item_id)
                self._send_json({"ok": True})
            elif url.path == "/api/trash":
                result = scanner.trash(ids)
                app.junk_cache = None
                self._send_json(result)
            elif url.path == "/api/uninstall":
                app.start_uninstalls(ids)
                self._send_json({"ok": True})
            elif url.path == "/api/open":
                rec = scanner.by_id.get(item_id)
                if rec and rec["type"] == "file":
                    try:
                        winsys.open_file(rec["path"])
                    except OSError:
                        pass
                self._send_json({"ok": True})
            elif url.path == "/api/reveal":
                rec = scanner.by_id.get(item_id)
                if rec:
                    target = rec.get("path") or rec.get("folder")
                    if target:
                        winsys.reveal_in_explorer(target)
                self._send_json({"ok": True})
            elif url.path == "/api/junk/clean":
                result = core.clean_junk()
                app.junk_cache = None
                self._send_json(result)
            elif url.path == "/api/bin/empty":
                size, _ = winsys.recycle_bin_size()
                ok = winsys.empty_recycle_bin()
                app.junk_cache = None
                self._send_json({"ok": ok, "freed": size if ok else 0,
                                 "freedText": core.human_size(size if ok else 0)})
            elif url.path == "/api/bin":
                size, count = winsys.recycle_bin_size()
                self._send_json({"size": size, "sizeText": core.human_size(size), "count": count})
            elif url.path == "/api/reset-kept":
                scanner.kept.clear()
                self._send_json({"ok": True})
            elif url.path == "/api/admin":
                ok = winsys.restart_as_admin()
                self._send_json({"ok": ok})
                if ok:
                    threading.Timer(0.5, lambda: os._exit(0)).start()
            elif url.path == "/api/ping":
                self._send_json({"ok": True})
            elif url.path == "/api/quit":
                self._send_json({"ok": True})
                threading.Timer(0.3, lambda: os._exit(0)).start()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

    return Handler


def serve(app: App, port: int = 0) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
