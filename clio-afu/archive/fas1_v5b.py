#!/usr/bin/env python3
"""
Fas 1 v5b: Bytes 104-111 brute force + duration/terrain/datum-fält
"""
import re, math
from pathlib import Path
from collections import Counter

BASE = Path('/home/clioadmin/19.0/clio-tools/clio-afu')
PDF_PATH = BASE / 'data/downloads/Databases/Larry Hatch/derivations/Larry Hatch - full text.pdf'
RND_PATH = BASE / 'data/downloads/Databases/Larry Hatch/original/U.RND'

HEADER_SIZE = 122
RECORD_SIZE = 112

DATA_LINE_RE = re.compile(
    r"^\s*(\d+):\s+(-?\d{1,4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}:\d{2})"
    r"\s+(\d+)"
    r"\s+(\d+):(\d+):(\d+)\s+([EWZ])"
    r"\s+(\d+):(\d+):(\d+)\s+([NSQ])"
    r"\s+(\S{4})\s+([A-Z0-9.\-]{3})\s+([A-Z0-9.\-]{3})"
    r"(?:\s+([A-Z0-9.\-]{3}))?"
)
SC_RE  = re.compile(r"([0-9A-Fa-f]):([0-9A-Fa-f])\s*$")
REF_RE = re.compile(r"^Ref#\s+(\d+)\s+.*?Page No\.\s+(\d+)\s*:\s*(\S.*?)$")

def parse_pdf(path):
    import fitz
    doc = fitz.open(str(path))
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    lines = text.split('\n')
    records, i = [], 0
    while i < len(lines):
        m = DATA_LINE_RE.match(lines[i])
        if m:
            sc = SC_RE.search(lines[i])
            ts = m.group(5)
            summary = lines[i+1].strip() if i+1 < len(lines) else ''
            ref_no = page_no = 0; terrain = ''
            if i+2 < len(lines):
                rm = REF_RE.match(lines[i+2])
                if rm: ref_no, page_no, terrain = int(rm.group(1)), int(rm.group(2)), rm.group(3).strip()
            records.append({
                'rec_no': int(m.group(1)),
                'year': int(m.group(2)), 'month': int(m.group(3)), 'day': int(m.group(4)),
                'hour': int(ts.split(':')[0]), 'minute': int(ts.split(':')[1]),
                'duration': int(m.group(6)),
                'lon_d': int(m.group(7)), 'lon_m': int(m.group(8)), 'lon_s': int(m.group(9)),
                'lon_dir': m.group(10),
                'lat_d': int(m.group(11)), 'lat_m': int(m.group(12)), 'lat_s': int(m.group(13)),
                'lat_dir': m.group(14), 'prec': m.group(15),
                'continent': m.group(16), 'country': m.group(17),
                'state': m.group(18) if m.group(18) else '---',
                'strange': int(sc.group(1), 16) if sc else -1,
                'cred': int(sc.group(2), 16) if sc else -1,
                'summary': summary, 'ref_no': ref_no, 'page_no': page_no, 'terrain': terrain,
            })
            i += 3
        else:
            i += 1
    return records

print("Parsar PDF...", flush=True)
records = parse_pdf(PDF_PATH)
N = len(records)
print(f"  {N} poster", flush=True)

rnd_data = RND_PATH.read_bytes()
def get_record(i):
    return rnd_data[HEADER_SIZE + i*RECORD_SIZE : HEADER_SIZE + (i+1)*RECORD_SIZE]

# Bekräfta year off-by-1
matches_next = sum(1 for i in range(N-1)
                   if int.from_bytes(get_record(i)[102:104], 'little', signed=True) == records[i+1]['year'])
print(f"\nYear off-by-1: {matches_next}/{N-1} ({matches_next/(N-1)*100:.1f}%)", flush=True)

# =======================================================================
# C. BRUTE FORCE BYTES 104-111
# =======================================================================
print("\n=== C. BRUTE FORCE BYTES 104-111 ===", flush=True)

fields_to_test = [
    ('year',     [r['year']     for r in records], True),
    ('month',    [r['month']    for r in records], False),
    ('day',      [r['day']      for r in records], False),
    ('hour',     [r['hour']     for r in records], False),
    ('minute',   [r['minute']   for r in records], False),
    ('duration', [r['duration'] for r in records], False),
]

for fname, vals, allow_signed in fields_to_test:
    best = {'off': -1, 'w': 1, 'sg': False, 'match': 0, 'pct': 0.0}
    for off in range(104, 112):
        for w in [1, 2]:
            if off + w > RECORD_SIZE:
                continue
            for le in [True]:
                for sg in ([True, False] if allow_signed else [False]):
                    matches = sum(1 for i in range(N)
                                  if int.from_bytes(get_record(i)[off:off+w],
                                                    'little', signed=sg) == vals[i])
                    if matches > best['match']:
                        best = {'off': off, 'w': w, 'sg': sg, 'match': matches, 'pct': matches/N*100}
    print(f"  {fname:10s}: off={best['off']:3d} w={best['w']} sg={best['sg']} → {best['match']}/{N} ({best['pct']:.1f}%)", flush=True)

# =======================================================================
# D. DURATION MED LOGTRANSFORM
# =======================================================================
print("\n=== D. DURATION (logtransform) ===", flush=True)
import math
dur_vals = [r['duration'] for r in records]

for t_name, t_fn in [
    ('raw',       lambda d: d),
    ('log2x16',   lambda d: int(round(math.log2(d+1)*16))),
    ('sqrt',      lambda d: int(round(math.sqrt(d)))),
    ('div10',     lambda d: d // 10),
    ('div5',      lambda d: d // 5),
    ('ln_x256',   lambda d: min(255, int(round(math.log(d+1)/math.log(2)*32)))),
]:
    t_vals = [t_fn(d) for d in dur_vals]
    best = {'off': -1, 'w': 1, 'sg': False, 'match': 0, 'pct': 0.0}
    for off in range(104, 112):
        for w in [1, 2]:
            if off + w > RECORD_SIZE:
                continue
            for sg in [False]:
                matches = sum(1 for i in range(N)
                              if int.from_bytes(get_record(i)[off:off+w], 'little', signed=sg) == t_vals[i])
                if matches > best['match']:
                    best = {'off': off, 'w': w, 'sg': sg, 'match': matches, 'pct': matches/N*100}
    print(f"  dur_{t_name:10s}: off={best['off']} w={best['w']} → {best['match']}/{N} ({best['pct']:.1f}%)", flush=True)

# =======================================================================
# E. TERRAIN INDEX
# =======================================================================
print("\n=== E. TERRAIN INDEX ===", flush=True)
terrain_codes = sorted(set(r['terrain'] for r in records))
print(f"  {len(terrain_codes)} unika terrain-koder", flush=True)
t10 = Counter(r['terrain'] for r in records).most_common(10)
print(f"  Top10: {t10}", flush=True)
t_idx = {t: i for i, t in enumerate(terrain_codes)}
t_vals = [t_idx[r['terrain']] for r in records]

best_t = {'off': -1, 'bias': 0, 'match': 0, 'pct': 0.0}
for off in range(99, 112):
    for bias in range(0, 5):
        matches = sum(1 for i in range(N) if get_record(i)[off] == t_vals[i] + bias)
        if matches > best_t['match']:
            best_t = {'off': off, 'bias': bias, 'match': matches, 'pct': matches/N*100}
print(f"  Terrain index: off={best_t['off']} bias={best_t['bias']} → {best_t['match']}/{N} ({best_t['pct']:.1f}%)", flush=True)

# =======================================================================
# F. FULL KORRELATION BYTES 99-111 inkl. year_next
# =======================================================================
print("\n=== F. FULL KORRELATION BYTES 99-111 ===", flush=True)
year_next = [records[i+1]['year'] if i < N-1 else 9999 for i in range(N)]

all_fields = [
    ('ref_no',    [r['ref_no']   for r in records]),
    ('page_no',   [r['page_no']  for r in records]),
    ('sc_packed', [(r['strange']<<4)|r['cred'] if r['strange']>=0 else -1 for r in records]),
    ('year_next', year_next),
    ('year',      [r['year']     for r in records]),
    ('month',     [r['month']    for r in records]),
    ('day',       [r['day']      for r in records]),
    ('hour',      [r['hour']     for r in records]),
    ('minute',    [r['minute']   for r in records]),
    ('duration',  [r['duration'] for r in records]),
]

print(f"  {'field':12s} {'off':>4} {'w':>2} {'sg':>4} {'match':>7} {'pct':>6}", flush=True)
for fname, vals in all_fields:
    best = {'off': -1, 'w': 1, 'sg': False, 'match': 0, 'pct': 0.0}
    valid_n = sum(1 for v in vals if v >= 0)
    for off in range(99, 112):
        for w in [1, 2]:
            if off + w > RECORD_SIZE:
                continue
            for sg in [True, False]:
                matches = sum(1 for i in range(N) if vals[i] >= 0
                              and int.from_bytes(get_record(i)[off:off+w], 'little', signed=sg) == vals[i])
                if matches > best['match']:
                    best = {'off': off, 'w': w, 'sg': sg, 'match': matches, 'pct': matches/valid_n*100}
    print(f"  {fname:12s} {best['off']:>4} {best['w']:>2} {str(best['sg']):>5} {best['match']:>7} {best['pct']:>6.1f}%", flush=True)

# =======================================================================
# G. ÅR SOM INT16 I PRE-SUMMARY (med off-by-1 korrektion)
#    Prova: binary[i-1][off:off+2] == records[i]['year']
# =======================================================================
print("\n=== G. ÅR I PRE-SUMMARY (off-by-1 korrigerat) ===", flush=True)
# year[i] är lagrat i record i-1 vid byte 102-103?
# Testa alla offsets i pre-summary för year med off-by-1
for off in range(0, 21):
    for w in [2]:
        for sg in [True, False]:
            matches = 0
            for i in range(1, N):
                stored = int.from_bytes(get_record(i-1)[off:off+w], 'little', signed=sg)
                if stored == records[i]['year']:
                    matches += 1
            pct = matches / (N-1) * 100
            if pct > 50:
                print(f"  year[i] @ record[i-1] off={off} w={w} sg={sg}: {matches}/{N-1} ({pct:.1f}%)", flush=True)

# =======================================================================
# H. MINUTER SOM int8u ELLER int16u
#    Minuten lagras som 0,10,20,30,40,50 (multiples av 10)
# =======================================================================
print("\n=== H. MINUT/TIMME I BYTES 104-111 ===", flush=True)
min_vals = [r['minute'] for r in records]
hour_vals = [r['hour'] for r in records]

for fname, vals, w_list in [('minute', min_vals, [1, 2]), ('hour', hour_vals, [1])]:
    for off in range(104, 112):
        for w in w_list:
            if off + w > RECORD_SIZE:
                continue
            matches = sum(1 for i in range(N)
                          if int.from_bytes(get_record(i)[off:off+w], 'little', signed=False) == vals[i])
            pct = matches / N * 100
            if pct > 70:
                print(f"  {fname} off={off} w={w}: {matches}/{N} ({pct:.1f}%)", flush=True)
            # Testa div10 för minut
            if fname == 'minute':
                matches2 = sum(1 for i in range(N)
                               if int.from_bytes(get_record(i)[off:off+w], 'little', signed=False) == vals[i]//10)
                pct2 = matches2 / N * 100
                if pct2 > 60:
                    print(f"  {fname}/10 off={off} w={w}: {matches2}/{N} ({pct2:.1f}%)", flush=True)

# =======================================================================
# I. BYTE-BY-BYTE ANALYS AV POST 0-9 (bytes 104-111)
# =======================================================================
print("\n=== I. BYTES 104-111 FÖR POST 0-9 ===", flush=True)
print("idx  yr  mo  dy   h  m   dur  | bytes 104-111", flush=True)
for i in range(15):
    r = records[i]
    raw = get_record(i)
    post = list(raw[104:112])
    print(f"{i:3d} {r['year']:5d} {r['month']:2d} {r['day']:2d} {r['hour']:2d} {r['minute']:2d} {r['duration']:5d} | "
          + ' '.join(f'{b:02x}' for b in post), flush=True)

print("\nKLAR", flush=True)
