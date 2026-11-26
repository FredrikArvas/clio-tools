#!/usr/bin/env python3
"""
Fas 1: PDF-parser + brute-force U.RND-formatslösare
Parsar ground-truth från PDF, löser sedan byteoffsetar i U.RND binärfil.
"""
import re
import sys
import json
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

# -------------------------------------------------------------------
# 1. Parsa PDF till ground-truth-poster
# -------------------------------------------------------------------
DATA_LINE_RE = re.compile(
    r"^\s*(\d+):\s+(-?\d{1,4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}:\d{2})"
    r"\s+(\d+)"
    r"\s+(\d+):(\d+):(\d+)\s+([EWZ])"
    r"\s+(\d+):(\d+):(\d+)\s+([NSQ])"
    r"\s+(\S{4})\s+([A-Z0-9.\-]{3})\s+([A-Z0-9.\-]{3})"
)

SC_RE = re.compile(r"([0-9A-Fa-f]):([0-9A-Fa-f])\s*$")

REF_LINE_RE = re.compile(
    r"^Ref#\s+(\d+)\s+.*?Page No\.\s+(\d+)\s*:\s*(\S.*?)$"
)

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
            rec_no = int(m.group(1))
            year   = int(m.group(2))
            month  = int(m.group(3))
            day    = int(m.group(4))
            time_s = m.group(5)
            hh, mm = int(time_s.split(':')[0]), int(time_s.split(':')[1])
            duration = int(m.group(6))
            lon_d  = int(m.group(7))
            lon_m  = int(m.group(8))
            lon_s  = int(m.group(9))
            lon_dir = m.group(10)
            lat_d  = int(m.group(11))
            lat_m  = int(m.group(12))
            lat_s  = int(m.group(13))
            lat_dir = m.group(14)
            prec   = m.group(15)
            continent = m.group(16)
            country   = m.group(17)
            # Strangeness:credibility kommer efter country på samma rad
            sc_m = SC_RE.search(lines[i])
            strange = int(sc_m.group(1), 16) if sc_m else -1
            cred    = int(sc_m.group(2), 16) if sc_m else -1

            summary = lines[i+1].strip() if i+1 < len(lines) else ''
            ref_no = 0
            page_no = 0
            terrain = ''
            if i+2 < len(lines):
                rm = REF_LINE_RE.match(lines[i+2])
                if rm:
                    ref_no = int(rm.group(1))
                    page_no = int(rm.group(2))
                    terrain = rm.group(3).strip()

            records.append({
                'rec_no': rec_no,
                'year': year, 'month': month, 'day': day,
                'hour': hh, 'minute': mm,
                'duration': duration,
                'lon_d': lon_d, 'lon_m': lon_m, 'lon_s': lon_s,
                'lon_dir': lon_dir,
                'lat_d': lat_d, 'lat_m': lat_m, 'lat_s': lat_s,
                'lat_dir': lat_dir,
                'prec': prec,
                'continent': continent, 'country': country,
                'strange': strange, 'cred': cred,
                'summary': summary,
                'ref_no': ref_no, 'page_no': page_no,
                'terrain': terrain,
            })
            i += 3
        else:
            i += 1

    return records

print("Steg 1: Parsar PDF...", flush=True)
records = parse_pdf(PDF_PATH)
print(f"  Parsade {len(records)} poster (forväntat 18122)", flush=True)

if len(records) != TOTAL_RECORDS:
    rec_nos = [r['rec_no'] for r in records]
    dups = [n for n, c in Counter(rec_nos).items() if c > 1]
    print(f"  Duplikat-rec_no: {dups[:10]}", flush=True)
    print(f"  FEL: Got {len(records)}, expected {TOTAL_RECORDS}", flush=True)
    # Fortsätt ändå med vad vi har

print(f"  Post 0: rec_no={records[0]['rec_no']}, summary='{records[0]['summary'][:50]}'", flush=True)
print(f"  Post 0: year={records[0]['year']}, strange={records[0]['strange']}, cred={records[0]['cred']}", flush=True)

# -------------------------------------------------------------------
# 2. Läs U.RND binärdata
# -------------------------------------------------------------------
print("\nSteg 2: Läser U.RND...", flush=True)
rnd_data = RND_PATH.read_bytes()
assert len(rnd_data) == 2029786, f"Fel filstorlek: {len(rnd_data)}"
assert (len(rnd_data) - HEADER_SIZE) % RECORD_SIZE == 0
n = (len(rnd_data) - HEADER_SIZE) // RECORD_SIZE
assert n == TOTAL_RECORDS, f"Fel antal poster: {n}"
print(f"  OK: {n} poster x {RECORD_SIZE} byte", flush=True)

def get_record(i):
    offset = HEADER_SIZE + i * RECORD_SIZE
    return rnd_data[offset:offset + RECORD_SIZE]

# -------------------------------------------------------------------
# 3. Verifiera summary-offset 31
# -------------------------------------------------------------------
print("\nSteg 3: Verifierar summary-offset 31...", flush=True)
mismatches = 0
for i in range(min(len(records), TOTAL_RECORDS)):
    raw = get_record(i)
    raw_summary = raw[31:109].decode('latin-1').rstrip('\x00').rstrip()
    pdf_summary = records[i]['summary'][:78].rstrip()
    if raw_summary != pdf_summary:
        mismatches += 1
        if mismatches <= 3:
            print(f"  Mismatch post {i}: bin='{raw_summary[:40]}' pdf='{pdf_summary[:40]}'", flush=True)

print(f"  Summary offset 31: {TOTAL_RECORDS - mismatches}/{TOTAL_RECORDS} matchar", flush=True)

# -------------------------------------------------------------------
# 4. Brute-force numeriska fält
# -------------------------------------------------------------------
print("\nSteg 4: Brute-force numeriska fält (offsets 0-30)...", flush=True)

n_rec = min(len(records), TOTAL_RECORDS)

def brute_force(field_name, pdf_vals, widths=(1, 2, 4), allow_signed=False, bcd=False):
    best = {'field': field_name, 'offset': -1, 'width': 0, 'match': 0, 'score': 0.0, 'pct': 0.0}
    for off in range(31):
        for w in widths:
            if off + w > 31:
                continue
            for little_end in ([True, False] if w > 1 else [True]):
                for is_signed in ([True, False] if allow_signed else [False]):
                    matches = 0
                    for i in range(n_rec):
                        raw = get_record(i)
                        b = raw[off:off + w]
                        if bcd and w == 2:
                            val = (b[0] >> 4)*1000 + (b[0] & 0xF)*100 + (b[1] >> 4)*10 + (b[1] & 0xF)
                        else:
                            val = int.from_bytes(b, 'little' if little_end else 'big', signed=is_signed)
                        if val == pdf_vals[i]:
                            matches += 1
                    score = matches / n_rec
                    if score > best['score']:
                        best = {
                            'field': field_name, 'offset': off, 'width': w,
                            'little_endian': little_end, 'signed': is_signed,
                            'bcd': bcd, 'match': matches, 'score': score,
                            'pct': round(score * 100, 2)
                        }
    return best

fields_to_solve = [
    ('year',      [r['year']     for r in records], (2, 4), True),
    ('month',     [r['month']    for r in records], (1,),   False),
    ('day',       [r['day']      for r in records], (1,),   False),
    ('hour',      [r['hour']     for r in records], (1,),   False),
    ('minute',    [r['minute']   for r in records], (1,),   False),
    ('duration',  [r['duration'] for r in records], (2, 4), False),
    ('lon_d',     [r['lon_d']    for r in records], (1, 2), False),
    ('lon_m',     [r['lon_m']    for r in records], (1,),   False),
    ('lon_s',     [r['lon_s']    for r in records], (1,),   False),
    ('lat_d',     [r['lat_d']    for r in records], (1, 2), False),
    ('lat_m',     [r['lat_m']    for r in records], (1,),   False),
    ('lat_s',     [r['lat_s']    for r in records], (1,),   False),
    ('ref_no',    [r['ref_no']   for r in records], (1, 2), False),
    ('page_no',   [r['page_no']  for r in records], (1, 2), False),
    ('strange',   [r['strange']  for r in records], (1,),   False),
    ('cred',      [r['cred']     for r in records], (1,),   False),
]

results = {}
for fname, vals, widths, allow_signed in fields_to_solve:
    res = brute_force(fname, vals, widths=widths, allow_signed=allow_signed)
    results[fname] = res
    le = 'LE' if res.get('little_endian') else 'BE'
    print(f"  {fname:12s}: off={res['offset']:2d}, w={res['width']}, {le}, "
          f"signed={res.get('signed',False)}, {res['match']}/{n_rec} ({res['pct']}%)", flush=True)

# -------------------------------------------------------------------
# 5. ASCII-koder (kontinent, land, terräng-ish)
# -------------------------------------------------------------------
print("\nSteg 5: ASCII-koder (kontinent, land)...", flush=True)

def find_ascii3_offset(field_vals, max_off=28, sample=2000):
    votes = Counter()
    for i in range(min(sample, n_rec)):
        raw = get_record(i)
        target = field_vals[i]
        for off in range(max_off + 1):
            chunk = raw[off:off+3]
            try:
                s = chunk.decode('ascii')
                if s == target:
                    votes[off] += 1
            except Exception:
                pass
    return votes

cont_votes = find_ascii3_offset([r['continent'] for r in records])
ctry_votes = find_ascii3_offset([r['country'] for r in records])
print(f"  Kontinent top-5: {cont_votes.most_common(5)}", flush=True)
print(f"  Land top-5: {ctry_votes.most_common(5)}", flush=True)

def verify_ascii3(offset, field_vals):
    matches = sum(
        1 for i in range(n_rec)
        if get_record(i)[offset:offset+3].decode('latin-1') == field_vals[i]
    )
    return matches

if cont_votes:
    best_off = cont_votes.most_common(1)[0][0]
    m = verify_ascii3(best_off, [r['continent'] for r in records])
    print(f"  Kontinent offset {best_off}: {m}/{n_rec} ({m/n_rec*100:.1f}%)", flush=True)
    results['continent'] = {'field': 'continent', 'offset': best_off, 'width': 3,
                            'type': 'ascii3', 'match': m, 'score': m/n_rec, 'pct': round(m/n_rec*100, 2)}

if ctry_votes:
    best_off = ctry_votes.most_common(1)[0][0]
    m = verify_ascii3(best_off, [r['country'] for r in records])
    print(f"  Land offset {best_off}: {m}/{n_rec} ({m/n_rec*100:.1f}%)", flush=True)
    results['country'] = {'field': 'country', 'offset': best_off, 'width': 3,
                          'type': 'ascii3', 'match': m, 'score': m/n_rec, 'pct': round(m/n_rec*100, 2)}

# -------------------------------------------------------------------
# 6. Precisionskod (4 ASCII-siffror)
# -------------------------------------------------------------------
print("\nSteg 6: Precisionskod (4 ASCII-siffror)...", flush=True)
prec_vals = [r['prec'] for r in records]
prec_votes = Counter()
for i in range(min(2000, n_rec)):
    raw = get_record(i)
    target = prec_vals[i]
    for off in range(28):
        chunk = raw[off:off+4]
        try:
            s = chunk.decode('ascii')
            if re.match(r'^[0-3]{4}$', s) and s == target:
                prec_votes[off] += 1
        except Exception:
            pass

print(f"  Prec top-5: {prec_votes.most_common(5)}", flush=True)
if prec_votes:
    best_off = prec_votes.most_common(1)[0][0]
    m = sum(
        1 for i in range(n_rec)
        if get_record(i)[best_off:best_off+4].decode('ascii', errors='replace') == prec_vals[i]
    )
    print(f"  Prec offset {best_off}: {m}/{n_rec} ({m/n_rec*100:.1f}%)", flush=True)
    results['prec'] = {'field': 'prec', 'offset': best_off, 'width': 4,
                       'type': 'ascii4', 'match': m, 'score': m/n_rec, 'pct': round(m/n_rec*100, 2)}

# -------------------------------------------------------------------
# 7. Riktningsbitar (lon_dir, lat_dir) — troligen bitar i ett byte
# -------------------------------------------------------------------
print("\nSteg 7: Riktningskoder (EWZ, NSQ)...", flush=True)

# Alternativt: de kan vara ASCII-bytes på ett ställe
def find_char_offset(field_vals, max_off=30):
    votes = Counter()
    for i in range(min(2000, n_rec)):
        raw = get_record(i)
        target_byte = ord(field_vals[i])
        for off in range(max_off + 1):
            if raw[off] == target_byte:
                votes[off] += 1
    return votes

lon_dir_votes = find_char_offset([r['lon_dir'] for r in records])
lat_dir_votes = find_char_offset([r['lat_dir'] for r in records])

# Men E/W/N/S kan vara vanliga ASCII-bytes överallt — filtrera på koherens
# Bättre: räkna exakt match
def verify_char_offset(offset, field_vals):
    matches = sum(
        1 for i in range(n_rec)
        if get_record(i)[offset] == ord(field_vals[i])
    )
    return matches

print("  Testar lon_dir-kandidater (top-5):", flush=True)
for off, cnt in lon_dir_votes.most_common(10):
    m = verify_char_offset(off, [r['lon_dir'] for r in records])
    if m > n_rec * 0.5:
        print(f"    offset {off}: sample={cnt}, full={m}/{n_rec} ({m/n_rec*100:.1f}%)", flush=True)

print("  Testar lat_dir-kandidater (top-5):", flush=True)
for off, cnt in lat_dir_votes.most_common(10):
    m = verify_char_offset(off, [r['lat_dir'] for r in records])
    if m > n_rec * 0.5:
        print(f"    offset {off}: sample={cnt}, full={m}/{n_rec} ({m/n_rec*100:.1f}%)", flush=True)

# -------------------------------------------------------------------
# 8. Hex-dump för post 0 och analys av kartlagda bytes
# -------------------------------------------------------------------
print("\nSteg 8: Hex-dump och analys...", flush=True)
raw0 = get_record(0)
print(f"  Post 0 hex bytes 0-30: {raw0[:31].hex()}", flush=True)
print(f"  Post 0 bytes 0-30: {list(raw0[:31])}", flush=True)
print(f"  Post 0 hex bytes 109-111: {raw0[109:112].hex()}", flush=True)
print(f"  Post 0 bytes 109-111: {list(raw0[109:112])}", flush=True)

# Vilka offsetar är kartlagda?
cartlagd = set()
for fname, res in results.items():
    if res and 'offset' in res:
        for b in range(res['offset'], res['offset'] + res.get('width', 1)):
            cartlagd.add(b)

print(f"\n  Kartlagda positioner: {sorted(b for b in cartlagd if b < 31)}", flush=True)
print(f"  Okartlagda (0-30): {sorted(b for b in range(31) if b not in cartlagd)}", flush=True)

# -------------------------------------------------------------------
# 9. Spara resultat
# -------------------------------------------------------------------
output_json = DOCS_DIR / 'urnd_offsets_raw.json'
with open(output_json, 'w') as f:
    json.dump(results, f, indent=2, default=str)

# Spara ground-truth-poster (sample + stats)
gt_summary = {
    'total_parsed': len(records),
    'expected': TOTAL_RECORDS,
    'sample_first': records[0],
    'sample_last': records[-1],
    'unique_continents': sorted(set(r['continent'] for r in records)),
    'unique_countries': len(set(r['country'] for r in records)),
    'year_range': [min(r['year'] for r in records), max(r['year'] for r in records)],
    'deleted_records': sum(1 for r in records if r['year'] == 3000),
}
with open(DOCS_DIR / 'ground_truth_stats.json', 'w') as f:
    json.dump(gt_summary, f, indent=2, default=str)

print(f"\nResultat sparade i {DOCS_DIR}", flush=True)
print("\n=== FAS 1 KLAR ===", flush=True)
