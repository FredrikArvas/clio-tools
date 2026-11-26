#!/usr/bin/env python3
"""
Importerar Larry Hatch U* database (U.RND) → Odoo 19 (uap-databas).
Använder PDF som primär källa, binary för strangeness/credibility/state.
"""
import os
import re
import sys
import hashlib
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')
load_dotenv(Path(__file__).parent / '.env')

BASE = Path(os.getenv('AFU_BASE', '/home/clioadmin/19.0/clio-tools/clio-afu'))
PDF_PATH = BASE / 'data/downloads/Databases/Larry Hatch/derivations/Larry Hatch - full text.pdf'
RND_PATH = BASE / 'data/downloads/Databases/Larry Hatch/original/U.RND'

DB_NAME = os.getenv('DB_NAME', 'uap')
DB_USER = os.getenv('DB_USER', 'odoo')
DB_HOST = os.getenv('DB_HOST', '172.19.0.2')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_PASS = os.environ['DB_PASS']

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
                if rm:
                    ref_no = int(rm.group(1))
                    page_no = int(rm.group(2))
                    terrain = rm.group(3).strip()
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
                'state_code': m.group(18) if m.group(18) else '---',
                'strange': int(sc.group(1), 16) if sc else -1,
                'cred': int(sc.group(2), 16) if sc else -1,
                'summary': summary, 'ref_no': ref_no, 'page_no': page_no, 'terrain': terrain,
            })
            i += 3
        else:
            i += 1
    return records


def dms_to_float(d, m, s, direction):
    v = d + m / 60.0 + s / 3600.0
    if direction in ('S', 'W'):
        v = -v
    return v


def make_hash(r):
    key = f"{r['year']}|{r['lat_d']}:{r['lat_m']}:{r['lat_s']}:{r['lat_dir']}|{r['lon_d']}:{r['lon_m']}:{r['lon_s']}:{r['lon_dir']}|{r['summary'][:30]}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def main():
    print("Parsar PDF...", flush=True)
    records = parse_pdf(PDF_PATH)
    N = len(records)
    print(f"  {N} poster parsade", flush=True)

    rnd_data = RND_PATH.read_bytes()
    def get_record(i):
        return rnd_data[HEADER_SIZE + i * RECORD_SIZE: HEADER_SIZE + (i + 1) * RECORD_SIZE]

    # Komplettera state från binär (mer pålitlig)
    for i, r in enumerate(records):
        raw = get_record(i)
        try:
            bin_state = raw[9:12].decode('ascii').rstrip('\x00').strip()
            if bin_state and bin_state != '---':
                r['state_code'] = bin_state
        except:
            pass
        # Komplettera s/c från binär om saknas i PDF
        if r['strange'] < 0 or r['cred'] < 0:
            sc_byte = raw[101]
            r['strange'] = (sc_byte >> 4) & 0xF
            r['cred'] = sc_byte & 0xF

    print("Ansluter till databas...", flush=True)
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT, password=DB_PASS)
    cur = conn.cursor()

    # Hitta modell-ID
    cur.execute("SELECT id FROM ir_model WHERE model = 'afu.larry_hatch.case'")
    row = cur.fetchone()
    if not row:
        print("ERROR: Modellen afu.larry_hatch.case finns inte. Installera modulen först!", file=sys.stderr)
        sys.exit(1)

    cur.execute("SELECT COUNT(*) FROM afu_larry_hatch_case")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"  {existing} poster finns redan. Avbryter (kör med --force för att rensa).", flush=True)
        if '--force' not in sys.argv:
            conn.close()
            return
        cur.execute("TRUNCATE TABLE afu_larry_hatch_case RESTART IDENTITY CASCADE")
        conn.commit()
        print("  Tabellen rensad.", flush=True)

    print(f"Importerar {N} poster...", flush=True)

    batch = []
    for i, r in enumerate(records):
        lat_f = dms_to_float(r['lat_d'], r['lat_m'], r['lat_s'], r['lat_dir'])
        lon_f = dms_to_float(r['lon_d'], r['lon_m'], r['lon_s'], r['lon_dir'])
        is_deleted = r['year'] == 3000
        chash = make_hash(r)

        batch.append((
            chash,
            r['year'], r['month'], r['day'],
            r['hour'], r['minute'], r['duration'],
            lat_f, r['lat_dir'],
            lon_f, r['lon_dir'],
            r['prec'],
            r['continent'], r['country'], r['state_code'],
            r['strange'], r['cred'],
            r['ref_no'], r['page_no'], r['terrain'],
            r['summary'],
            i,
            is_deleted,
        ))

        if len(batch) >= 500 or i == N - 1:
            cur.executemany("""
                INSERT INTO afu_larry_hatch_case
                  (content_hash,
                   year_val, month_val, day_val, hour_val, minute_val, duration,
                   lat_deg, lat_dir, lon_deg, lon_dir, prec,
                   continent, country, state_code,
                   strangeness, credibility, ref_no, page_no, terrain,
                   summary, rnd_index, is_deleted,
                   display_name)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                  left(%s || ': ' || %s, 100))
            """, [b + (str(b[1]), b[20][:40]) for b in batch])
            conn.commit()
            batch = []
            if i % 2000 == 0:
                print(f"  {i+1}/{N}...", flush=True)

    cur.execute("SELECT COUNT(*) FROM afu_larry_hatch_case")
    final = cur.fetchone()[0]
    print(f"\nKLAR: {final} poster importerade till 'uap'-databasen.", flush=True)
    conn.close()


if __name__ == '__main__':
    main()
