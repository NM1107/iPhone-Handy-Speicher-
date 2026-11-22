"""Startpunkt: Server starten und ein eigenes App-Fenster öffnen."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

from app import server, winsys


def find_browser() -> str | None:
    """Edge ist auf jedem Windows 10/11 dabei; sonst Chrome."""
    candidates = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        candidates += [
            Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def single_instance() -> bool:
    """Verhindert, dass die App zweimal läuft."""
    if not winsys.IS_WINDOWS:
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "PC-Aufraeumen-Einmal")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main() -> None:
    if "--selftest" in sys.argv:
        from selftest import run
        sys.exit(run())

    if not single_instance():
        return

    app = server.App()
    httpd = server.serve(app)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={app.token}"

    browser = find_browser()
    proc = None
    if browser:
        profile = Path(tempfile.gettempdir()) / "PC-Aufraeumen-Fenster"
        proc = subprocess.Popen([
            browser, f"--app={url}", f"--user-data-dir={profile}",
            "--window-size=1360,900", "--no-first-run", "--no-default-browser-check",
            "--disable-features=Translate", "--lang=de",
        ])
    else:
        webbrowser.open(url)

    # Läuft, bis das Fenster zu ist (oder die Seite sich länger nicht meldet)
    while True:
        time.sleep(2)
        if proc is not None and proc.poll() is not None and time.time() - app.last_ping > 8:
            break
        if time.time() - app.last_ping > 120 and not app.scanner.state.running:
            break
    httpd.shutdown()


if __name__ == "__main__":
    main()
