"""
scrape_contacts.py — Besöker klubbars webbplatser och extraherar kontaktpersoner.
"""

import json, time, sys, re
from pathlib import Path
from urllib.parse import urljoin

import requests

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    import anthropic
    HAS_CLAUDE = True
except ImportError:
    HAS_CLAUDE = False

CONTACT_PATHS = [
    '/styrelse', '/om-oss/styrelse', '/kontakt', '/kontakta-oss',
    '/om-oss', '/om-klubben', '/foreningen', '/om-foreningen',
    '/organisation', '/',
]

ROLE_KEYWORDS = [
    'ordforande', 'ordförande', 'vice ordförande', 'sekreterare', 'kassör',
    'ledamot', 'suppleant', 'revisor', 'tränare', 'coach',
    'ungdomsledare', 'vd', 'kansli', 'kontaktperson',
    'sportchef', 'alpin', 'längd', 'skidchef',
]

CLAUDE_PROMPT = (
    "Du är ett verktyg för att extrahera kontaktpersoner ur text från en idrottsklubb.\n"
    "Extrahera ALLA personer med namn och roll som nämns i texten nedan.\n"
    "Returnera ENBART ett JSON-objekt:\n"
    '{"kontakter": [{"namn": "...", "roll": "...", "epost": "...", "telefon": "..."}]}\n'
    "Om ett fält saknas, sätt det till null.\n"
    "Roller ska vara på svenska (Ordförande, Sekreterare, Kassör, Ledamot, etc.).\n"
    "Inkludera BARA faktiska personer med namn.\n\nText:\n"
)


def _fetch_text(url, session):
    try:
        if HAS_TRAFILATURA:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(downloaded, include_links=False, include_tables=True)
                if text and len(text) > 100:
                    return text
        r = session.get(url, timeout=8)
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            return soup.get_text(' ', strip=True)[:5000]
    except Exception:
        return None
    return None


def _extract_with_claude(text):
    if not HAS_CLAUDE:
        return []
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1024,
            messages=[{'role': 'user', 'content': CLAUDE_PROMPT + text[:4000]}]
        )
        raw = msg.content[0].text.strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            return data.get('kontakter', [])
    except Exception as e:
        print(f'    Claude-fel: {e}')
    return []


def _extract_simple(text):
    kontakter = []
    lines = text.split('\n')
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for role in ROLE_KEYWORDS:
            if role in line_lower:
                name_match = re.search(r'([A-ZÅÄÖ][a-zåäö]+(?:\s+[A-ZÅÄÖ][a-zåäö]+)+)', line)
                if not name_match and i + 1 < len(lines):
                    name_match = re.search(r'([A-ZÅÄÖ][a-zåäö]+(?:\s+[A-ZÅÄÖ][a-zåäö]+)+)', lines[i+1])
                email_match = re.search(r'[\w.+-]+@[\w.-]+\.[a-z]{2,}', line)
                if name_match:
                    kontakter.append({
                        'namn': name_match.group(1).strip(),
                        'roll': role.title(),
                        'epost': email_match.group() if email_match else None,
                        'telefon': None,
                    })
                break
    return kontakter


def scrape_club(club, session):
    base_url = club.get('klubb_url', '')
    if not base_url:
        return []
    best_text = ''
    best_url = ''
    for path in CONTACT_PATHS:
        url = urljoin(base_url, path)
        text = _fetch_text(url, session)
        if text and len(text) > len(best_text):
            best_text = text
            best_url = url
            if 'styrelse' in path:
                break
    if not best_text:
        return []
    kontakter = _extract_with_claude(best_text) if HAS_CLAUDE else []
    if not kontakter:
        kontakter = _extract_simple(best_text)
    for k in kontakter:
        k['kalla_url'] = best_url
    return kontakter


def scrape_all(clubs_file='clubs.json', output='contacts.json'):
    clubs = json.loads(Path(clubs_file).read_text())
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (clio-ssf-klubb/1.0)'})
    with_url = [c for c in clubs if c.get('has_own_domain')]
    print(f'Scrapar {len(with_url)}/{len(clubs)} klubbar med egna webbplatser...')
    results = []
    for i, club in enumerate(with_url, 1):
        name = club['klubbnamn']
        url = club['klubb_url']
        print(f'  [{i}/{len(with_url)}] {name}: {url}')
        try:
            kontakter = scrape_club(club, session)
            print(f'    -> {len(kontakter)} person(er) hittade')
            results.append({'klubb': club, 'kontakter': kontakter})
        except Exception as e:
            print(f'    FEL: {e}')
            results.append({'klubb': club, 'kontakter': []})
        time.sleep(0.5)
    Path(output).write_text(json.dumps(results, indent=2, ensure_ascii=False))
    total_contacts = sum(len(r['kontakter']) for r in results)
    print(f'\nKlart: {total_contacts} kontakter fran {len(with_url)} klubbar -> {output}')
    return results


if __name__ == '__main__':
    clubs_file = sys.argv[1] if len(sys.argv) > 1 else 'clubs.json'
    output = sys.argv[2] if len(sys.argv) > 2 else 'contacts.json'
    scrape_all(clubs_file, output)
