"""
fetch_page.py -- Hamtar HTML fran en URL och rensar bort navigation/footer.
Samma logik som clio-fetch-contacts/fetch_page.py.
"""

import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'sv-SE,sv;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

STRIP_TAGS = ['script', 'style', 'noscript', 'header', 'footer', 'nav', 'aside']


def fetch(url: str, output_file: str = None) -> str:
    """Hamtar URL, rensar HTML och returnerar som strang. Sparar till fil om output_file anges."""
    session = requests.Session()
    session.headers.update(HEADERS)

    print(f'  Hamtar {url} ...')
    r = session.get(url, timeout=15)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or 'utf-8'

    soup = BeautifulSoup(r.text, 'lxml')
    for tag in soup(STRIP_TAGS):
        tag.decompose()

    html = str(soup)

    if output_file:
        Path(output_file).write_text(html, encoding='utf-8')
        print(f'  Sparad: {output_file} ({len(html):,} tecken)')

    return html


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Anvandning: python fetch_page.py <url> [output.html]')
        sys.exit(1)
    out = sys.argv[2] if len(sys.argv) > 2 else None
    print(fetch(sys.argv[1], out))
