"""Scan, Kategorien, Einschätzungen und Aufräumen – ohne Oberfläche.

Sicherheitsregeln (wichtig, deshalb hier oben):
* Windows, Programme, ProgramData, AppData und Spiele-Bibliotheken werden nie
  einzeln angezeigt. Spiele/Programme gibt es nur als Ganzes und sie werden
  über ihren normalen Windows-Deinstaller entfernt.
* Versteckte Systemdateien, Verknüpfungen (Junctions/Symlinks) und Dateien,
  die nur in der Cloud liegen (OneDrive „nur online“), werden übersprungen.
* Löschen = in den Papierkorb verschieben. Endgültig wird es erst, wenn der
  Nutzer den Papierkorb leert.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import winsys

MB = 1024 * 1024
GB = 1024 * MB

BIG_FILE = 500 * MB
OLD_AFTER_DAYS = 2 * 365
OLD_MIN_SIZE = 100 * 1024
DUP_MIN_SIZE = 1 * MB

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v", ".flv", ".mpg", ".mpeg", ".3gp", ".ts"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff", ".cr2", ".nef", ".arw", ".dng", ".avif"}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"}
TEXT_EXT = {".txt", ".log", ".md", ".csv", ".json", ".xml", ".ini", ".cfg", ".yml", ".yaml", ".bat", ".ps1", ".py", ".js", ".html", ".htm", ".css"}
DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".pages"}
INSTALLER_EXT = {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
DISK_IMAGE_EXT = {".iso", ".img", ".vhd", ".vhdx", ".dmg"}
LEFTOVER_EXT = {".tmp", ".temp", ".dmp", ".old", ".bak", ".crdownload", ".part", ".partial", ".download"}
SKIP_FILE_EXT = {".lnk", ".url", ".sys"}
# Dateien, aus denen Programme/Spiele bestehen. Die werden NIE angeboten
# (Ausnahme: .exe/.msi-Installer in Downloads/Desktop – siehe is_program_file).
PROGRAM_FILE_EXT = {
    ".exe", ".dll", ".sys", ".lib", ".pyd", ".jar", ".so", ".node", ".pak", ".dat", ".bin",
    ".cab", ".msp", ".ocx", ".drv", ".mui", ".cat", ".manifest", ".pdb", ".a", ".o", ".class",
    ".pyc", ".asar", ".bundle", ".assets", ".resource", ".ucas", ".utoc", ".vpk", ".forge",
    ".rpf", ".big", ".wad", ".bsa", ".ba2", ".esm", ".esp", ".xpak", ".ff", ".bdt", ".pck",
    ".obb", ".dylib", ".vdf", ".acf", ".db", ".sqlite", ".ldb", ".mdb", ".edb", ".jrs",
}
SKIP_FILE_NAMES = {"desktop.ini", "thumbs.db", "pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log", "dumpstack.log.tmp", "ntuser.dat"}

# Ordner direkt unter einem Laufwerk, die tabu sind
SKIP_TOP_DIRS = {
    "windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
    "system volume information", "recovery", "perflogs", "$winreagent", "$windows.~bt",
    "$windows.~ws", "config.msi", "msocache", "boot", "efi", "$sysreset", "onedrivetemp",
    "windows.old", "xboxgames", "windowsapps", "drivers",
}
# Ordnernamen, die überall übersprungen werden (Programme/Spiele/System)
SKIP_ANY_DIRS = {
    "appdata", "steamapps", "steamlibrary", "steam", "epic games", "ea games", "ea app",
    "origin games", "ubisoft game launcher", "ubisoft", "riot games", "battle.net",
    "xboxgames", "windowsapps", "gog galaxy", "gog games", "rockstar games",
    "$recycle.bin", "system volume information", ".git", "node_modules",
}
# Unter C:\Users übersprungen
SKIP_ANY_DIRS |= {"include", "site-packages", "__pycache__", ".venv", "venv", "pkgs", "libexec", ".gradle",
                  ".m2", ".nuget", ".cargo", ".rustup", ".conda", "miniconda3", "anaconda3"}
SKIP_USER_DIRS = {"default", "default user", "all users"}

# Liegt eine dieser Dateien/Ordner in einem Ordner, gehört er zu einem Spiel
# oder Programm – dann wird der ganze Ordner nicht einzeln angezeigt.
PROGRAM_MARKERS = {
    "unins000.exe", "uninstall.exe", "steam_api.dll", "steam_api64.dll", "unityplayer.dll",
    "_commonredist", "easyanticheat", "battleye", "binaries", "engine", "eossdk-win64-shipping.dll",
    "steam_appid.txt", "galaxy64.dll", "uplay_r1_loader64.dll", "d3dcompiler_47.dll",
}

# Diese Einträge sind Treiber, Laufzeit-Pakete oder Launcher. Sie werden NICHT
# zum Deinstallieren angeboten (z. B. würde Steam alle Spiele mitnehmen).
PROGRAM_BLOCKLIST = (
    "visual c++", "redistributable", ".net", "runtime", "driver", "treiber", "nvidia",
    "realtek", "intel", "amd", "amd software", "chipset", "directx", "physx", "vulkan",
    "webview2", "microsoft edge", "windows sdk", "windows software development",
    "update health", "microsoft update", "bonjour", "steam", "epic games launcher",
    "ea app", "origin", "ubisoft connect", "battle.net", "riot client", "riot vanguard",
    "gog galaxy", "rockstar games launcher", "xbox", "gaming services", "claude",
    "teams machine-wide", "office click-to-run", "microsoft 365", "onedrive",
    "windows pc health", "easyanticheat", "battleye", "java", "python launcher",
)

CATEGORIES = [
    {"id": "programs", "title": "Spiele & Programme", "color": "#8B5CF6",
     "text": "Sortiert nach Größe. Löschen heißt hier: sauber über Windows deinstallieren."},
    {"id": "big", "title": "Große Dateien", "color": "#3B82F6",
     "text": "Alle Dateien über 500 MB, die größte zuerst."},
    {"id": "downloads", "title": "Downloads", "color": "#F59E0B",
     "text": "Alles im Downloads-Ordner – Installer, ZIPs, PDFs, Bilder."},
    {"id": "media", "title": "Videos & Bilder", "color": "#EC4899",
     "text": "Videos, Aufnahmen und große Bilder mit Vorschau."},
    {"id": "duplicates", "title": "Doppelte Dateien", "color": "#14B8A6",
     "text": "Dateien, die es mehrmals gibt. Das Original bleibt immer."},
    {"id": "old", "title": "Lange nicht benutzt", "color": "#94A3B8",
     "text": "Seit über 2 Jahren nicht verändert – von der Textdatei bis zum Archiv."},
]


# ---------------------------------------------------------------- Hilfen

def human_size(n: float) -> str:
    if n >= GB:
        return f"{n / GB:.1f} GB".replace(".", ",")
    if n >= MB:
        return f"{round(n / MB)} MB"
    if n >= 1024:
        return f"{round(n / 1024)} KB"
    return f"{int(n)} Byte"


def relative_age(timestamp: float, now: float | None = None) -> str:
    now = now or time.time()
    days = int((now - timestamp) // 86400)
    if days < 1:
        return "heute"
    if days == 1:
        return "gestern"
    if days < 31:
        return f"vor {days} Tagen"
    months = days // 30
    if months < 12:
        return "vor 1 Monat" if months == 1 else f"vor {months} Monaten"
    years = days // 365
    return "vor 1 Jahr" if years == 1 else f"vor {years} Jahren"


def kind_of(ext: str) -> str:
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in TEXT_EXT:
        return "text"
    if ext == ".pdf":
        return "pdf"
    return "file"


TYPE_LABELS = {
    "video": "Video", "image": "Bild", "audio": "Audio", "text": "Textdatei", "pdf": "PDF-Dokument",
}


def type_label(ext: str) -> str:
    kind = kind_of(ext)
    if kind in TYPE_LABELS:
        return TYPE_LABELS[kind]
    if ext in INSTALLER_EXT:
        return "Installationsprogramm"
    if ext in ARCHIVE_EXT:
        return "Archiv (gepackte Dateien)"
    if ext in DISK_IMAGE_EXT:
        return "Abbild (ISO/Disk)"
    if ext in DOC_EXT:
        return "Dokument"
    if ext in LEFTOVER_EXT:
        return "Temporäre/Reste-Datei"
    return f"{ext[1:].upper()}-Datei" if ext else "Datei"


@dataclass
class FileEntry:
    path: str
    size: int
    mtime: float
    ext: str
    in_downloads: bool
    id: int = 0
    duplicate_of: str | None = None


@dataclass
class ScanState:
    running: bool = False
    phase: str = "idle"           # idle | files | programs | duplicates | done | error
    files_seen: int = 0
    bytes_seen: int = 0
    current: str = ""
    started: float = 0.0
    finished: float = 0.0
    dup_progress: float = 0.0
    error: str = ""


class KeptStore:
    """Merkt sich, was der Nutzer behalten will – damit es nicht wieder auftaucht."""

    def __init__(self, folder: Path):
        self.file = folder / "behalten.json"
        self.lock = threading.Lock()
        try:
            self.paths: set[str] = set(json.loads(self.file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            self.paths = set()

    def _save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(self.paths), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.file)

    @staticmethod
    def norm(path: str) -> str:
        return os.path.normcase(os.path.normpath(path))

    def add(self, path: str) -> None:
        with self.lock:
            self.paths.add(self.norm(path))
            self._save()

    def remove(self, path: str) -> None:
        with self.lock:
            self.paths.discard(self.norm(path))
            self._save()

    def __contains__(self, path: str) -> bool:
        return self.norm(path) in self.paths

    def clear(self) -> None:
        with self.lock:
            self.paths.clear()
            self._save()


# ---------------------------------------------------------------- Scanner

class Scanner:
    def __init__(self, data_dir: Path | None = None, roots: list[str] | None = None,
                 downloads: Path | None = None, now: float | None = None,
                 system_root: str | None = None):
        self.state = ScanState()
        self.lock = threading.RLock()
        self.roots = roots
        self.downloads = Path(downloads) if downloads else winsys.downloads_folder()
        self.kept = KeptStore(data_dir or winsys.app_data_dir())
        self.now = now
        # Auf dem Windows-Laufwerk wird nur der Benutzer-Bereich (C:\\Users) durchsucht
        sysroot = system_root if system_root is not None else (winsys.windows_dir().anchor if winsys.IS_WINDOWS else "")
        self.system_root = self._norm(sysroot) if sysroot else ""
        self.files: list[FileEntry] = []
        self.by_id: dict[int, dict] = {}
        self.programs: list[dict] = []
        self.skip_prefixes: list[str] = []
        self.removed: set[int] = set()
        self._index: dict[tuple, int] = {}
        self._next_id = 1
        self._cancel = False

    # -------------------------------------------------- Ausschlüsse

    def _norm(self, path: str) -> str:
        return os.path.normcase(os.path.normpath(path))

    def _skip_dir(self, path: str, name: str, depth: int) -> bool:
        lname = name.lower()
        if lname in SKIP_ANY_DIRS or lname.startswith("."):
            return True
        if depth == 0 and self.system_root and lname != "users" and \
                self._norm(os.path.dirname(path)).rstrip("\\/") == self.system_root.rstrip("\\/"):
            return True
        if lname in SKIP_USER_DIRS and os.path.basename(os.path.dirname(path)).lower() == "users":
            return True
        if depth == 0 and lname in SKIP_TOP_DIRS:
            return True
        if lname.startswith("$"):
            return True
        normed = self._norm(path)
        for prefix in self.skip_prefixes:
            if normed == prefix or normed.startswith(prefix + os.sep):
                return True
        return False

    @staticmethod
    def _is_link_or_junction(entry: os.DirEntry) -> bool:
        try:
            if entry.is_symlink():
                return True
            if hasattr(entry, "is_junction") and entry.is_junction():
                return True
            attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
            return bool(attrs & winsys.FILE_ATTRIBUTE_REPARSE_POINT)
        except OSError:
            return True

    # -------------------------------------------------- Scan

    def start(self) -> bool:
        with self.lock:
            if self.state.running:
                return False
            self.state = ScanState(running=True, phase="programs", started=time.time())
            self._cancel = False
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        return True

    def run_blocking(self) -> None:
        """Für Tests: Scan im aktuellen Thread."""
        with self.lock:
            self.state = ScanState(running=True, phase="programs", started=time.time())
        self._run()

    def _run(self) -> None:
        try:
            self._scan_programs()
            self.state.phase = "files"
            self._scan_files()
            self.state.phase = "duplicates"
            self._find_duplicates()
            self.state.phase = "done"
        except Exception as exc:  # noqa: BLE001
            self.state.phase = "error"
            self.state.error = str(exc)
        finally:
            self.state.running = False
            self.state.finished = time.time()

    def _scan_programs(self) -> None:
        programs = winsys.installed_programs()
        prefixes = []
        result = []
        for prog in programs:
            loc = prog.get("location") or ""
            if loc and os.path.isdir(loc) and len(Path(loc).parts) > 2:
                # Programmordner nie einzeln scannen – auch nicht blockierte
                prefixes.append(self._norm(loc))
            if is_blocked_program(prog["name"]):
                continue
            result.append({**prog, "size": prog.get("estimated_kb", 0) * 1024})
        self.skip_prefixes = prefixes
        # Echte Ordnergröße nachrechnen (Registry-Angaben fehlen oft), mit Zeitbudget
        budget_end = time.time() + 45
        for prog in sorted(result, key=lambda p: p["size"], reverse=True):
            loc = prog.get("location") or ""
            if time.time() > budget_end:
                break
            if loc and os.path.isdir(loc) and len(Path(loc).parts) > 2:
                self.state.current = loc
                real = folder_size(loc, limit_seconds=3.0)
                if real > prog["size"]:
                    prog["size"] = real
        self.programs = sorted(result, key=lambda p: p["size"], reverse=True)

    def _scan_files(self) -> None:
        roots = self.roots or winsys.fixed_drives()
        files: list[FileEntry] = []
        downloads_norm = self._norm(str(self.downloads))
        for root in roots:
            stack = [(root, 0)]
            while stack:
                if self._cancel:
                    return
                folder, depth = stack.pop()
                self.state.current = folder
                try:
                    with os.scandir(folder) as it:
                        entries = list(it)
                except OSError:
                    continue
                if depth > 0 and looks_like_program_folder(entries, self._norm(folder) == downloads_norm):
                    continue  # Spiel-/Programmordner: nicht einzeln anfassen
                for entry in entries:
                    try:
                        if self._is_link_or_junction(entry):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if not self._skip_dir(entry.path, entry.name, depth):
                                stack.append((entry.path, depth + 1))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        lname = entry.name.lower()
                        ext = os.path.splitext(lname)[1]
                        if lname in SKIP_FILE_NAMES or ext in SKIP_FILE_EXT:
                            continue
                        st = entry.stat(follow_symlinks=False)
                        attrs = getattr(st, "st_file_attributes", 0)
                        if attrs & winsys.FILE_ATTRIBUTE_SYSTEM:
                            continue
                        if attrs & winsys.CLOUD_ONLY_MASK:
                            continue  # liegt nur in der Cloud – belegt keinen Platz
                        if attrs & winsys.FILE_ATTRIBUTE_HIDDEN and depth == 0:
                            continue
                        if not stat.S_ISREG(st.st_mode):
                            continue
                        normed = self._norm(entry.path)
                        in_dl = normed.startswith(downloads_norm + os.sep)
                        if is_program_file(ext, in_dl, normed):
                            continue
                        self.state.files_seen += 1
                        self.state.bytes_seen += st.st_size
                        files.append(FileEntry(entry.path, st.st_size, st.st_mtime, ext, in_dl))
                    except OSError:
                        continue
        self.files = files

    # -------------------------------------------------- Duplikate

    def _find_duplicates(self) -> None:
        by_size: dict[int, list[FileEntry]] = {}
        for f in self.files:
            if f.size >= DUP_MIN_SIZE:
                by_size.setdefault(f.size, []).append(f)
        candidates = [group for group in by_size.values() if len(group) > 1]
        total = sum(len(g) for g in candidates) or 1
        done = 0
        for group in candidates:
            by_quick: dict[str, list[FileEntry]] = {}
            for f in group:
                done += 1
                self.state.dup_progress = done / total
                h = quick_hash(f.path, f.size)
                if h:
                    by_quick.setdefault(h, []).append(f)
            for same in by_quick.values():
                if len(same) < 2:
                    continue
                by_full: dict[str, list[FileEntry]] = {}
                for f in same:
                    h = full_hash(f.path)
                    if h:
                        by_full.setdefault(h, []).append(f)
                for dupes in by_full.values():
                    if len(dupes) < 2:
                        continue
                    original = pick_original(dupes)
                    for f in dupes:
                        if f is not original:
                            f.duplicate_of = original.path
        self.state.dup_progress = 1.0

    # -------------------------------------------------- Kategorien

    def _register(self, record: dict) -> dict:
        key = (record["type"], record.get("path") or record.get("key"))
        with self.lock:
            item_id = self._index.get(key)
            if item_id is None:
                item_id = self._next_id
                self._next_id += 1
                self._index[key] = item_id
            record["id"] = item_id
            self.by_id[item_id] = record
        return record

    def file_record(self, f: FileEntry, category: str) -> dict:
        now = self.now or time.time()
        verdict, hint = judge(f, category, now)
        return {
            "type": "file",
            "path": f.path,
            "name": os.path.basename(f.path),
            "folder": os.path.dirname(f.path),
            "size": f.size,
            "sizeText": human_size(f.size),
            "ext": f.ext[1:].upper() if f.ext else "",
            "kind": kind_of(f.ext),
            "typeLabel": type_label(f.ext),
            "modified": relative_age(f.mtime, now),
            "verdict": verdict,
            "hint": hint,
            "duplicateOf": f.duplicate_of,
        }

    def program_record(self, p: dict) -> dict:
        date = p.get("install_date") or ""
        when = f"{date[6:8]}.{date[4:6]}.{date[0:4]}" if len(date) == 8 and date.isdigit() else "unbekannt"
        size = p.get("size") or 0
        return {
            "type": "program",
            "key": p["key"],
            "name": p["name"],
            "folder": p.get("location") or "",
            "path": "",
            "size": size,
            "sizeText": human_size(size) if size else "Größe unbekannt",
            "ext": "",
            "kind": "program",
            "typeLabel": "Spiel / Programm" + (f" · {p['publisher']}" if p.get("publisher") else ""),
            "modified": f"installiert am {when}",
            "verdict": "check",
            "hint": "Wird über das normale Windows-Deinstallieren entfernt. Spielstände in der Cloud bleiben erhalten – lokale Spielstände vorher sichern, wenn du sie noch brauchst.",
            "uninstall": p["uninstall"],
        }

    def items(self, category: str) -> list[dict]:
        now = self.now or time.time()
        if category == "programs":
            records = [self.program_record(p) for p in self.programs if p["key"] not in self.kept]
            records = [self._register(r) for r in records]
            return [r for r in records if r["id"] not in self.removed]

        chosen: list[FileEntry] = []
        for f in self.files:
            if f.path in self.kept:
                continue
            if category == "big" and f.size >= BIG_FILE:
                chosen.append(f)
            elif category == "downloads" and f.in_downloads:
                chosen.append(f)
            elif category == "media":
                if (f.ext in VIDEO_EXT and f.size >= 20 * MB) or (f.ext in IMAGE_EXT and f.size >= 2 * MB):
                    chosen.append(f)
            elif category == "duplicates" and f.duplicate_of:
                chosen.append(f)
            elif category == "old" and f.size >= OLD_MIN_SIZE and now - f.mtime > OLD_AFTER_DAYS * 86400:
                chosen.append(f)
        chosen.sort(key=lambda f: f.size, reverse=True)
        records = [self._register(self.file_record(f, category)) for f in chosen]
        return [r for r in records if r["id"] not in self.removed]

    def summary(self) -> list[dict]:
        out = []
        for cat in CATEGORIES:
            items = self.items(cat["id"])
            out.append({**cat, "count": len(items), "size": sum(i["size"] for i in items),
                        "sizeText": human_size(sum(i["size"] for i in items))})
        return out

    # -------------------------------------------------- Aktionen

    def keep(self, item_id: int) -> None:
        rec = self.by_id.get(item_id)
        if rec:
            self.kept.add(rec.get("path") or rec.get("key"))

    def unkeep(self, item_id: int) -> None:
        rec = self.by_id.get(item_id)
        if rec:
            self.kept.remove(rec.get("path") or rec.get("key"))

    def trash(self, ids: list[int]) -> dict:
        """Dateien in den Papierkorb. Programme werden hier nicht angefasst."""
        done, failed, freed = [], [], 0
        gone_paths: set[str] = set()
        for item_id in ids:
            rec = self.by_id.get(item_id)
            if not rec or rec["type"] != "file":
                continue
            path = rec["path"]
            if not self.is_safe_path(path):
                failed.append({"id": item_id, "name": rec["name"], "reason": "Geschützter Ordner"})
                continue
            try:
                size = os.path.getsize(path)
                winsys.move_to_recycle_bin(path)
                done.append(item_id)
                freed += size
                self.removed.add(item_id)
                gone_paths.add(path)
            except FileNotFoundError:
                done.append(item_id)
                self.removed.add(item_id)
                gone_paths.add(path)
            except Exception as exc:  # noqa: BLE001
                failed.append({"id": item_id, "name": rec["name"], "reason": friendly_error(exc)})
        if gone_paths:
            self.files = [f for f in self.files if f.path not in gone_paths]
        return {"done": done, "failed": failed, "freed": freed, "freedText": human_size(freed)}

    def is_safe_path(self, path: str) -> bool:
        """Zweite Sicherung direkt vor dem Löschen – unabhängig vom Scan."""
        normed = self._norm(path)
        rel_parts = None
        for root in (self.roots or winsys.fixed_drives()):
            nroot = self._norm(root).rstrip("\\/")
            if normed.startswith(nroot + os.sep):
                rel_parts = [p.lower() for p in Path(normed[len(nroot) + 1:]).parts]
                break
        if not rel_parts or len(rel_parts) < 2 and rel_parts[0] in SKIP_FILE_NAMES:
            return False  # außerhalb der gescannten Laufwerke: nie
        if rel_parts[0] in SKIP_TOP_DIRS or rel_parts[0].startswith("$"):
            return False
        if self.system_root and normed.startswith(self.system_root.rstrip("\\/") + os.sep) and \
                len(rel_parts) > 1 and rel_parts[0] != "users":
            return False
        if any(d.startswith(".") for d in rel_parts[:-1]):
            return False
        dirs = rel_parts[:-1]
        if any(d in SKIP_ANY_DIRS for d in dirs):
            return False
        if len(dirs) >= 2 and dirs[0] == "users" and dirs[1] in SKIP_USER_DIRS:
            return False
        if os.path.basename(normed) in SKIP_FILE_NAMES:
            return False
        in_dl = normed.startswith(self._norm(str(self.downloads)) + os.sep)
        if is_program_file(os.path.splitext(normed)[1], in_dl, normed):
            return False
        return not any(normed.startswith(prefix + os.sep) for prefix in self.skip_prefixes)

    def mark_program_removed(self, item_id: int) -> None:
        self.removed.add(item_id)


# ---------------------------------------------------------------- Einschätzung

def judge(f: FileEntry, category: str, now: float) -> tuple[str, str]:
    """('go' = kann weg | 'check' = selbst prüfen, Erklärung)."""
    name = os.path.basename(f.path)
    folder = os.path.dirname(f.path)
    stem = os.path.splitext(name)[0]
    if f.duplicate_of:
        return "go", f"Doppelt: Die gleiche Datei liegt auch in „{os.path.dirname(f.duplicate_of)}“. Nur diese Kopie wird gelöscht."
    if f.ext in LEFTOVER_EXT:
        return "go", "Temporäre oder abgebrochene Datei – wird nicht mehr gebraucht."
    if f.ext in DISK_IMAGE_EXT:
        return "go", "Abbild einer CD/DVD oder eines Installationsmediums. Kann man normalerweise jederzeit neu herunterladen."
    if f.ext in INSTALLER_EXT and f.in_downloads:
        return "go", "Installationsprogramm. Ist das Programm schon installiert, brauchst du diese Datei nicht mehr."
    if f.ext in ARCHIVE_EXT:
        if os.path.isdir(os.path.join(folder, stem)):
            return "go", f"Gepacktes Archiv, das schon entpackt ist – der Ordner „{stem}“ liegt daneben."
        return "check", "Gepacktes Archiv. Wenn du es schon entpackt hast, brauchst du es meist nicht mehr."
    if f.ext in VIDEO_EXT:
        return "check", "Video – schau kurz rein, bevor du entscheidest."
    if f.ext in IMAGE_EXT:
        return "check", "Bild – schau kurz drauf, ob du es noch brauchst."
    if f.ext in DOC_EXT:
        return "check", "Dokument – könnte wichtig sein (Schule, Arbeit, Verträge). Lieber kurz prüfen."
    age_days = (now - f.mtime) / 86400
    if age_days > OLD_AFTER_DAYS:
        return "check", f"Seit {int(age_days // 365)} Jahren nicht verändert."
    if f.size < MB:
        return "check", "Kleine Datei – spart kaum Platz. Nur löschen, wenn sie dir nichts mehr bringt."
    return "check", "Schau kurz drauf, ob du sie noch brauchst."


_BLOCK_RE = None


def looks_like_program_folder(entries: list, is_downloads: bool) -> bool:
    """Ein Ordner mit .exe UND .dll (oder einem Marker) ist ein Programm/Spiel."""
    names = {e.name.lower() for e in entries}
    if PROGRAM_MARKERS & names:
        return True
    if is_downloads:
        return False
    has_exe = any(n.endswith(".exe") for n in names)
    has_dll = any(n.endswith(".dll") for n in names)
    return has_exe and has_dll


def is_program_file(ext: str, in_downloads: bool, normed_path: str) -> bool:
    """Programmdateien nie anbieten – außer Installer im Downloads-Ordner/Desktop."""
    if ext not in PROGRAM_FILE_EXT:
        return False
    if ext in INSTALLER_EXT and (in_downloads or f"{os.sep}desktop{os.sep}" in normed_path):
        return False
    return True


def is_blocked_program(name: str) -> bool:
    """Ganze Wörter vergleichen: „Origin“ ja, „Assassin's Creed Origins“ nein."""
    global _BLOCK_RE
    if _BLOCK_RE is None:
        import re
        terms = "|".join(re.escape(t.strip()) for t in PROGRAM_BLOCKLIST)
        _BLOCK_RE = re.compile(rf"(?<![a-z0-9])(?:{terms})(?![a-z0-9])")
    return bool(_BLOCK_RE.search(name.lower()))


def friendly_error(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, PermissionError) or "denied" in text or "zugriff" in text:
        return "Kein Zugriff – Datei ist geöffnet oder geschützt"
    if "used by another process" in text or "being used" in text:
        return "Datei ist gerade geöffnet"
    return "Konnte nicht verschoben werden"


def pick_original(dupes: list[FileEntry]) -> FileEntry:
    """Das „Original“ bleibt: nicht im Downloads-Ordner, ohne „Kopie“, das älteste."""
    def score(f: FileEntry):
        lname = os.path.basename(f.path).lower()
        is_copy = any(t in lname for t in ("kopie", "copy", " (1)", " (2)", " (3)", "- kopie"))
        return (f.in_downloads, is_copy, f.mtime, len(f.path))
    return min(dupes, key=score)


def quick_hash(path: str, size: int) -> str | None:
    """Anfang, Mitte, Ende – schnell, um Kandidaten auszusortieren."""
    try:
        h = hashlib.blake2b(digest_size=16)
        with open(path, "rb") as fh:
            for offset in (0, max(0, size // 2 - 32768), max(0, size - 65536)):
                fh.seek(offset)
                h.update(fh.read(65536))
        return h.hexdigest()
    except OSError:
        return None


def full_hash(path: str) -> str | None:
    try:
        h = hashlib.blake2b(digest_size=20)
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(4 * MB)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def folder_size(path: str, limit_seconds: float = 10.0) -> int:
    total = 0
    deadline = time.time() + limit_seconds
    stack = [path]
    while stack:
        if time.time() > deadline:
            break
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            if not getattr(st, "st_file_attributes", 0) & winsys.CLOUD_ONLY_MASK:
                                total += st.st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


# ---------------------------------------------------------------- Datenmüll

def junk_locations() -> list[dict]:
    la = winsys.local_appdata()
    pd = winsys.program_data()
    win = winsys.windows_dir()
    locs = [
        ("Temporäre Dateien (deine)", [winsys.temp_folder()]),
        ("Temporäre Dateien (Windows)", [win / "Temp"]),
        ("Windows-Update-Downloads", [win / "SoftwareDistribution" / "Download"]),
        ("Übermittlungsoptimierung (Update-Cache)", [win / "ServiceProfiles" / "NetworkService" / "AppData" / "Local" / "Microsoft" / "Windows" / "DeliveryOptimization" / "Cache"]),
        ("Grafik-Shader-Cache", [la / "D3DSCache", la / "NVIDIA" / "DXCache", la / "NVIDIA" / "GLCache",
                                 la / "AMD" / "DxCache", la / "AMD" / "DxcCache", pd / "NVIDIA Corporation" / "NV_Cache"]),
        ("Browser-Cache", browser_caches(la)),
        ("Entpackte Treiber-Installer", [Path(win.anchor or "C:\\") / "AMD", Path(win.anchor or "C:\\") / "NVIDIA"]),
        ("Absturzberichte", [la / "CrashDumps", pd / "Microsoft" / "Windows" / "WER" / "ReportArchive",
                             pd / "Microsoft" / "Windows" / "WER" / "ReportQueue"]),
    ]
    out = []
    for title, paths in locs:
        existing = [str(p) for p in paths if p and os.path.isdir(p)]
        out.append({"title": title, "paths": existing})
    return out


def browser_caches(la: Path) -> list[Path]:
    caches = []
    for vendor in (la / "Google" / "Chrome" / "User Data", la / "Microsoft" / "Edge" / "User Data",
                   la / "BraveSoftware" / "Brave-Browser" / "User Data"):
        if not vendor.is_dir():
            continue
        try:
            profiles = [p for p in vendor.iterdir() if p.is_dir() and (p.name == "Default" or p.name.startswith("Profile"))]
        except OSError:
            continue
        for prof in profiles:
            for sub in ("Cache", "Code Cache", "GPUCache", "Service Worker/CacheStorage"):
                caches.append(prof / sub)
    ff = la / "Mozilla" / "Firefox" / "Profiles"
    if ff.is_dir():
        try:
            for prof in ff.iterdir():
                caches.append(prof / "cache2")
        except OSError:
            pass
    return caches


def measure_junk() -> dict:
    groups = []
    total = 0
    denied = False
    for loc in junk_locations():
        size = 0
        for p in loc["paths"]:
            if not os.access(p, os.R_OK | os.W_OK):
                denied = True
                continue
            size += folder_size(p, limit_seconds=6.0)
        groups.append({"title": loc["title"], "size": size, "sizeText": human_size(size)})
        total += size
    bin_size, bin_count = winsys.recycle_bin_size()
    groups.append({"title": "Papierkorb", "size": bin_size, "sizeText": human_size(bin_size), "count": bin_count})
    total += bin_size
    return {"groups": groups, "total": total, "totalText": human_size(total),
            "needsAdmin": denied and not winsys.is_admin()}


def clean_junk() -> dict:
    """Löscht den INHALT der Cache-/Temp-Ordner. Gesperrte Dateien bleiben einfach."""
    freed = 0
    for loc in junk_locations():
        for folder in loc["paths"]:
            freed += _delete_contents(folder)
    bin_size, _ = winsys.recycle_bin_size()
    if winsys.empty_recycle_bin():
        freed += bin_size
    return {"freed": freed, "freedText": human_size(freed)}


def _delete_contents(folder: str) -> int:
    freed = 0
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_symlink():
                os.unlink(entry.path)
                continue
            if entry.is_dir(follow_symlinks=False):
                freed += _delete_contents(entry.path)
                try:
                    os.rmdir(entry.path)
                except OSError:
                    pass
            else:
                size = entry.stat(follow_symlinks=False).st_size
                os.chmod(entry.path, stat.S_IWRITE)
                os.unlink(entry.path)
                freed += size
        except OSError:
            continue
    return freed
