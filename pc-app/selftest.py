"""Selbsttest – läuft auf Windows (GitHub) und Linux.

Baut einen kleinen Test-„PC“ in einem Temp-Ordner und prüft:
Kategorien, Sicherheitsregeln, Papierkorb, Server, Vorschau, Schutz."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from app import core, server, winsys

MB = 1024 * 1024


def make_file(path: Path, size: int, content: bytes | None = None, age_days: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        path.write_bytes(content)
    else:
        with open(path, "wb") as fh:
            # Anfang + Ende mit Inhalt, Mitte dünn (sparse), damit es schnell geht
            fh.write(os.urandom(min(size, 70000)))
            if size > 70000:
                fh.seek(size - 70000)
                fh.write(os.urandom(70000))
    if age_days:
        ts = time.time() - age_days * 86400
        os.utime(path, (ts, ts))
    return path


def build_tree(root: Path) -> dict:
    user = root / "Users" / "Nevio"
    dl = user / "Downloads"
    same = os.urandom(3 * MB)
    same_dll = os.urandom(2 * MB)
    paths = {
        "installer": make_file(dl / "setup_tool.exe", 2 * MB),
        "iso": make_file(dl / "Win11_German_x64.iso", 600 * MB),
        "zip": make_file(dl / "fotos.zip", 3 * MB),
        "zip_dir": dl / "fotos",
        "video": make_file(user / "Videos" / "Aufnahme.mp4", 25 * MB),
        "photo": make_file(user / "Pictures" / "Urlaub.jpg", 3 * MB),
        "pdf_orig": make_file(user / "Documents" / "Lebenslauf.pdf", len(same), same, age_days=400),
        "pdf_copy": make_file(dl / "Lebenslauf (Kopie).pdf", len(same), same),
        "old_txt": make_file(user / "Documents" / "notizen.txt", 200 * 1024, b"Einkaufsliste\n" * 14000, age_days=1100),
        "small_new": make_file(user / "Desktop" / "todo.txt", 10, b"hallo welt"),
        # Muss alles UNSICHTBAR bleiben:
        "appdata": make_file(user / "AppData" / "Local" / "Spiel" / "cache.bin", 600 * MB),
        "progfiles": make_file(root / "Program Files" / "Tool" / "riesig.dat", 700 * MB),
        "windows": make_file(root / "Windows" / "System32" / "groß.dll", 600 * MB),
        "game_pak": make_file(root / "Games" / "MeinSpiel" / "Content" / "data.pak", 800 * MB),
        "game_marker": make_file(root / "Games" / "MeinSpiel" / "unins000.exe", 1000),
        "steam": make_file(root / "SteamLibrary" / "steamapps" / "common" / "X" / "x.pak", 900 * MB),
        "lnk": make_file(user / "Desktop" / "Spiel.lnk", 2000),
        # Programm ohne Registry-Eintrag direkt auf dem Laufwerk (exe + dll)
        "tool_exe": make_file(root / "Tools" / "MeinTool" / "tool.exe", 600 * MB),
        "tool_dll": make_file(root / "Tools" / "MeinTool" / "helfer.dll", 2 * MB, same_dll),
        # gleiche .dll nochmal in einem normalen Ordner: darf NICHT als Duplikat auftauchen
        "dll_copy": make_file(user / "Documents" / "helfer.dll", 2 * MB, same_dll),
        "old_jar": make_file(user / "Documents" / "alt" / "spiel-mod.jar", 5 * MB, age_days=1500),
        "pak_alone": make_file(root / "Spiele" / "Irgendwas" / "Content" / "riesig.pak", 900 * MB),
    }
    paths["zip_dir"].mkdir(parents=True, exist_ok=True)
    # Verknüpfung auf AppData darf nicht verfolgt werden
    try:
        os.symlink(user / "AppData", user / "Documents" / "Link-zu-AppData", target_is_directory=True)
    except (OSError, NotImplementedError):
        pass
    return paths


def check(cond: bool, text: str, errors: list[str]) -> None:
    print(("  OK   " if cond else "  FEHLER ") + text)
    if not cond:
        errors.append(text)


def run() -> int:
    errors: list[str] = []
    print("== Systemfunktionen ==")
    drives = winsys.fixed_drives()
    check(bool(drives), f"Laufwerke gefunden: {drives}", errors)
    info = winsys.disk_info(drives[0])
    check(info["total"] > 0, f"Speicherinfo {drives[0]}: {core.human_size(info['free'])} frei", errors)
    progs = winsys.installed_programs()
    print(f"  Info  {len(progs)} Programme in der Registry gefunden")
    check(isinstance(winsys.recycle_bin_size(), tuple), "Papierkorb-Größe abfragbar", errors)
    check(winsys.downloads_folder() is not None, f"Downloads-Ordner: {winsys.downloads_folder()}", errors)
    junk = core.measure_junk()
    check("total" in junk, f"Datenmüll messbar: {junk['totalText']}", errors)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "pc"
        data = Path(tmp) / "data"
        data.mkdir()
        p = build_tree(root)
        dl = root / "Users" / "Nevio" / "Downloads"

        print("== Scan ==")
        sc = core.Scanner(data_dir=data, roots=[str(root)], downloads=dl)
        sc.run_blocking()
        check(sc.state.phase == "done", f"Scan fertig (Phase {sc.state.phase}, {sc.state.error})", errors)
        seen = {f.path for f in sc.files}
        for key in ("appdata", "progfiles", "windows", "game_pak", "game_marker", "steam", "lnk",
                    "tool_exe", "tool_dll", "dll_copy", "old_jar", "pak_alone"):
            check(str(p[key]) not in seen, f"Geschützt/ignoriert: {p[key].relative_to(root)}", errors)
        check(not any("Link-zu-AppData" in s for s in seen), "Verknüpfungen werden nicht verfolgt", errors)

        names = lambda cat: {i["name"] for i in sc.items(cat)}  # noqa: E731
        check(names("big") == {"Win11_German_x64.iso"}, f"Große Dateien: {names('big')}", errors)
        check({"setup_tool.exe", "Win11_German_x64.iso", "fotos.zip", "Lebenslauf (Kopie).pdf"} <= names("downloads"), f"Downloads: {names('downloads')}", errors)
        check({"Aufnahme.mp4", "Urlaub.jpg"} == names("media"), f"Videos & Bilder: {names('media')}", errors)
        check(names("duplicates") == {"Lebenslauf (Kopie).pdf"}, f"Doppelte (nur Kopie, Original bleibt): {names('duplicates')}", errors)
        check("notizen.txt" in names("old") and "todo.txt" not in names("old"), f"Lange nicht benutzt: {names('old')}", errors)

        items = {i["name"]: i for c in ("big", "downloads", "media", "duplicates", "old") for i in sc.items(c)}
        check(items["setup_tool.exe"]["verdict"] == "go", "Installer im Download = „Kann weg“", errors)
        check(items["Win11_German_x64.iso"]["verdict"] == "go", "ISO = „Kann weg“", errors)
        check(items["fotos.zip"]["verdict"] == "go" and "entpackt" in items["fotos.zip"]["hint"], "Entpacktes ZIP erkannt", errors)
        check(items["Aufnahme.mp4"]["verdict"] == "check", "Video = „Selbst prüfen“", errors)
        check(items["Lebenslauf (Kopie).pdf"]["verdict"] == "go" and "Documents" in items["Lebenslauf (Kopie).pdf"]["hint"], "Duplikat nennt Ort des Originals", errors)

        print("== Behalten merken ==")
        iso_id = items["Win11_German_x64.iso"]["id"]
        sc.keep(iso_id)
        check("Win11_German_x64.iso" not in names("big"), "Behaltenes taucht nicht mehr auf", errors)
        sc2 = core.Scanner(data_dir=data, roots=[str(root)], downloads=dl)
        sc2.run_blocking()
        check("Win11_German_x64.iso" not in {i["name"] for i in sc2.items("big")}, "…auch nach Neustart", errors)
        sc.unkeep(iso_id)
        check("Win11_German_x64.iso" in names("big"), "Rückgängig beim Behalten klappt", errors)

        print("== Sicherheitsnetz ==")
        check(not sc.is_safe_path(str(p["appdata"])), "AppData-Pfad wird beim Löschen abgelehnt", errors)
        check(not sc.is_safe_path(str(p["windows"])), "Windows-Pfad wird beim Löschen abgelehnt", errors)
        check(sc.is_safe_path(str(p["installer"])), "Downloads-Pfad ist erlaubt", errors)
        check(not sc.is_safe_path(str(p["progfiles"])), "Programme-Pfad wird beim Löschen abgelehnt", errors)
        check(not sc.is_safe_path(str(p["dll_copy"])), "Programmdatei (.dll) wird beim Löschen abgelehnt", errors)
        check(not sc.is_safe_path(str(p["steam"])), "Steam-Bibliothek wird beim Löschen abgelehnt", errors)
        check(not sc.is_safe_path(os.path.join(tmp, "anderswo", "datei.txt")), "Pfad außerhalb der Laufwerke wird abgelehnt", errors)
        fake = sc._register({"type": "file", "path": str(p["appdata"]), "name": "cache.bin", "kind": "file"})
        res = sc.trash([fake["id"]])
        check(p["appdata"].exists() and not res["done"], "Geschützte Datei wird auch per direktem Aufruf nicht gelöscht", errors)

        print("== Server ==")
        app = server.App(scanner=sc)
        httpd = server.serve(app)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def get(path, token=True, headers=None):
            req = urllib.request.Request(base + path, headers={**({"X-Token": app.token} if token else {}), **(headers or {})})
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers, r.read()

        def post(path, body):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"X-Token": app.token, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())

        try:
            get("/api/state", token=False)
            check(False, "API ohne Schlüssel gesperrt", errors)
        except urllib.error.HTTPError as e:
            check(e.code == 403, "API ohne Schlüssel gesperrt (403)", errors)
        status, _, body = get(f"/?t={app.token}", token=False)
        check(status == 200 and b"PC aufr" in body and app.token.encode() in body, "Oberfläche wird ausgeliefert", errors)
        st = json.loads(get("/api/state")[2])
        check(st["phase"] == "done" and len(st["categories"]) == 6, "Status mit 6 Kategorien", errors)
        vid = items["Aufnahme.mp4"]["id"]
        status, headers, chunk = get(f"/api/file?id={vid}", headers={"Range": "bytes=0-99"})
        check(status == 206 and len(chunk) == 100 and headers["Content-Range"].startswith("bytes 0-99/"), "Video-Vorschau mit Spulen (Range)", errors)
        txt = json.loads(get(f"/api/text?id={items['notizen.txt']['id']}")[2])
        check(txt["text"].startswith("Einkaufsliste"), "Text-Vorschau", errors)
        try:
            get(f"/api/file?id={items['setup_tool.exe']['id']}")
            check(False, "Keine Vorschau/Download für .exe", errors)
        except urllib.error.HTTPError as e:
            check(e.code == 404, "Keine Vorschau/Download für .exe", errors)

        print("== Papierkorb ==")
        ids = [items["setup_tool.exe"]["id"], items["Lebenslauf (Kopie).pdf"]["id"]]
        res = post("/api/trash", {"ids": ids})
        check(sorted(res["done"]) == sorted(ids) and not res["failed"], f"In den Papierkorb: {res['freedText']} ({res['failed']})", errors)
        check(not p["installer"].exists() and not p["pdf_copy"].exists(), "Dateien sind weg", errors)
        check(p["pdf_orig"].exists(), "Original vom Duplikat ist noch da", errors)
        check("setup_tool.exe" not in names("downloads"), "Gelöschtes verschwindet aus der Liste", errors)
        httpd.shutdown()

    print()
    if errors:
        print(f"{len(errors)} FEHLER")
        return 1
    print("Alle Tests bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
