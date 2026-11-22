"""Diagnose auf einem echten Windows (GitHub): kompletter Scan von C:."""
import sys, time
from app import core, winsys

t = time.time()
sc = core.Scanner()
sc.run_blocking()
print(f"Scan: Phase={sc.state.phase} Fehler={sc.state.error!r}")
print(f"Dauer: {time.time() - t:.0f} s, {sc.state.files_seen} Dateien, {core.human_size(sc.state.bytes_seen)} angesehen")
print(f"Programme (zum Deinstallieren angeboten): {len(sc.programs)}")
for p in sc.programs[:12]:
    print(f"   {core.human_size(p['size']):>10}  {p['name']}")
blocked = [p['name'] for p in winsys.installed_programs() if core.is_blocked_program(p['name'])]
print(f"Ausgeblendet (Treiber/Laufzeit/Launcher): {len(blocked)}, z. B. {blocked[:8]}")
for cat in core.CATEGORIES:
    items = sc.items(cat['id'])
    print(f"[{cat['title']}] {len(items)} Stück, {core.human_size(sum(i['size'] for i in items))}")
    for i in items[:5]:
        print(f"   {i['sizeText']:>10}  {i['verdict']:5}  {i.get('path') or i['name']}")
bad = [f.path for f in sc.files if not sc.is_safe_path(f.path)]
print(f"Angezeigte Dateien, die das Sicherheitsnetz ablehnen würde: {len(bad)} {bad[:5]}")
junk = core.measure_junk()
print("Datenmüll:", junk['totalText'], [(g['title'], g['sizeText']) for g in junk['groups']])
r = core.clean_junk()
print("Datenmüll gelöscht:", r['freedText'])
sys.exit(1 if sc.state.phase != "done" or bad else 0)
