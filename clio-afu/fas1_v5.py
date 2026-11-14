#!/usr/bin/env python3
"""
Fas 1 v5: Bekräfta S|C-packning, lös bytes 104-111 och år-mysteriet.
"""
import re, struct, json
from pathlib import Path
from collections import Counter, defaultdict

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

# =======================================================================
# A. VERIFIERA S|C PACKNING VID OFFSET 101
# =======================================================================
print("\n=== A. S|C PACKNING @ offset 101 ===", flush=True)
valid_sc = [(i, r['strange'], r['cred']) for i, r in enumerate(records)
            if r['strange'] >= 0 and r['cred'] >= 0]
packed_matches = sum(1 for i, s, c in valid_sc
                     if get_record(i)[101] == (s << 4) | c)
print(f"  (S<<4)|C @ offset 101: {packed_matches}/{len(valid_sc)} ({packed_matches/len(valid_sc)*100:.1f}%)", flush=True)

# Bekräfta med konkreta exempel
print("  Kontroll post 0-14:", flush=True)
for i in range(15):
    r = records[i]
    b = get_record(i)[101]
    exp = (r['strange'] << 4) | r['cred'] if r['strange'] >= 0 else -1
    ok = '✓' if b == exp else '✗'
    print(f"    post {i:3d}: s={r['strange']:2d} c={r['cred']:2d} → expect {exp:3d}={hex(exp)} got {b:3d}={hex(b)} {ok}", flush=True)

# =======================================================================
# B. ÅR-MYSTERIET: Kolla header bytes 102-103
#    Om header[102:104] = year[0] (-593), förklaras off-by-1 av header-record
# =======================================================================
print("\n=== B. ÅR-MYSTERIET: HEADER BYTES 102-103 ===", flush=True)
hdr = rnd_data[0:HEADER_SIZE]
hdr_102_103 = hdr[102:104]
v_le = int.from_bytes(hdr_102_103, 'little', signed=True)
v_be = int.from_bytes(hdr_102_103, 'big', signed=True)
print(f"  Header[102:104] = {hdr_102_103.hex()} → LE={v_le}, BE={v_be}", flush=True)
print(f"  records[0]['year'] = {records[0]['year']} (förväntat om off-by-1 förklaras av header)", flush=True)

# Kolla hela headern för year=-593 i alla encodings
yr0 = records[0]['year']  # -593
print(f"\n  Söker {yr0} i header ({HEADER_SIZE} bytes):", flush=True)
for off in range(HEADER_SIZE - 1):
    for w in [2]:
        for le in [True, False]:
            for sg in [True, False]:
                v = int.from_bytes(hdr[off:off+w], 'little' if le else 'big', signed=sg)
                if v == yr0:
                    print(f"    off={off} w={w} {'LE' if le else 'BE'} sg={sg}: {v} ✓", flush=True)

# =======================================================================
# C. BRUTE FORCE AV BYTES 104-111 (post-summary efter year-fältet)
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
    best = {'off': -1, 'match': 0, 'pct': 0.0}
    for off in range(104, 112):
        for w in [1, 2]:
            if off + w > 112:
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
# D. DURATION: Hitta med logtransform
#    QB kanske lagrar ln(dur+1)*256 eller liknande
# =======================================================================
print("\n=== D. DURATION SÖKNING (inkl. log-transform) ===", flush=True)
import math
dur_vals = [r['duration'] for r in records]

# Testa olika transformationer
for transform_name, transform_fn in [
    ('raw', lambda d: d),
    ('log2', lambda d: int(round(math.log2(d+1)*16)) if d > 0 else 0),
    ('sqrt', lambda d: int(round(math.sqrt(d)))),
    ('div10', lambda d: d // 10),
    ('min_to_5min', lambda d: d // 5),
]:
    transformed = [transform_fn(d) for d in dur_vals]
    best = {'off': -1, 'match': 0, 'pct': 0.0}
    for off in range(104, 112):
        for w in [1, 2]:
            if off + w > 112:
                continue
            for sg in [False, True]:
                matches = sum(1 for i in range(N)
                              if int.from_bytes(get_record(i)[off:off+w], 'little', signed=sg) == transformed[i])
                if matches > best['match']:
                    best = {'off': off, 'w': w, 'sg': sg, 'match': matches, 'pct': matches/N*100}
    print(f"  dur_{transform_name:12s}: off={best['off']} w={best['w']} → {best['match']}/{N} ({best['pct']:.1f}%)", flush=True)

# =======================================================================
# E. TERRAIN-INDEX: Skapa unik mapping och testa
# =======================================================================
print("\n=== E. TERRAIN INDEX ===", flush=True)
terrain_codes = sorted(set(r['terrain'] for r in records))
print(f"  {len(terrain_codes)} unika terrain-koder", flush=True)
print(f"  Vanligaste: {Counter(r['terrain'] for r in records).most_common(10)}", flush=True)
t_idx = {t: i for i, t in enumerate(terrain_codes)}
t_vals = [t_idx[r['terrain']] for r in records]

best_t = {'off': -1, 'match': 0, 'pct': 0.0}
for off in range(99, 112):
    for bias in range(0, 5):
        matches = sum(1 for i in range(N) if get_record(i)[off] == t_vals[i] + bias)
        if matches > best_t['match']:
            best_t = {'off': off, 'bias': bias, 'match': matches, 'pct': matches/N*100}
print(f"  Terrain index: off={best_t['off']} bias={best_t['bias']} → {best_t['match']}/{N} ({best_t['pct']:.1f}%)", flush=True)

# =======================================================================
# F. YEAR MED OFF-BY-1: Bekräfta binary[i][102:104] == records[i+1]['year']
# =======================================================================
print("\n=== F. ÅR OFF-BY-1 BEKRÄFTELSE ===", flush=True)
matches_next = sum(1 for i in range(N-1)
                   if int.from_bytes(get_record(i)[102:104], 'little', signed=True) == records[i+1]['year'])
print(f"  binary[i][102:104] == records[i+1]['year']: {matches_next}/{N-1} ({matches_next/(N-1)*100:.1f}%)", flush=True)

# Kolla sista posten
last_val = int.from_bytes(get_record(N-1)[102:104], 'little', signed=True)
print(f"  Sista post ({N-1}) year[{N-1}]={records[N-1]['year']}, bytes[102:104]={last_val}", flush=True)

# =======================================================================
# G. KOMPLETT POST-SUMMARY ANALYS: Korrelation för ALLA fält
#    Testar byte off mot ALLA kända fält (inkl. off-by-1 för år)
# =======================================================================
print("\n=== G. FULL KORRELATION BYTES 99-111 ===", flush=True)

year_next = [records[i+1]['year'] if i < N-1 else records[N-1]['year'] for i in range(N)]

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

print(f"  {'field':12s} {'off':>4} {'w':>2} {'sg':>3} {'match':>7} {'pct':>6}", flush=True)
for fname, vals in all_fields:
    best = {'off': -1, 'match': 0, 'pct': 0.0, 'w': 0, 'sg': False}
    valid_n = sum(1 for v in vals if v >= 0)
    for off in range(99, 112):
        for w in [1, 2]:
            if off + w > 112:
                continue
            for sg in [True, False]:
                matches = sum(1 for i in range(N) if vals[i] >= 0
                              and int.from_bytes(get_record(i)[off:off+w], 'little', signed=sg) == vals[i])
                if matches > best['match']:
                    best = {'off': off, 'w': w, 'sg': sg, 'match': matches, 'pct': matches/valid_n*100}
    print(f"  {fname:12s} {best['off']:>4} {best['w']:>2} {str(best['sg']):>3} {best['match']:>7} {best['pct']:>6.1f}%", flush=True)

print("\nKLAR", flush=True)
