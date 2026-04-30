#!/usr/bin/env python3
"""
Full sync-kedja: memberships + meta + results sasong 17+18.
Kor med: nohup python3 -u run_full_sync.py > /tmp/full_sync.log 2>&1 &
Folj upp: tail -f /tmp/full_sync.log
"""
import subprocess
from datetime import datetime

BASE = '/home/clioadmin/clio-tools/clio-odoo-ssfta'


def step(name, cmd):
    print(f'\n[{datetime.now():%H:%M:%S}] === {name} ===', flush=True)
    result = subprocess.run(cmd, cwd=BASE)
    if result.returncode != 0:
        print(f'[{datetime.now():%H:%M:%S}] FEL i {name} (exit {result.returncode})', flush=True)
    else:
        print(f'[{datetime.now():%H:%M:%S}] {name} KLAR', flush=True)
    return result.returncode


print(f'[{datetime.now():%H:%M:%S}] FULL SYNC STARTAR', flush=True)

rc1 = step('1. Memberships',       ['python3', '-u', f'{BASE}/sync_memberships.py', '--db', 'ssf'])
rc2 = step('2. Meta (skip-upd)',   ['python3', '-u', f'{BASE}/sync_competition_meta.py', '--db', 'ssf', '--skip-updates'])
rc3 = step('3. Results sasong 18', ['python3', '-u', f'{BASE}/sync_competition_results.py', '--db', 'ssf', '--season', '18'])
rc4 = step('4. Results sasong 17', ['python3', '-u', f'{BASE}/sync_competition_results.py', '--db', 'ssf', '--season', '17'])

print(f'\n[{datetime.now():%H:%M:%S}] === SAMMANFATTNING ===', flush=True)
for nr, rc, name in [
    (1, rc1, 'Memberships'),
    (2, rc2, 'Meta'),
    (3, rc3, 'Results s18'),
    (4, rc4, 'Results s17'),
]:
    status = 'OK' if rc == 0 else f'FEL (exit {rc})'
    print(f'  Steg {nr} {name}: {status}', flush=True)

print(f'[{datetime.now():%H:%M:%S}] Klar.', flush=True)
