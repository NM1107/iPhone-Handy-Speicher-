"""Windows-spezifische Helfer: Laufwerke, Ordner, installierte Programme,
Papierkorb, Explorer. Auf anderen Systemen gibt es harmlose Ersatzwerte,
damit die Logik auch dort getestet werden kann."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# Datei-Attribute (Windows)
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


# ---------------------------------------------------------------- Laufwerke

def fixed_drives() -> list[str]:
    """Alle festen Laufwerke (C:\\, D:\\ …). Keine USB-Sticks, kein Netzwerk."""
    if not IS_WINDOWS:
        return ["/"]
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if bitmask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            # 3 = DRIVE_FIXED
            if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == 3:
                drives.append(root)
    return drives


def disk_info(root: str) -> dict:
    try:
        usage = shutil.disk_usage(root)
        return {"root": root, "total": usage.total, "free": usage.free, "used": usage.used}
    except OSError:
        return {"root": root, "total": 0, "free": 0, "used": 0}


def volume_label(root: str) -> str:
    if not IS_WINDOWS:
        return ""
    buf = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root), buf, 261, None, None, None, None, 0)
    return buf.value if ok else ""


# ---------------------------------------------------------------- Ordner

def home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def downloads_folder() -> Path:
    """Echter Downloads-Ordner (auch wenn er verschoben wurde)."""
    if IS_WINDOWS:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
            value, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            winreg.CloseKey(key)
            path = Path(os.path.expandvars(value))
            if path.exists():
                return path
        except OSError:
            pass
    return home() / "Downloads"


def local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (home() / "AppData" / "Local"))


def program_data() -> Path:
    return Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")


def windows_dir() -> Path:
    return Path(os.environ.get("SystemRoot") or r"C:\Windows")


def temp_folder() -> Path:
    return Path(os.environ.get("TEMP") or (local_appdata() / "Temp"))


def app_data_dir() -> Path:
    """Hier merkt sich die App, was du behalten willst."""
    path = local_appdata() / "PC-Aufraeumen"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------- Programme

def installed_programs() -> list[dict]:
    """Installierte Programme und Spiele aus der Windows-Registry."""
    if not IS_WINDOWS:
        return []
    import winreg

    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    programs: dict[str, dict] = {}
    for hive, path in roots:
        try:
            base = winreg.OpenKey(hive, path)
        except OSError:
            continue
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(base, index)
            except OSError:
                break
            index += 1
            try:
                key = winreg.OpenKey(base, sub)
            except OSError:
                continue

            def get(name, default=None):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except OSError:
                    return default

            name = get("DisplayName")
            uninstall = get("UninstallString")
            if (not name or not uninstall or get("SystemComponent", 0) == 1
                    or get("ParentKeyName") or get("ReleaseType") in ("Update", "Hotfix", "Security Update")):
                winreg.CloseKey(key)
                continue
            if str(name).startswith(("Update for", "Security Update", "Hotfix")):
                winreg.CloseKey(key)
                continue
            location = (get("InstallLocation") or "").strip().strip('"')
            entry = {
                "key": f"{hive}\\{path}\\{sub}",
                "name": str(name).strip(),
                "publisher": str(get("Publisher") or "").strip(),
                "uninstall": str(uninstall),
                "location": location,
                "estimated_kb": int(get("EstimatedSize") or 0) if str(get("EstimatedSize") or "0").isdigit() else 0,
                "install_date": str(get("InstallDate") or ""),
                "icon": str(get("DisplayIcon") or ""),
            }
            winreg.CloseKey(key)
            dedupe = entry["name"].lower()
            if dedupe not in programs:
                programs[dedupe] = entry
        winreg.CloseKey(base)
    return list(programs.values())


def program_still_installed(registry_key: str) -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    hive_part, _, sub = registry_key.partition("\\")
    try:
        hive = int(hive_part)
        winreg.CloseKey(winreg.OpenKey(hive, sub))
        return True
    except (OSError, ValueError):
        return False


def run_uninstaller(command: str) -> subprocess.Popen | None:
    """Startet das normale Deinstallationsprogramm (der Nutzer sieht es)."""
    if not IS_WINDOWS:
        return None
    return subprocess.Popen(command, shell=True)


# ---------------------------------------------------------------- Explorer

def open_file(path: str) -> None:
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606 – öffnet mit dem Standardprogramm


def reveal_in_explorer(path: str) -> None:
    if IS_WINDOWS:
        subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])


# ---------------------------------------------------------------- Papierkorb

def move_to_recycle_bin(path: str) -> None:
    from send2trash import send2trash
    send2trash(path)


def recycle_bin_size() -> tuple[int, int]:
    """(Bytes, Anzahl) im Papierkorb aller Laufwerke."""
    if not IS_WINDOWS:
        return (0, 0)

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong)]

    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    result = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if result != 0:
        return (0, 0)
    return (int(info.i64Size), int(info.i64NumItems))


def empty_recycle_bin() -> bool:
    if not IS_WINDOWS:
        return True
    SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 0x1, 0x2, 0x4
    result = ctypes.windll.shell32.SHEmptyRecycleBinW(
        None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)
    # 0 = OK, 0x8000FFFF (E_UNEXPECTED) = Papierkorb war schon leer
    return result in (0, -2147418113, 0x8000FFFF)


# ---------------------------------------------------------------- Admin

def is_admin() -> bool:
    if not IS_WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def restart_as_admin() -> bool:
    if not IS_WINDOWS:
        return False
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, ""
    else:
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv)
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return result > 32
