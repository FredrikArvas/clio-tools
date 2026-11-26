#!/usr/bin/env python3
"""
Fas 1 v4b: Fixad differentialanalys. Fokus: byte 1 vs lon_m, bytes 13-19 vs lat.
"""
import re
from pathlib import Path
from collections import Counter, defaultdict
from itertools import combinations

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
# A. DIFFERENTIAL: lat_m (fixad) — KORRIGERAT
# =======================================================================
print("\n=== A. DIFFERENTIAL: lat_m-variation ===", flush=True)
groups2 = defaultdict(list)
for i, r in enumerate(records):
    key = (r['lon_d'], r['lon_dir'], r['lat_d'], r['lat_dir'], r['year'])
    groups2[key].append(i)

byte_change_lat = Counter()
count_pairs = 0
for key, idxs in groups2.items():  # .items() not .values()!
    if len(idxs) < 2:
        continue
    for i, j in combinations(idxs, 2):
        if records[i]['lat_m'] == records[j]['lat_m']:
            continue
        ri = get_record(i)
        rj = get_record(j)
        changed = [b for b in range(21) if ri[b] != rj[b]]
        byte_change_lat.update(changed)
        count_pairs += 1

print(f"  {count_pairs} par", flush=True)
print("  Bytes 0-20 som ändras när lat_m varierar:", flush=True)
for off, cnt in sorted(byte_change_lat.items()):
    print(f"    byte {off:2d}: {cnt}", flush=True)

# =======================================================================
# B. ANALYSE: byte 1 vs lon_m
#    Bekräfta att byte 1 enkoderar lon_m och hitta formeln
# =======================================================================
print("\n=== B. BYTE 1 vs LON_M (FORMULA-SÖK) ===", flush=True)

# Samla alla (byte1_value, lon_m) par
samples = []
for i in range(N):
    r = records[i]
    b1 = get_record(i)[1]
    samples.append((b1, r['lon_m'], r['lon_d'], r['lon_dir'], r['lon_s']))

# Räkna frekvens per (byte1, lon_m)
freq = Counter((b1, lm) for b1, lm, *_ in samples)

# Visa de vanligaste lon_m-värdena med typisk byte 1
print("  lon_m → median(byte1):", flush=True)
from statistics import median
for lm in sorted(set(s[1] for s in samples)):
    b1s = [s[0] for s in samples if s[1] == lm]
    if len(b1s) > 10:
        print(f"  lon_m={lm:2d}: byte1 median={median(b1s):.0f}, min={min(b1s)}, max={max(b1s)}, n={len(b1s)}", flush=True)

# Testa om byte1 = f(lon_d, lon_m, lon_s, lon_dir)
# Hypotes 1: byte1 = (lon_m * K + lon_s/20) mod 256
# Prova K=3
print("\n  Testar byte1 = (lon_m * K + lon_s/20) mod 256:", flush=True)
for K in [1, 2, 3, 4, 5]:
    matches = sum(1 for b1, lm, ld, ldir, ls in samples
                  if b1 == (lm * K + ls // 20) % 256)
    print(f"    K={K}: {matches}/{N} ({matches/N*100:.1f}%)", flush=True)

# Hypotes 2: byte1 = lon_m (direkt)
matches_direct = sum(1 for b1, lm, *_ in samples if b1 == lm)
print(f"  Direkt: byte1==lon_m: {matches_direct}/{N} ({matches_direct/N*100:.1f}%)", flush=True)

# Hypotes 3: byte1 = lon_m * 4 + lon_s/15
for K in [3, 4]:
    for S_div in [15, 20]:
        matches = sum(1 for b1, lm, ld, ldir, ls in samples
                      if b1 == (lm * K + ls // S_div) % 256)
        print(f"  K={K} S/{S_div}: {matches}/{N} ({matches/N*100:.1f}%)", flush=True)

# =======================================================================
# C. BYTES 13-19 vs LAT_M, LAT_D, LON_D
# =======================================================================
print("\n=== C. BYTES 13-19 vs KOORDINAT-FÄLT ===", flush=True)

# Korrelation byte 13 vs lon_d + lat_d
print("  byte 13 vs fält:", flush=True)
for fname, vals in [
    ('lon_d', [r['lon_d'] for r in records]),
    ('lat_d', [r['lat_d'] for r in records]),
    ('lon_m', [r['lon_m'] for r in records]),
    ('lat_m', [r['lat_m'] for r in records]),
]:
    for off in [13, 14, 15, 16, 17, 18, 19, 20]:
        for w in [1, 2]:
            for sg in [True, False]:
                if off + w > 21:
                    continue
                matches = sum(1 for i in range(N)
                              if int.from_bytes(get_record(i)[off:off+w], 'little', signed=sg) == vals[i])
                if matches > N * 0.5:
                    print(f"  {fname} @ off={off} w={w} sg={sg}: {matches}/{N} ({matches/N*100:.1f}%)", flush=True)

# =======================================================================
# D. POST-SUMMARY FULL: bytes 99-111 för post 0-29
# =======================================================================
print("\n=== D. POST-SUMMARY BYTES 99-111 (post 0-29) ===", flush=True)
print("idx  yr  mo  dy   h   m  dur  str crd  ref pag | bytes 99-111", flush=True)
for i in range(30):
    r = records[i]
    raw = get_record(i)
    post = list(raw[99:112])
    print(f"{i:3d} {r['year']:5d} {r['month']:2d} {r['day']:2d} "
          f"{r['hour']:2d} {r['minute']:2d} {r['duration']:5d} "
          f"{r['strange']:2d} {r['cred']:2d} "
          f"{r['ref_no']:4d} {r['page_no']:4d} | "
          + ' '.join(f'{b:02x}' for b in post), flush=True)

# =======================================================================
# E. PREC-SÖKNING i bytes 0-20 OCH 13-20 separat
# =======================================================================
print("\n=== E. PREC-FÄLT SÖKNING ===", flush=True)
prec_vals = [r['prec'] for r in records]
for off in range(18):
    full = sum(1 for i in range(N)
               if get_record(i)[off:off+4].decode('latin-1', errors='replace') == prec_vals[i])
    if full > N * 0.5:
        print(f"  prec off={off}: {full}/{N} ({full/N*100:.1f}%)", flush=True)

# =======================================================================
# F. BYTE 0 vs LON_D + lon_dir ENCODING TEST
# =======================================================================
print("\n=== F. BYTE 0 vs LON_D/DIR ===", flush=True)
for bias in range(-10, 10):
    for negate in [False, True]:
        matches = 0
        for i in range(N):
            r = records[i]
            b = get_record(i)[0]
            expected = r['lon_d'] + bias
            if negate:
                expected = -expected
            expected = expected % 256
            if b == expected:
                matches += 1
        if matches > N * 0.3:
            print(f"  byte0 == {'neg ' if negate else ''}lon_d+{bias}: {matches}/{N} ({matches/N*100:.1f}%)", flush=True)

# Testa också: byte 0 encodes DIFFERENT field (lat_d, lon_d+lon_m scaled...)
# Specifikt: (256 - lon_d) för E och lon_d för W (som per sign-convention)
for off in range(8):
    matches_E = sum(1 for i in range(N) if records[i]['lon_dir'] == 'E'
                    and get_record(i)[off] == (256 - records[i]['lon_d']) % 256)
    matches_W = sum(1 for i in range(N) if records[i]['lon_dir'] == 'W'
                    and get_record(i)[off] == records[i]['lon_d'])
    total = sum(1 for r in records if r['lon_dir'] in ['E', 'W'])
    combined = matches_E + matches_W
    if combined > total * 0.3:
        print(f"  off={off}: (256-lon_d) for E / lon_d for W: {combined}/{total} ({combined/total*100:.1f}%)", flush=True)

print("\nKLAR", flush=True)
