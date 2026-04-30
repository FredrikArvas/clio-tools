#!/usr/bin/env python3
"""
Full sync-kedja: SSFTA → Odoo (ssf-db).
Kor med: nohup python3 -u run_full_sync.py > /tmp/full_sync.log 2>&1 &
Folj upp: tail -f /tmp/full_sync.log

Ordning:
  1. sync_competition_meta   → sektorer, säsonger, grenar, klasser, serier, evenemang, tävlingar
  2. sync_orgs               → organisationer (SF, SDF, föreningar)
  3. sync_persons             → personer
  4. sync_relations           → org-relationer (SF→SDF→Förening, Gren→Förening)
  5. sync_memberships         → medlemskap
  6. sync_functionaries       → funktionärer
  7. sync_person_sectors      → person↔gren (direkt SQL, 340k+)
"""
import subprocess
import sys
from datetime import datetime

BASE = '/home/clioadmin/clio-tools/clio-odoo-ssfta'
DB   = 'ssf'

PY = [sys.executable, '-u']


def step(nr, name, cmd):
    print(f'\n[{datetime.now():%H:%M:%S}] === {nr}. {name} ===', flush=True)
    result = subprocess.run(cmd, cwd=BASE)
    if result.returncode != 0:
        print(f'[{datetime.now():%H:%M:%S}] FEL i {name} (exit {result.returncode})', flush=True)
    else:
        print(f'[{datetime.now():%H:%M:%S}] {name} KLAR', flush=True)
    return result.returncode


print(f'[{datetime.now():%H:%M:%S}] FULL SYNC STARTAR', flush=True)

STEPS = [
    (1, 'Meta (sektorer, grenar, serier, evenemang, tavlingar)',
        PY + [f'{BASE}/sync_competition_meta.py', '--db', DB]),
    (2, 'Orgs (SF/SDF/föreningar)',
        PY + [f'{BASE}/sync_orgs.py', '--db', DB]),
    (3, 'Persons',
        PY + [f'{BASE}/sync_persons.py', '--db', DB]),
    (4, 'Relations (org-hierarki)',
        PY + [f'{BASE}/sync_relations.py', '--db', DB]),
    (5, 'Memberships',
        PY + [f'{BASE}/sync_memberships.py', '--db', DB]),
    (6, 'Functionaries',
        PY + [f'{BASE}/sync_functionaries.py', '--db', DB]),
    (7, 'PersonSectors (person↔gren)',
        PY + [f'{BASE}/sync_person_sectors.py', '--db', DB]),
]

results = []
for nr, name, cmd in STEPS:
    rc = step(nr, name, cmd)
    results.append((nr, rc, name))

print(f'\n[{datetime.now():%H:%M:%S}] === SAMMANFATTNING ===', flush=True)
for nr, rc, name in results:
    status = 'OK' if rc == 0 else f'FEL (exit {rc})'
    print(f'  Steg {nr} {name}: {status}', flush=True)

print(f'[{datetime.now():%H:%M:%S}] Klar.', flush=True)
