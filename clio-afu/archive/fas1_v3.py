#!/usr/bin/env python3
"""
Fas 1 v3: Fixad geo-regex (3 koder), riktad brute-force på bytes 0-20 + 99-111.
"""
import re, json, struct
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
SUMMARY_OFFSET = 21
SUMMARY_END = 99

# Fixad regex: fångar 3 geo-koder (continent country state), state optional
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
print(f"  {len(records)} poster (förväntat 18122)", flush=True)

# Verifiera: kolla att geo-fälten ser rimliga ut
print(f"  Post 0: cont={records[0]['continent']}, ctry={records[0]['country']}, state={records[0]['state']}", flush=True)
print(f"  Unika kontinenter: {sorted(set(r['continent'] for r in records))}", flush=True)

rnd_data = RND_PATH.read_bytes()
def get_record(i): return rnd_data[HEADER_SIZE + i*RECORD_SIZE : HEADER_SIZE + (i+1)*RECORD_SIZE]

N = TOTAL_RECORDS

# -------------------------------------------------------------------
# A. Verifiera summary-offset med whitespace-tolerant jämförelse
# -------------------------------------------------------------------
n_parsed = len(records)
ok = 0
for i in range(n_parsed):
    raw = get_record(i)
    b = raw[SUMMARY_OFFSET:SUMMARY_END].decode('latin-1').strip()
    p = records[i]['summary'].strip()[:78]
    if b == p: ok += 1
print(f"\nSummary offset 21 (strip): {ok}/{n_parsed} ({ok/n_parsed*100:.1f}%)", flush=True)
N = n_parsed  # Använd parsade poster för resten

# -------------------------------------------------------------------
# B. Verifiera geo-koder i bytes 0-20
# -------------------------------------------------------------------
print("\n=== GEO-KODER I BYTES 0-20 ===", flush=True)
for fname, fvals in [('state', [r['state'] for r in records]),
                     ('country', [r['country'] for r in records]),
                     ('continent', [r['continent'] for r in records])]:
    votes = Counter()
    for i in range(min(2000, N)):
        raw = get_record(i)
        t = fvals[i]
        for off in range(19):
            try:
                if raw[off:off+3].decode('ascii') == t:
                    votes[off] += 1
            except: pass
    best_off, best_cnt = votes.most_common(1)[0] if votes else (-1, 0)
    if best_off >= 0:
        m = sum(1 for i in range(N) if get_record(i)[best_off:best_off+3].decode('latin-1') == fvals[i])
        print(f"  {fname:10s}: off={best_off}, sample={best_cnt}/2000, full={m}/{N} ({m/N*100:.1f}%)", flush=True)
    else:
        # Kolla post-summary bytes
        for off in range(99, 109):
            try:
                votes2 = Counter()
                for i in range(min(2000, N)):
                    raw = get_record(i)
                    if raw[off:off+3].decode('ascii', errors='replace') == fvals[i]:
                        votes2[off] += 1
                if votes2:
                    bo, bc = votes2.most_common(1)[0]
                    m = sum(1 for i in range(N) if get_record(i)[bo:bo+3].decode('latin-1') == fvals[i])
                    print(f"  {fname:10s}: off={bo} (POST), sample={bc}/2000, full={m}/{N} ({m/N*100:.1f}%)", flush=True)
                    break
            except: pass

# -------------------------------------------------------------------
# C. Brute-force med korrekt offsets, fler kodningar
# -------------------------------------------------------------------
print("\n=== BRUTE FORCE (offsets 0-20 + 99-111) ===", flush=True)

def brute_v3(fname, vals, allow_signed=False):
    best = {'offset': -1, 'match': 0, 'score': 0.0, 'pct': 0.0, 'enc': ''}
    # Byte-widths 1, 2, 4 i pre (0-20) och post (99-111)
    ranges = [(o, o+1, 'pre') for o in range(21)] + [(o, o+1, 'post') for o in range(99, 112)]
    for w in [1, 2, 4]:
        for start, _, region in ranges:
            end = start + w
            if region == 'pre' and end > 21: continue
            if region == 'post' and end > 112: continue
            for le in ([True, False] if w > 1 else [True]):
                for sg in ([True, False] if allow_signed else [False]):
                    matches = sum(
                        1 for i in range(N)
                        if int.from_bytes(get_record(i)[start:end],
                                          'little' if le else 'big', signed=sg) == vals[i]
                    )
                    if matches > best['match']:
                        best = {'offset': start, 'width': w, 'le': le, 'signed': sg,
                                'match': matches, 'score': matches/N, 'pct': round(matches/N*100,2),
                                'enc': f"int{w*8}{'s' if sg else 'u'}_{'LE' if le else 'BE'}"}
    return best

fields = [
    ('year',     [r['year'] for r in records],     True),
    ('month',    [r['month'] for r in records],    False),
    ('day',      [r['day'] for r in records],      False),
    ('hour',     [r['hour'] for r in records],     False),
    ('minute',   [r['minute'] for r in records],   False),
    ('duration', [r['duration'] for r in records], False),
    ('lon_d',    [r['lon_d'] for r in records],    False),
    ('lon_m',    [r['lon_m'] for r in records],    False),
    ('lon_s',    [r['lon_s'] for r in records],    False),
    ('lat_d',    [r['lat_d'] for r in records],    False),
    ('lat_m',    [r['lat_m'] for r in records],    False),
    ('lat_s',    [r['lat_s'] for r in records],    False),
    ('ref_no',   [r['ref_no'] for r in records],   False),
    ('page_no',  [r['page_no'] for r in records],  False),
    ('strange',  [r['strange'] for r in records],  False),
    ('cred',     [r['cred'] for r in records],     False),
]

results = {}
for fname, vals, sg in fields:
    res = brute_v3(fname, vals, allow_signed=sg)
    results[fname] = res
    print(f"  {fname:10s}: off={res['offset']:3d} {res['enc']:20s} {res['match']}/{N} ({res['pct']}%)", flush=True)

# -------------------------------------------------------------------
# D. Handanalyse av post 0-9: matcha kända värden mot bytes
# -------------------------------------------------------------------
print("\n=== HANDANALYSE POST 0-9 ===", flush=True)
print("Bytes 0-20 (pre-summary):", flush=True)
for i in range(10):
    raw = get_record(i)
    r = records[i]
    pre = list(raw[:21])
    print(f"  Post{i:3d}: yr={r['year']:6d} mo={r['month']:2d} dy={r['day']:2d} "
          f"h={r['hour']:2d} m={r['minute']:2d} dur={r['duration']:5d} "
          f"lon={r['lon_d']}:{r['lon_m']}:{r['lon_s']}{r['lon_dir']} "
          f"lat={r['lat_d']}:{r['lat_m']}:{r['lat_s']}{r['lat_dir']} "
          f"cont={r['continent']} ctry={r['country']} state={r['state']}",
          flush=True)
    print(f"           PRE hex: {bytes(pre).hex()}", flush=True)

# -------------------------------------------------------------------
# E. Kolla om packed bitfields ger bättre match för datum/tid
# -------------------------------------------------------------------
print("\n=== PACKED DATE EXPERIMENT ===", flush=True)
# Hypotes: år(12 bits med offset)+ månad(4) + dag(5) + timme(5) + minut(3) = 29 bits
# Prova: bytes 0-3 eller 0-4 innehåller packad datum+tid

# Extrahera och jämför mot kanda värden för post 0
print("Post 0 bytes 0-3:", list(get_record(0)[:4]), flush=True)
print(f"  Känt: år={records[0]['year']}, mån={records[0]['month']}, dag={records[0]['day']}, "
      f"h={records[0]['hour']}, min={records[0]['minute']}", flush=True)

# Prova IEEE float för år: -593.0
raw0 = get_record(0)
for off in range(18):
    b = raw0[off:off+4]
    if len(b) == 4:
        f = struct.unpack('<f', b)[0]
        if abs(f - records[0]['year']) < 1.0:
            print(f"  FLOAT LE off={off}: {f} ≈ {records[0]['year']} ✓", flush=True)
    b = raw0[off:off+4]
    if len(b) == 4:
        f = struct.unpack('>f', b)[0]
        if abs(f - records[0]['year']) < 1.0:
            print(f"  FLOAT BE off={off}: {f} ≈ {records[0]['year']} ✓", flush=True)

# Prova year+500 offset (för att hantera negativa)
for off in range(19):
    for w in [2]:
        b = get_record(0)[off:off+w]
        v_le = int.from_bytes(b, 'little', signed=False)
        v_be = int.from_bytes(b, 'big', signed=False)
        # Kolla om v - 500 ≈ -593 → v ≈ -93 → nej
        # Kolla om v med biased encoding: v - 32768 ≈ -593 → v ≈ 32175
        for bias in [0, 100, 500, 1000, 2000, 32768]:
            target = records[0]['year'] + bias
            if v_le == target or v_be == target:
                print(f"  Year+{bias} off={off} w={w}: LE={v_le}, BE={v_be} → target={target} ✓", flush=True)

# -------------------------------------------------------------------
# F. Attributes: leta efter 8-byte block som korrelerar med keywords
# -------------------------------------------------------------------
print("\n=== ATTRIBUT SÖKNING (8-byte block) ===", flush=True)
# Post 0 summary: "CHALDEA:EZEKIEL:FIERY SPHERE LANDS/4 SUPPORTS:TAKEN FOR A RIDE"
# Förväntade attribut: LND (landing), ABD (taken for a ride), SCR (sphere), HST (historical)
# LND = rad 6, kol 8 (sista i rad 6)
# ABD = rad 5, kol 5
# SCR = rad 3, kol 1

# Samla poster med kända nyckelord och sök correlation med bytes i 0-20 + 99-111
lnd_set = set(i for i, r in enumerate(records) if 'LAND' in r['summary'] or ' LND' in r['summary'])
abd_set = set(i for i, r in enumerate(records) if 'ABDUCT' in r['summary'] or 'TAKEN' in r['summary'])
noc_set = set(i for i, r in enumerate(records) if ' NOC' in r['summary'] or 'NO ENTITY' in r['summary'])

print(f"  LND-kandidater: {len(lnd_set)}", flush=True)
print(f"  ABD-kandidater: {len(abd_set)}", flush=True)

# Sök 8-byte block i 0-20 + 99-111 som har hög bitkorrelation
# Prova systematisk: för varje möjligt startoffset för 8-byte block
for start in list(range(0, 14)) + list(range(99, 105)):
    end = start + 8
    if start < 21 and end > 21: continue
    if start >= 99 and end > 112: continue

    # Korrelera bit 0 (byte 0 bit 0) med lnd_set
    lnd_match = 0
    for i in range(N):
        raw = get_record(i)
        byte_block = raw[start:end]
        # Om LND är bit (rad=5, kol=7) i 8x8 matris = byte 5, bit 7
        # Vi vet inte ordningen ännu - testa alla 64 bitar
        pass

    # Enklare: kolla om något byte i blocket korrelerar med 'LAND' i summary
    for byte_in_block in range(8):
        byte_off = start + byte_in_block
        for bit in range(8):
            count_11 = 0  # both set
            count_00 = 0  # both clear
            for i in lnd_set:
                raw = get_record(i)
                if raw[byte_off] & (1 << bit): count_11 += 1
            for i in range(N):
                if i not in lnd_set:
                    raw = get_record(i)
                    if not (raw[byte_off] & (1 << bit)): count_00 += 1
            phi = (count_11 + count_00) / N
            if phi > 0.85:
                print(f"  LND corr: off={byte_off}, bit={bit}, phi={phi:.3f} "
                      f"({count_11}/{len(lnd_set)} LND set)", flush=True)

# Spara
with open(DOCS_DIR / 'urnd_offsets_v3.json', 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nSparat till {DOCS_DIR}/urnd_offsets_v3.json", flush=True)
