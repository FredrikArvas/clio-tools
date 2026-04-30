"""
update_refs_ssf.py — Byter ref från UUID till rfNumber för alla klubbar i ssf.

Hämtar alla 1 214 klubbar, bygger UUID->rfNumber-mappning, uppdaterar ssf.
Progress sparas till uuid_map.json — avbruten körning återupptas automatiskt.

Burst-mönster: 5 anrop → 5 s, 5 anrop → 10 s, 5 anrop → 5 s, ...
"""
import requests, time, json, sys
from pathlib import Path
from itertools import cycle

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clio_odoo import connect

BASE       = 'https://varmland.skidor.com'
PAGE_ID    = '106.7756e3f1866cb6688ddfef1'
PORTLET_ID = '12.2543d89518e56b1f3e21c10d'
API        = f'{BASE}/appresource/{PAGE_ID}/{PORTLET_ID}'
SSF_DB     = 'ssf'
PROGRESS   = Path(__file__).parent / 'uuid_map.json'

BURST      = 5           # antal anrop per burst
PAUSES     = cycle([5, 10])   # alternerande pauser i sekunder
PAGE_DELAY = 2.0


def _session():
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0 (clio-ssf-klubb/1.0)',
                      'Referer': BASE + '/distrikt/varmland/kontakta-oss-klubbar/hitta-klubb'})
    s.get(BASE + '/distrikt/varmland/kontakta-oss-klubbar/hitta-klubb', timeout=10)
    return s


def _get(session, url, params, retries=4):
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 429 or r.status_code >= 500:
                wait = 2 ** (attempt + 3)   # 8, 16, 32, 64 s
                print(f'  HTTP {r.status_code} — väntar {wait}s (försök {attempt+1}/{retries})')
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            wait = 2 ** (attempt + 3)
            print(f'  Nätverksfel: {e} — väntar {wait}s')
            time.sleep(wait)
    raise RuntimeError(f'Misslyckades efter {retries} försök')


def fetch_all_raw(session):
    r = _get(session, f'{API}/search',
             {'query': '', 'districtId': '', 'municipality': '', 'subSport': '', 'page': '0'})
    data        = r.json()['organisations']
    total_pages = data['totalPages']
    total       = data['totalElements']
    clubs_raw   = list(data['organisations'])
    print(f'Totalt {total} klubbar över {total_pages} sidor')

    for page in range(1, total_pages):
        time.sleep(PAGE_DELAY)
        r = _get(session, f'{API}/search',
                 {'query': '', 'districtId': '', 'municipality': '', 'subSport': '', 'page': str(page)})
        clubs_raw.extend(r.json()['organisations']['organisations'])
        print(f'  Sida {page + 1}/{total_pages}: {len(clubs_raw)} hämtade')

    return clubs_raw


def build_mapping(clubs_raw, session, existing=None):
    mapping   = dict(existing or {})
    already   = len(mapping)
    if already:
        print(f'  Återupptar: {already} redan mappade')

    to_do     = [c for c in clubs_raw if c['id'] not in mapping]
    total     = len(clubs_raw)
    done      = already
    no_rf     = 0
    pauses    = cycle([5, 10])
    burst_count = 0

    for c in to_do:
        uuid = c['id']
        try:
            r   = _get(session, f'{API}/organisation', {'organisationId': uuid})
            det = r.json().get('organisation', {})
            rf  = det.get('rfNumber', '')
            if rf:
                mapping[uuid] = rf
            else:
                no_rf += 1
            done        += 1
            burst_count += 1

            if burst_count >= BURST:
                pause = next(pauses)
                PROGRESS.write_text(json.dumps(mapping, ensure_ascii=False))
                print(f'  {done}/{total} — {len(mapping)} rfNumber — paus {pause}s (sparat)')
                time.sleep(pause)
                burst_count = 0

        except Exception as e:
            print(f'  FEL {c.get("name")}: {e} — fortsätter')

    PROGRESS.write_text(json.dumps(mapping, ensure_ascii=False))
    print(f'Mappning klar: {len(mapping)} med rfNumber, {no_rf} utan')
    return mapping


def update_ssf_refs(mapping):
    print(f'\nAnsluter till Odoo {SSF_DB}...')
    env     = connect(db=SSF_DB)
    Partner = env['res.partner']
    updated = 0
    missing = 0
    for uuid, rfnumber in mapping.items():
        rows = Partner.search_read([('ref', '=', uuid), ('is_company', '=', True)], ['id'])
        if rows:
            Partner.write([rows[0]['id']], {'ref': rfnumber})
            updated += 1
            if updated % 200 == 0:
                print(f'  {updated} uppdaterade...')
        else:
            missing += 1
    print(f'Uppdaterade: {updated}  Ej hittade: {missing}')


if __name__ == '__main__':
    existing = {}
    if PROGRESS.exists():
        existing = json.loads(PROGRESS.read_text())
        print(f'Hittade progress-fil: {len(existing)} UUID mappade')

    session = _session()

    print('Steg 1: Hämtar klubblista...')
    clubs_raw = fetch_all_raw(session)

    bursts = (len(clubs_raw) - len(existing)) // BURST
    avg_pause = 7.5   # (5+10)/2
    est_min = bursts * avg_pause / 60
    print(f'\nSteg 2: Hämtar rfNumber — ~{est_min:.0f} min uppskattad tid...')
    mapping = build_mapping(clubs_raw, session, existing)

    print('\nSteg 3: Uppdaterar ssf-databasen...')
    update_ssf_refs(mapping)

    print('\nKlart!')
