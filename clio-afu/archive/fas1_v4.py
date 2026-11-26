#!/usr/bin/env python3
"""
Fas 1 v4: Differentialanalys + attribut-korrelation + kontinent/land-mappning
"""
import re, struct, json
from pathlib import Path
from collections import Counter, defaultdict

BASE = Path('/home/clioadmin/19.0/clio-tools/clio-afu')
PDF_PATH = BASE / 'data/downloads/Databases/Larry Hatch/derivations/Larry Hatch - full text.pdf'
RND_PATH = BASE / 'data/downloads/Databases/Larry Hatch/original/U.RND'

HEADER_SIZE = 122
RECORD_SIZE = 112
SUMMARY_OFFSET = 21
SUMMARY_END = 99

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
# A. DIFFERENTIALANALYS
# Hitta par (i, j) som delar lon_d, lon_dir men skiljer sig i lon_m
# → vilka bytes ändras?
# =======================================================================
print("\n=== A. DIFFERENTIAL: lon_m-variation (fixerad lon_d) ===", flush=True)

# Gruppera efter (lon_d, lon_dir, lat_d, lat_dir, year)
from itertools import combinations

groups = defaultdict(list)
for i, r in enumerate(records):
    key = (r['lon_d'], r['lon_dir'], r['lat_d'], r['lat_dir'])
    groups[key].append(i)

# Hitta grupper med >= 3 poster och variation i lon_m
diff_candidates = []
for key, idxs in groups.items():
    if len(idxs) < 3:
        continue
    lon_ms = [records[i]['lon_m'] for i in idxs]
    if len(set(lon_ms)) > 1:
        diff_candidates.append((key, idxs))

print(f"  {len(diff_candidates)} grupper med samma lon_d+dir+lat_d+dir men varierande lon_m", flush=True)

# Ta de 5 bästa grupperna (mest varierade lon_m)
diff_candidates.sort(key=lambda x: len(set(records[i]['lon_m'] for i in x[1])), reverse=True)

byte_change_votes = Counter()
for key, idxs in diff_candidates[:10]:
    for i, j in combinations(idxs[:8], 2):
        if records[i]['lon_m'] == records[j]['lon_m']:
            continue
        ri = get_record(i)
        rj = get_record(j)
        # Kolla vilka bytes i 0-21 som ändras
        changed = [b for b in range(21) if ri[b] != rj[b]]
        byte_change_votes.update(changed)

print("  Bytes 0-20 som ändras när lon_m varierar (votes):", flush=True)
for off, cnt in sorted(byte_change_votes.items()):
    print(f"    byte {off:2d}: {cnt}", flush=True)

# =======================================================================
# B. DIFFERENTIAL: lat_m-variation
# =======================================================================
print("\n=== B. DIFFERENTIAL: lat_m-variation (fixerad lat_d) ===", flush=True)

groups2 = defaultdict(list)
for i, r in enumerate(records):
    key = (r['lon_d'], r['lon_dir'], r['lat_d'], r['lat_dir'], r['year'])
    groups2[key].append(i)

byte_change_lat = Counter()
count_pairs = 0
for key, idxs in groups2.values():
    if not isinstance(idxs, list) or len(idxs) < 2:
        continue
    for i, j in combinations(idxs, 2):
        if records[i]['lat_m'] == records[j]['lat_m']:
            continue
        ri = get_record(i)
        rj = get_record(j)
        changed = [b for b in range(21) if ri[b] != rj[b]]
        byte_change_lat.update(changed)
        count_pairs += 1

# Fix: groups2 values are lists
byte_change_lat2 = Counter()
count_pairs2 = 0
for key, idxs in groups2.items():
    if len(idxs) < 2:
        continue
    for i, j in combinations(idxs, 2):
        if records[i]['lat_m'] == records[j]['lat_m']:
            continue
        ri = get_record(i)
        rj = get_record(j)
        changed = [b for b in range(21) if ri[b] != rj[b]]
        byte_change_lat2.update(changed)
        count_pairs2 += 1

print(f"  {count_pairs2} par", flush=True)
print("  Bytes 0-20 som ändras när lat_m varierar:", flush=True)
for off, cnt in sorted(byte_change_lat2.items()):
    print(f"    byte {off:2d}: {cnt}", flush=True)

# =======================================================================
# C. KONTINENT/LAND-MAPPNING: testa om bytes 0-8 eller 13-20
#    konsistent mappar kontinent/land som INTEGER-index
# =======================================================================
print("\n=== C. KONTINENT/LAND SOM INTEGER-INDEX ===", flush=True)

cont_codes = sorted(set(r['continent'] for r in records))
ctry_codes = sorted(set(r['country'] for r in records))
cont_idx = {c: i for i, c in enumerate(cont_codes)}
ctry_idx = {c: i for i, c in enumerate(ctry_codes)}

print(f"  {len(cont_codes)} unika kontinenter, {len(ctry_codes)} unika länder", flush=True)

cont_vals = [cont_idx[r['continent']] for r in records]
ctry_vals = [ctry_idx[r['country']] for r in records]

def brute_index(name, vals, max_val):
    best = {'off': -1, 'pct': 0}
    for off in range(21):
        for bias in range(0, 10):
            matches = sum(1 for i in range(min(N, 5000))
                         if get_record(i)[off] == vals[i] + bias)
            pct = matches / min(N, 5000) * 100
            if pct > best['pct']:
                best = {'off': off, 'bias': bias, 'matches': matches, 'pct': pct}
    return best

res_cont = brute_index('continent', cont_vals, len(cont_codes))
res_ctry = brute_index('country', ctry_vals, len(ctry_codes))
print(f"  Kontinent: off={res_cont['off']}, bias={res_cont.get('bias',0)}, {res_cont['pct']:.1f}%", flush=True)
print(f"  Land:      off={res_ctry['off']}, bias={res_ctry.get('bias',0)}, {res_ctry['pct']:.1f}%", flush=True)

# =======================================================================
# D. PREC-FÄLTET (4 tecken, t.ex. "3111")
#    Letar i bytes 0-20 efter ASCII-strängar av 4 tecken
# =======================================================================
print("\n=== D. PREC-SÖKNING (4-char ASCII) ===", flush=True)
prec_vals = [r['prec'] for r in records]
for off in range(18):
    votes = sum(1 for i in range(min(N, 5000))
                if get_record(i)[off:off+4].decode('latin-1', errors='replace') == prec_vals[i])
    if votes > 1000:
        full = sum(1 for i in range(N)
                   if get_record(i)[off:off+4].decode('latin-1', errors='replace') == prec_vals[i])
        print(f"  prec off={off}: {full}/{N} ({full/N*100:.1f}%)", flush=True)

# =======================================================================
# E. ATTRIBUT-BLOCK: Letar 8-byte block med bit-korrelation
#    mot KEYWORD-sökningar i summary
# =======================================================================
print("\n=== E. ATTRIBUT-BLOCK (8 bytes, 64 bitar) ===", flush=True)

# Byggkworra: poster med starka indikatorer
kw_sets = {
    'LANDING': set(i for i, r in enumerate(records) if any(w in r['summary'] for w in ['LAND', 'TOUCH', 'GROUNDED', 'ALIGHTED'])),
    'DAYLIGHT': set(i for i, r in enumerate(records) if r['hour'] >= 6 and r['hour'] <= 18),
    'ZERO_DUR': set(i for i, r in enumerate(records) if r['duration'] == 0),
    'NONZERO_SC': set(i for i, r in enumerate(records) if r['strange'] > 0),
}

for kw_name, kw_set in kw_sets.items():
    neg_set = set(range(N)) - kw_set
    if len(kw_set) < 100:
        continue
    print(f"  {kw_name}: {len(kw_set)} poster", flush=True)
    best_phi = 0
    best_info = None
    # Testa bits i pre-summary (0-21) och post-summary (99-111)
    for start_off in list(range(0, 14)) + list(range(99, 104)):
        for byte_in_block in range(8):
            byte_off = start_off + byte_in_block
            if byte_off > 111:
                continue
            for bit in range(8):
                set_in_kw = sum(1 for i in kw_set if get_record(i)[byte_off] & (1 << bit))
                clear_in_neg = sum(1 for i in list(neg_set)[:5000] if not (get_record(i)[byte_off] & (1 << bit)))
                phi = (set_in_kw + clear_in_neg) / (len(kw_set) + min(len(neg_set), 5000))
                if phi > best_phi:
                    best_phi = phi
                    best_info = (byte_off, bit, set_in_kw, phi)
    if best_info:
        bo, bb, cnt, phi = best_info
        print(f"    Bästa bit: off={bo}, bit={bb}, phi={phi:.3f}, {cnt}/{len(kw_set)} i set", flush=True)

# =======================================================================
# F. STRANGENESS + CREDIBILITY SOM NIBBLES (packade i 1 byte)
# =======================================================================
print("\n=== F. STRANGENESS+CREDIBILITY SOM PACKAD NIBBLE ===", flush=True)
strange_vals = [r['strange'] for r in records]
cred_vals    = [r['cred']    for r in records]

valid = [(i, s, c) for i, (s, c) in enumerate(zip(strange_vals, cred_vals)) if s >= 0 and c >= 0]
print(f"  {len(valid)} poster med känd S+C", flush=True)

for off in range(99, 112):
    # Testa: high nibble = strangeness, low nibble = credibility
    ms = sum(1 for i, s, c in valid if (get_record(i)[off] >> 4) == s)
    mc = sum(1 for i, s, c in valid if (get_record(i)[off] & 0xF) == c)
    # Testa packed: high=s, low=c
    mpacked = sum(1 for i, s, c in valid if get_record(i)[off] == (s << 4) | c)
    if mpacked > len(valid) * 0.5:
        full_m = sum(1 for i, s, c in valid if get_record(i)[off] == (s << 4) | c)
        print(f"  PACKED(s<<4|c) off={off}: {full_m}/{len(valid)} ({full_m/len(valid)*100:.1f}%)", flush=True)
    if ms > len(valid) * 0.7:
        print(f"  STRANGENESS high-nibble off={off}: {ms}/{len(valid)} ({ms/len(valid)*100:.1f}%)", flush=True)
    if mc > len(valid) * 0.7:
        print(f"  CREDIBILITY  low-nibble  off={off}: {mc}/{len(valid)} ({mc/len(valid)*100:.1f}%)", flush=True)

# Testa också pre-summary
for off in range(21):
    mpacked = sum(1 for i, s, c in valid if get_record(i)[off] == (s << 4) | c)
    if mpacked > len(valid) * 0.5:
        print(f"  PACKED(s<<4|c) pre off={off}: {mpacked}/{len(valid)} ({mpacked/len(valid)*100:.1f}%)", flush=True)

# =======================================================================
# G. Kolla POST-SUMMARY byte-by-byte för post 0-19
# =======================================================================
print("\n=== G. POST-SUMMARY BYTES 99-111 (post 0-19) ===", flush=True)
print("idx  yr  mo  dy   h   m  str crd  ref pag | bytes 99-111", flush=True)
for i in range(20):
    r = records[i]
    raw = get_record(i)
    post = list(raw[99:112])
    print(f"{i:3d} {r['year']:4d} {r['month']:2d} {r['day']:2d} "
          f"{r['hour']:2d} {r['minute']:2d} {r['strange']:2d} {r['cred']:2d} "
          f"{r['ref_no']:3d} {r['page_no']:3d} | "
          + ' '.join(f'{b:02x}' for b in post), flush=True)

print("\nKLAR", flush=True)
