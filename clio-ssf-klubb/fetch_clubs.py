"""
fetch_clubs.py — Hämtar alla klubbar för ett distrikt från skidor.com API.

Sparar resultat till clubs.json med fälten:
  klubbid, klubbnamn, klubb_epost, klubb_url, klubbaddress

Använd distriktsnamn 'Alla' för att hämta alla 1 214 klubbar (13 sidor).
"""

import requests
import json
import time
import sys
from pathlib import Path

BASE       = 'https://varmland.skidor.com'
PAGE_ID    = '106.7756e3f1866cb6688ddfef1'
PORTLET_ID = '12.2543d89518e56b1f3e21c10d'
API        = f'{BASE}/appresource/{PAGE_ID}/{PORTLET_ID}'

DISTRICTS = {
    'Värmland': '0C7897C7-7E72-4978-B4BF-10815F0F9751',
    'Alla':     '',
}

FREE_DOMAINS = {
    'gmail.com','hotmail.com','hotmail.se','yahoo.com','yahoo.se',
    'live.com','live.se','outlook.com','outlook.se','telia.com',
    'tele2.se','comhem.se','bredband.net','spray.se','home.se',
    'swipnet.se','msn.com','icloud.com','me.com','mac.com',
    'student.','glocalnet.net','tiscali.se','passagen.se',
}


def _session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (clio-ssf-klubb/1.0)',
        'Referer': BASE + '/distrikt/varmland/kontakta-oss-klubbar/hitta-klubb',
    })
    s.get(BASE + '/distrikt/varmland/kontakta-oss-klubbar/hitta-klubb', timeout=10)
    return s


def _free_domain(email: str) -> bool:
    if not email or '@' not in email:
        return True
    domain = email.split('@')[1].lower().strip()
    return any(domain == d or domain.endswith('.' + d) for d in FREE_DOMAINS)


def _fetch_all_pages(s, district_id):
    Hämtar alla sidor och returnerar råa organisations-listor.
    r = s.get(f'{API}/search', params={
        'query': '', 'districtId': district_id,
        'municipality': '', 'subSport': '', 'page': '0'
    }, timeout=15)
    r.raise_for_status()
    data        = r.json()['organisations']
    total_pages = data['totalPages']
    total       = data['totalElements']
    clubs_raw   = list(data['organisations'])
    print(f'Totalt {total} klubbar ({total_pages} sidor)')

    for page in range(1, total_pages):
        r = s.get(f'{API}/search', params={
            'query': '', 'districtId': district_id,
            'municipality': '', 'subSport': '', 'page': str(page)
        }, timeout=15)
        r.raise_for_status()
        clubs_raw.extend(r.json()['organisations']['organisations'])
        print(f'  Sida {page + 1}/{total_pages}: {len(clubs_raw)} hämtade')
        time.sleep(0.2)

    return clubs_raw


def fetch_clubs(district: str = 'Värmland', output: str = None) -> list[dict]:
    district_id = DISTRICTS.get(district, district)
    s = _session()

    print(f'Hämtar klubbar för distrikt: {district}...')
    clubs_raw = _fetch_all_pages(s, district_id)
    total = len(clubs_raw)
    print(f'Hämtar detaljer för {total} klubbar...')

    clubs = []
    for i, c in enumerate(clubs_raw, 1):
        try:
            det_r = s.get(f'{API}/organisation', params={'organisationId': c['id']}, timeout=10)
            det = det_r.json().get('organisation', {})

            contacts = det.get('contactDetails', [])
            email    = next((x['value'] for x in contacts if x.get('type') == 'EMAIL'), '')
            homepage = next((x['value'] for x in contacts if x.get('type') == 'HOMEPAGE'), '')

            addrs = det.get('addresses', [])
            addr  = next((a for a in addrs if a.get('type') == 'POSTAL'), addrs[0] if addrs else {})

            if homepage and not homepage.startswith('http'):
                homepage = 'https://' + homepage

            domain = None
            if homepage:
                from urllib.parse import urlparse
                domain = urlparse(homepage).netloc or homepage
            elif email and not _free_domain(email):
                domain = email.split('@')[1]
                homepage = f'https://{domain}'

            club = {
                'klubbid':        det.get('rfNumber', ''),
                'klubbnamn':      det.get('name', c.get('name', '')),
                'klubb_epost':    email,
                'klubb_url':      homepage,
                'klubb_domain':   domain,
                'has_own_domain': bool(domain and not _free_domain(email)),
                'klubbaddress': {
                    'gata':   addr.get('streetAddress', ''),
                    'postnr': addr.get('postalCode', ''),
                    'ort':    addr.get('postalPlace', ''),
                    'land':   addr.get('country', 'Sverige'),
                },
                'distrikt': det.get('districtName', district),
                '_id': c['id'],
            }
            clubs.append(club)

            if i % 50 == 0:
                print(f'  {i}/{total}...')
            time.sleep(0.1)

        except Exception as e:
            print(f'  FEL för {c.get("name")}: {e}')
            clubs.append({'klubbid': '', 'klubbnamn': c.get('name', ''), 'klubb_epost': '',
                          'klubb_url': '', 'klubb_domain': None, 'has_own_domain': False,
                          'klubbaddress': {}, 'distrikt': district, '_id': c['id']})

    with_domain = sum(1 for c in clubs if c['has_own_domain'])
    print(f'\nKlart: {total} klubbar, {with_domain} med egen domän')

    if output:
        Path(output).write_text(json.dumps(clubs, indent=2, ensure_ascii=False))
        print(f'Sparat till {output}')

    return clubs


if __name__ == '__main__':
    district = sys.argv[1] if len(sys.argv) > 1 else 'Värmland'
    output   = sys.argv[2] if len(sys.argv) > 2 else 'clubs.json'
    fetch_clubs(district, output)
