#!/usr/bin/env python3
"""
Fas 1 v6: Off-by-1 för alla datumfält, kontinent/land-index, prec-fält.
"""
import re
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

NM1 = N - 1

# =======================================================================
# A. OFF-BY-1 VERIFIERING: byte 104-111 med offset +1 för alla datumfält
# =======================================================================
print("\n=== A. OFF-BY-1 VERIFIERING (binary[i][off] == pdf[i+1][field]) ===", flush=True)

fields_next = [
    ('year',     [r['year']     for r in records], 2, True),
    ('month',    [r['month']    for r in records], 1, False),
    ('day',      [r['day']      for r in records], 1, False),
    ('hour',     [r['hour']     for r in records], 1, False),
    ('minute',   [r['minute']   for r in records], 1, False),
    ('duration', [r['duration'] for r in records], 1, False),
]

for fname, vals, w, sg in fields_next:
    best = {'off': -1, 'match': 0, 'pct': 0.0}
    for off in range(99, 112):
        if off + w > RECORD_SIZE:
            continue
        matches = sum(1 for i in range(NM1)
                      if int.from_bytes(get_record(i)[off:off+w], 'little', signed=sg) == vals[i+1])
        pct = matches / NM1 * 100
        if matches > best['match']:
            best = {'off': off, 'match': matches, 'pct': pct}
    print(f"  {fname:10s}[i+1] best off={best['off']:3d}: {best['match']}/{NM1} ({best['pct']:.1f}%)", flush=True)

# =======================================================================
# B. FULL OFF-BY-1 sök i HELA posten (bytes 0-111), int8u
# =======================================================================
print("\n=== B. FULL OFF-BY-1 i hela posten (alla offsets 0-111) ===", flush=True)
for fname, vals, w, sg in fields_next:
    if w != 1:
        continue
    best_all = [{'off': -1, 'match': 0, 'pct': 0.0}] * 1
    results = []
    for off in range(0, 112):
        matches = sum(1 for i in range(NM1) if get_record(i)[off] == vals[i+1])
        pct = matches / NM1 * 100
        results.append((pct, off, matches))
    results.sort(reverse=True)
    top3 = results[:3]
    tops = ", ".join(f"off={o}: {m}/{NM1} ({p:.1f}%)" for p, o, m in top3)
    print(f"  {fname:10s}[i+1] top3: {tops}", flush=True)

# =======================================================================
# C. KONTINENT/LAND: INDEX-SÖKNING (med bias) i bytes 0-21
# =======================================================================
print("\n=== C. KONTINENT/LAND NUMERISK INDEX (bytes 0-20) ===", flush=True)
cont_codes = sorted(set(r['continent'] for r in records))
ctry_codes = sorted(set(r['country'] for r in records))
print(f"  {len(cont_codes)} kontinentkoder, {len(ctry_codes)} landskoder", flush=True)

SAMPLE = min(N, 5000)

for fname, codes, get_val in [
    ('continent', cont_codes, lambda r: r['continent']),
    ('country',   ctry_codes, lambda r: r['country']),
]:
    code_idx = {c: i for i, c in enumerate(codes)}
    vals = [code_idx[get_val(r)] for r in records]

    best = {'off': -1, 'bias': 0, 'match': 0, 'pct': 0.0}
    for off in range(22):
        for bias in range(0, 30):
            matches = sum(1 for i in range(SAMPLE) if get_record(i)[off] == vals[i] + bias)
            if matches > best['match']:
                best = {'off': off, 'bias': bias, 'match': matches, 'pct': matches/SAMPLE*100}

    full_m = sum(1 for i in range(N) if get_record(i)[best['off']] == vals[i] + best['bias'])
    print(f"  {fname}: off={best['off']}, bias={best['bias']}: {full_m}/{N} ({full_m/N*100:.1f}%)", flush=True)

# =======================================================================
# D. OFF-BY-1 FÖR KONTINENT/LAND
# =======================================================================
print("\n=== D. KONTINENT/LAND OFF-BY-1 ===", flush=True)
for fname, codes, get_val in [
    ('continent', cont_codes, lambda r: r['continent']),
    ('country',   ctry_codes, lambda r: r['country']),
]:
    code_idx = {c: i for i, c in enumerate(codes)}
    vals = [code_idx[get_val(r)] for r in records]

    best = {'off': -1, 'bias': 0, 'match': 0, 'pct': 0.0}
    for off in range(22):
        for bias in range(0, 30):
            matches = sum(1 for i in range(NM1) if get_record(i)[off] == vals[i+1] + bias)
            if matches > best['match']:
                best = {'off': off, 'bias': bias, 'match': matches, 'pct': matches/NM1*100}
    print(f"  {fname}[i+1]: off={best['off']}, bias={best['bias']}: {best['match']}/{NM1} ({best['pct']:.1f}%)", flush=True)

# =======================================================================
# E. ASCII KONTINENT/LAND I BYTES 0-8 vs 13-20
# =======================================================================
print("\n=== E. ASCII-SÖKNING KONTINENT/LAND ===", flush=True)
for fname, get_val in [('continent', lambda r: r['continent']), ('country', lambda r: r['country'])]:
    vals = [get_val(r) for r in records]
    found = False
    for off in list(range(0, 9)) + list(range(13, 21)):
        if off + 3 > 21:
            continue
        count = 0
        for i in range(SAMPLE):
            try:
                s = get_record(i)[off:off+3].decode('ascii')
                if s == vals[i]:
                    count += 1
            except:
                pass
        if count > 500:
            full = 0
            for i in range(N):
                try:
                    s = get_record(i)[off:off+3].decode('ascii')
                    if s == vals[i]:
                        full += 1
                except:
                    pass
            print(f"  {fname} ASCII off={off}: {full}/{N} ({full/N*100:.1f}%)", flush=True)
            found = True
    if not found:
        print(f"  {fname}: inte hittat som ASCII i bytes 0-8 / 13-20", flush=True)

# =======================================================================
# F. PREC-FÄLT (4 chars) — ALLA OFFSETS 0-111
# =======================================================================
print("\n=== F. PREC-FÄLT SÖKNING ===", flush=True)
prec_vals = [r['prec'] for r in records]

# ASCII 4 chars
found_prec = False
for off in range(0, 109):
    count = sum(1 for i in range(SAMPLE)
                if get_record(i)[off:off+4].decode('latin-1', errors='replace') == prec_vals[i])
    if count > 1000:
        full = sum(1 for i in range(N)
                   if get_record(i)[off:off+4].decode('latin-1', errors='replace') == prec_vals[i])
        print(f"  prec ASCII off={off}: {full}/{N} ({full/N*100:.1f}%)", flush=True)
        found_prec = True

if not found_prec:
    print("  prec: inte hittat som 4-char ASCII (>20%)", flush=True)

# Prec som int16 (3111, 2321, etc.)
prec_int = []
for p in prec_vals:
    try:
        prec_int.append(int(p))
    except:
        prec_int.append(-1)

valid_prec = sum(1 for v in prec_int if v >= 0)
print(f"  {valid_prec}/{N} prec-värden är numeriska (ex: '3111')", flush=True)

best_pi = {'off': -1, 'match': 0, 'pct': 0.0}
for off in range(0, 21):
    m = sum(1 for i in range(SAMPLE)
            if prec_int[i] >= 0
            and int.from_bytes(get_record(i)[off:off+2], 'little', signed=False) == prec_int[i])
    if m > best_pi['match']:
        best_pi = {'off': off, 'match': m, 'pct': m/SAMPLE*100}

full_pi = sum(1 for i in range(N)
              if prec_int[i] >= 0
              and int.from_bytes(get_record(i)[best_pi['off']:best_pi['off']+2], 'little', signed=False) == prec_int[i])
print(f"  prec int16 best off={best_pi['off']}: {full_pi}/{valid_prec} ({full_pi/max(valid_prec,1)*100:.1f}%)", flush=True)

# Prec as 4 NIBBLES packed into 2 bytes: each digit = 0-9 fits in nibble
# "3111" → 0x31 0x11?
prec_nibble = []
for p in prec_vals:
    if len(p) == 4 and p.isdigit():
        b0 = (int(p[0]) << 4) | int(p[1])
        b1 = (int(p[2]) << 4) | int(p[3])
        prec_nibble.append((b0, b1))
    else:
        prec_nibble.append((-1, -1))

valid_nib = sum(1 for b0, b1 in prec_nibble if b0 >= 0)
print(f"  {valid_nib} prec-värden som nibble-packed", flush=True)

best_nib = {'off': -1, 'match': 0, 'pct': 0.0}
for off in range(0, 21):
    m = sum(1 for i in range(SAMPLE)
            if prec_nibble[i][0] >= 0
            and get_record(i)[off] == prec_nibble[i][0]
            and get_record(i)[off+1] == prec_nibble[i][1])
    if m > best_nib['match']:
        best_nib = {'off': off, 'match': m, 'pct': m/SAMPLE*100}

full_nib = sum(1 for i in range(N)
               if prec_nibble[i][0] >= 0
               and get_record(i)[best_nib['off']] == prec_nibble[i][0]
               and get_record(i)[best_nib['off']+1] == prec_nibble[i][1])
print(f"  prec nibble2 best off={best_nib['off']}: {full_nib}/{valid_nib} ({full_nib/max(valid_nib,1)*100:.1f}%)", flush=True)

# =======================================================================
# G. BYTE-DUMP bytes 0-20 för post 0-9 (med kända fält)
# =======================================================================
print("\n=== G. PRE-SUMMARY BYTES 0-20 (post 0-9) ===", flush=True)
print(f"{'idx':>3} {'yr':>5} {'mo':>2} {'dy':>2} {'h':>2} {'m':>2} {'lon':>12} {'lat':>12} | bytes 0-20", flush=True)
for i in range(10):
    r = records[i]
    raw = get_record(i)
    lon_str = f"{r['lon_d']}:{r['lon_m']}:{r['lon_s']}{r['lon_dir']}"
    lat_str = f"{r['lat_d']}:{r['lat_m']}:{r['lat_s']}{r['lat_dir']}"
    print(f"{i:3d} {r['year']:5d} {r['month']:2d} {r['day']:2d} "
          f"{r['hour']:2d} {r['minute']:2d} {lon_str:>12} {lat_str:>12} | "
          + ' '.join(f'{b:02x}' for b in raw[0:21]), flush=True)

# =======================================================================
# H. LATITUDE ARCSECOND-TEST för bytes 0-8 (med +/- sign och multipliers)
# =======================================================================
print("\n=== H. LON/LAT ARCSECOND-TEST bytes 0-8 ===", flush=True)

def to_arcsec_lon(r):
    v = r['lon_d']*3600 + r['lon_m']*60 + r['lon_s']
    return -v if r['lon_dir'] == 'E' else v  # sign convention

def to_arcsec_lat(r):
    v = r['lat_d']*3600 + r['lat_m']*60 + r['lat_s']
    return v if r['lat_dir'] == 'N' else -v

lon_arcsec = [to_arcsec_lon(r) for r in records]
lat_arcsec = [to_arcsec_lat(r) for r in records]

# Test int16 LE/BE signed
for fname, arcvals in [('lon', lon_arcsec), ('lat', lat_arcsec)]:
    for off in range(0, 8):
        for sg in [True, False]:
            for divisor in [1, 2, 3, 4, 5, 6, 10, 20, 60]:
                m = sum(1 for i in range(SAMPLE)
                        if int.from_bytes(get_record(i)[off:off+2], 'little', signed=sg) == arcvals[i] // divisor)
                if m / SAMPLE > 0.35:
                    full = sum(1 for i in range(N)
                               if int.from_bytes(get_record(i)[off:off+2], 'little', signed=sg) == arcvals[i] // divisor)
                    print(f"  {fname} arcsec//{divisor} LE off={off}: {full}/{N} ({full/N*100:.1f}%)", flush=True)

# Test mot NÄSTA posts koordinater (off-by-1)
print("\n  Off-by-1 test för koordinater:", flush=True)
for fname, arcvals in [('lon', lon_arcsec), ('lat', lat_arcsec)]:
    for off in range(0, 8):
        for sg in [True, False]:
            for divisor in [1, 2, 3, 4, 5, 6, 10, 20, 60]:
                m = sum(1 for i in range(NM1)
                        if int.from_bytes(get_record(i)[off:off+2], 'little', signed=sg) == arcvals[i+1] // divisor)
                if m / NM1 > 0.35:
                    full = sum(1 for i in range(NM1)
                               if int.from_bytes(get_record(i)[off:off+2], 'little', signed=sg) == arcvals[i+1] // divisor)
                    print(f"  {fname}[i+1] arcsec//{divisor} LE off={off}: {full}/{NM1} ({full/NM1*100:.1f}%)", flush=True)

print("\nKLAR", flush=True)
