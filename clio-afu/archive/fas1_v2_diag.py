#!/usr/bin/env python3
"""
Fas 1 v2: Förbättrad diagnostik med korrekt summary-offset (21, inte 31).
Binärfält: bytes 0-20 (pre-summary) + bytes 99-111 (post-summary).
"""
import re
import sys
import json
import struct
from pathlib import Path
from collections import Counter

BASE = Path('/home/clioadmin/19.0/clio-tools/clio-afu')
PDF_PATH = BASE / 'data/downloads/Databases/Larry Hatch/derivations/Larry Hatch - full text.pdf'
RND_PATH = BASE / 'data/downloads/Databases/Larry Hatch/original/U.RND'
DOCS_DIR = BASE / 'docs'
DOCS_DIR.mkdir(exist_ok=True)

HEADER_SIZE = 122
RECORD_SIZE = 112
TOTAL_RECORDS = 18122
SUMMARY_OFFSET = 21     # KORRIGERAT från plan (som angav 31 = abs_offset mod 112)
SUMMARY_END = 99        # 21 + 78 = 99
# Binärfält: 0-20 (pre) + 99-111 (post) = 34 bytes totalt

# -------------------------------------------------------------------
# 1. PDF-parsning (bevisad korrekt)
# -------------------------------------------------------------------
DATA_LINE_RE = re.compile(
    r"^\s*(\d+):\s+(-?\d{1,4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}:\d{2})"
    r"\s+(\d+)"
    r"\s+(\d+):(\d+):(\d+)\s+([EWZ])"
    r"\s+(\d+):(\d+):(\d+)\s+([NSQ])"
    r"\s+(\S{4})\s+([A-Z0-9.\-]{3})\s+([A-Z0-9.\-]{3})"
)
SC_RE = re.compile(r"([0-9A-Fa-f]):([0-9A-Fa-f])\s*$")
REF_LINE_RE = re.compile(r"^Ref#\s+(\d+)\s+.*?Page No\.\s+(\d+)\s*:\s*(\S.*?)$")

def parse_pdf(path):
    import fitz
    doc = fitz.open(str(path))
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    lines = text.split('\n')
    records = []
    i = 0
    while i < len(lines):
        m = DATA_LINE_RE.match(lines[i])
        if m:
            sc_m = SC_RE.search(lines[i])
            time_s = m.group(5)
            summary = lines[i+1].strip() if i+1 < len(lines) else ''
            ref_no, page_no, terrain = 0, 0, ''
            if i+2 < len(lines):
                rm = REF_LINE_RE.match(lines[i+2])
                if rm:
                    ref_no, page_no, terrain = int(rm.group(1)), int(rm.group(2)), rm.group(3).strip()
            records.append({
                'rec_no': int(m.group(1)),
                'year': int(m.group(2)), 'month': int(m.group(3)), 'day': int(m.group(4)),
                'hour': int(time_s.split(':')[0]), 'minute': int(time_s.split(':')[1]),
                'duration': int(m.group(6)),
                'lon_d': int(m.group(7)), 'lon_m': int(m.group(8)), 'lon_s': int(m.group(9)),
                'lon_dir': m.group(10),
                'lat_d': int(m.group(11)), 'lat_m': int(m.group(12)), 'lat_s': int(m.group(13)),
                'lat_dir': m.group(14),
                'prec': m.group(15), 'continent': m.group(16), 'country': m.group(17),
                'strange': int(sc_m.group(1), 16) if sc_m else -1,
                'cred': int(sc_m.group(2), 16) if sc_m else -1,
                'summary': summary, 'ref_no': ref_no, 'page_no': page_no, 'terrain': terrain,
            })
            i += 3
        else:
            i += 1
    return records

print("Parserar PDF...", flush=True)
records = parse_pdf(PDF_PATH)
assert len(records) == TOTAL_RECORDS, f"Fel: {len(records)} poster"
print(f"  OK: {len(records)} poster", flush=True)

rnd_data = RND_PATH.read_bytes()
def get_record(i):
    return rnd_data[HEADER_SIZE + i * RECORD_SIZE : HEADER_SIZE + (i+1) * RECORD_SIZE]

# -------------------------------------------------------------------
# 2. Verifiera rätt summary-offset
# -------------------------------------------------------------------
print("\nVerifierar summary vid offset 21...", flush=True)
ok = 0
for i in range(TOTAL_RECORDS):
    raw = get_record(i)
    bin_summary = raw[SUMMARY_OFFSET:SUMMARY_END].decode('latin-1').rstrip('\x00').rstrip()
    pdf_summary = records[i]['summary'][:78].rstrip()
    if bin_summary == pdf_summary:
        ok += 1
print(f"  Offset 21: {ok}/{TOTAL_RECORDS} matchar ({ok/TOTAL_RECORDS*100:.2f}%)", flush=True)

# -------------------------------------------------------------------
# 3. Fullständigt hex-dump av post 0-4
# -------------------------------------------------------------------
print("\n=== HEX DUMP POST 0-4 ===", flush=True)
for i in range(5):
    raw = get_record(i)
    r = records[i]
    print(f"\nPost {i}: rec_no={r['rec_no']}, year={r['year']}, month={r['month']}, "
          f"day={r['day']}, h={r['hour']}, m={r['minute']}, dur={r['duration']}", flush=True)
    print(f"  lon={r['lon_d']}:{r['lon_m']}:{r['lon_s']}{r['lon_dir']} "
          f"lat={r['lat_d']}:{r['lat_m']}:{r['lat_s']}{r['lat_dir']}", flush=True)
    print(f"  prec={r['prec']}, cont={r['continent']}, ctry={r['country']}, "
          f"state={r['state'] if 'state' in r else '?'}", flush=True)
    print(f"  s={r['strange']}, c={r['cred']}, ref={r['ref_no']}, pg={r['page_no']}", flush=True)
    pre = raw[:SUMMARY_OFFSET]
    post = raw[SUMMARY_END:]
    print(f"  PRE  (0-20):   {pre.hex()} | {list(pre)}", flush=True)
    print(f"  POST (99-111): {post.hex()} | {list(post)}", flush=True)
    print(f"  SUM  : {raw[SUMMARY_OFFSET:SUMMARY_END].decode('latin-1', errors='replace')[:50]}", flush=True)

# -------------------------------------------------------------------
# 4. Försök dekoda år med flera metoder
# -------------------------------------------------------------------
print("\n=== DECODING EXPERIMENT - YEAR ===", flush=True)
print("Söker 'year=-593' i post 0 bytes 0-20 och 99-111:", flush=True)
raw0 = get_record(0)
pre0 = raw0[:SUMMARY_OFFSET]
post0 = raw0[SUMMARY_END:]

print(f"  pre0: {list(pre0)}", flush=True)
print(f"  post0: {list(post0)}", flush=True)

# Känd info: år=-593 → 2-byte signed LE = 0xFDAF = [175, 253]
year_bytes_le = (-593).to_bytes(2, 'little', signed=True)
year_bytes_be = (-593).to_bytes(2, 'big', signed=True)
print(f"  year -593 LE bytes: {list(year_bytes_le)} = {year_bytes_le.hex()}", flush=True)
print(f"  year -593 BE bytes: {list(year_bytes_be)} = {year_bytes_be.hex()}", flush=True)

# Sök i alla bytes
all_bytes = list(pre0) + list(post0)
print(f"  Alla 34 bytes: {all_bytes}", flush=True)

# Kolla om år finns gömmt med offset: år+X = värde i byten
for offset in [0, 100, 500, 600, 1000, 32768]:
    val = -593 + offset
    if 0 <= val <= 65535:
        b_le = val.to_bytes(2, 'little')
        for j in range(len(all_bytes)-1):
            if list(all_bytes[j:j+2]) == list(b_le):
                actual_off = j if j < 21 else j - 21 + 99
                print(f"  TRÄFF: year+{offset}={val} LE vid all_idx={j} (record_off={actual_off})", flush=True)

# Kolla om år är packed i 4 bytes med månad/dag
# Exempel: [year as 2B][month as 1B][day as 1B]
target_4b = struct.pack('<hBB', -593, 1, 1)
print(f"  year+month+day packed LE: {list(target_4b)} = {target_4b.hex()}", flush=True)
for j in range(len(all_bytes)-3):
    if list(all_bytes[j:j+4]) == list(target_4b):
        print(f"  TRÄFF 4B vid all_idx={j}", flush=True)

# Kolla om det är BCD: -593 är svårt BCD, men prova år som positiv med century-flagga
# Kolla 1965 i en post med känt år
# Hitta en post med ett positivt "modernt" år
modern_posts = [(i, r) for i, r in enumerate(records) if 1900 <= r['year'] <= 1999]
print(f"\n  {len(modern_posts)} poster med år 1900-1999", flush=True)
# Testa de första 10
for i, r in modern_posts[:5]:
    raw = get_record(i)
    pre = raw[:SUMMARY_OFFSET]
    post_b = raw[SUMMARY_END:]
    yr = r['year']
    all_b = list(pre) + list(post_b)
    yr_le = yr.to_bytes(2, 'little')
    yr_be = yr.to_bytes(2, 'big')
    found = False
    for j in range(len(all_b)-1):
        if list(all_b[j:j+2]) == list(yr_le):
            actual_off = j if j < 21 else j - 21 + 99
            print(f"  Post {i} år={yr} LE {list(yr_le)}: TRÄFF all_idx={j} off={actual_off}", flush=True)
            found = True
        elif list(all_b[j:j+2]) == list(yr_be):
            actual_off = j if j < 21 else j - 21 + 99
            print(f"  Post {i} år={yr} BE {list(yr_be)}: TRÄFF all_idx={j} off={actual_off}", flush=True)
            found = True
    if not found:
        print(f"  Post {i} år={yr}: INGEN TRÄFF i plain int16. pre={pre.hex()} post={post_b.hex()}", flush=True)

# -------------------------------------------------------------------
# 5. Brute-force med korrekt offsetar (0-20 och 99-111)
# -------------------------------------------------------------------
print("\n=== BRUTE FORCE (0-20 + 99-111) ===", flush=True)

n_rec = TOTAL_RECORDS

def brute_force_v2(field_name, pdf_vals, allow_signed=False, try_float=False):
    best = {'field': field_name, 'offset': -1, 'width': 0, 'match': 0, 'score': 0.0, 'pct': 0.0, 'encoding': ''}
    # Kandidatoffsetar: pre (0-20) + post (99-111)
    candidates = [(o, 'pre') for o in range(21)] + [(o, 'post') for o in range(99, 112)]

    for (base_off, region) in candidates:
        for w in [1, 2, 4]:
            end = base_off + w
            # Välid range?
            if region == 'pre' and end > 21:
                continue
            if region == 'post' and end > 112:
                continue
            for little_end in ([True, False] if w > 1 else [True]):
                for is_signed in ([True, False] if allow_signed else [False]):
                    matches = 0
                    for i in range(n_rec):
                        raw = get_record(i)
                        b = raw[base_off:base_off+w]
                        val = int.from_bytes(b, 'little' if little_end else 'big', signed=is_signed)
                        if val == pdf_vals[i]:
                            matches += 1
                    score = matches / n_rec
                    if score > best['score']:
                        best = {
                            'field': field_name, 'offset': base_off, 'width': w,
                            'little_endian': little_end, 'signed': is_signed,
                            'match': matches, 'score': score, 'pct': round(score*100, 2),
                            'encoding': f"int{w*8}{'s' if is_signed else 'u'}_{'LE' if little_end else 'BE'}"
                        }
        # Prova float (SINGLE) för numeriska fält
        if try_float and base_off + 4 <= (21 if region == 'pre' else 112):
            matches = 0
            for i in range(n_rec):
                raw = get_record(i)
                b = raw[base_off:base_off+4]
                val = struct.unpack('<f', b)[0]
                if abs(val - pdf_vals[i]) < 0.5:
                    matches += 1
            score = matches / n_rec
            if score > best['score']:
                best = {
                    'field': field_name, 'offset': base_off, 'width': 4,
                    'match': matches, 'score': score, 'pct': round(score*100, 2),
                    'encoding': 'float32_LE'
                }
    return best

fields = [
    ('year',      [r['year']     for r in records], True,  True),
    ('month',     [r['month']    for r in records], False, False),
    ('day',       [r['day']      for r in records], False, False),
    ('hour',      [r['hour']     for r in records], False, False),
    ('minute',    [r['minute']   for r in records], False, False),
    ('duration',  [r['duration'] for r in records], False, True),
    ('lon_d',     [r['lon_d']    for r in records], False, False),
    ('lon_m',     [r['lon_m']    for r in records], False, False),
    ('lon_s',     [r['lon_s']    for r in records], False, False),
    ('lat_d',     [r['lat_d']    for r in records], False, False),
    ('lat_m',     [r['lat_m']    for r in records], False, False),
    ('lat_s',     [r['lat_s']    for r in records], False, False),
    ('ref_no',    [r['ref_no']   for r in records], False, False),
    ('page_no',   [r['page_no']  for r in records], False, False),
    ('strange',   [r['strange']  for r in records], False, False),
    ('cred',      [r['cred']     for r in records], False, False),
]

results = {}
for fname, vals, allow_signed, try_float in fields:
    res = brute_force_v2(fname, vals, allow_signed=allow_signed, try_float=try_float)
    results[fname] = res
    print(f"  {fname:12s}: off={res['offset']:3d}, {res['encoding']:20s}, "
          f"{res['match']}/{n_rec} ({res['pct']}%)", flush=True)

# -------------------------------------------------------------------
# 6. ASCII-fält med korrekt offset
# -------------------------------------------------------------------
print("\n=== ASCII-KODER (0-20 + 99-111) ===", flush=True)

def find_ascii3(field_vals, region='pre', sample=2000):
    votes = Counter()
    for i in range(min(sample, n_rec)):
        raw = get_record(i)
        target = field_vals[i]
        offsets = range(19) if region == 'pre' else range(99, 110)
        for off in offsets:
            try:
                s = raw[off:off+3].decode('ascii')
                if s == target:
                    votes[off] += 1
            except Exception:
                pass
    return votes

state_vals = [r['country'] for r in records]  # land = 3-char code
cont_vals = [r['continent'] for r in records]

# Vi vet redan att CHL är vid offset 9. Försök verifiera mot alla poster.
print("  Söker state/country 3-char kod...", flush=True)
for region in ['pre', 'post']:
    v = find_ascii3(state_vals, region=region)
    if v:
        top = v.most_common(3)
        print(f"  Country ({region}) top-3: {top}", flush=True)
        for off, cnt in top[:1]:
            m = sum(1 for i in range(n_rec)
                   if get_record(i)[off:off+3].decode('latin-1') == state_vals[i])
            print(f"    off={off}: {m}/{n_rec} ({m/n_rec*100:.1f}%)", flush=True)

print("  Söker continent 3-char kod...", flush=True)
for region in ['pre', 'post']:
    v = find_ascii3(cont_vals, region=region)
    if v:
        top = v.most_common(3)
        print(f"  Continent ({region}) top-3: {top}", flush=True)

# -------------------------------------------------------------------
# 7. Analysera bytes 99-111 noggrannare
# -------------------------------------------------------------------
print("\n=== BYTES 99-111 FÖR POST 0-9 ===", flush=True)
for i in range(10):
    raw = get_record(i)
    r = records[i]
    post = raw[99:]
    print(f"  Post {i} (yr={r['year']:5d} s={r['strange']} c={r['cred']} ref={r['ref_no']:3d} "
          f"pg={r['page_no']:3d} cont={r['continent']} ctry={r['country']}): "
          f"{post.hex()} | {list(post)}", flush=True)

# -------------------------------------------------------------------
# 8. Spara resultat
# -------------------------------------------------------------------
output = DOCS_DIR / 'urnd_offsets_v2.json'
with open(output, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResultat sparade: {output}", flush=True)
print("=== KLAR ===", flush=True)
