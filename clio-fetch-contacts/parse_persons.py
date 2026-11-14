"""
parse_persons.py — Skickar HTML till Claude och extraherar persondata inkl. bild-URL.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / '.env', override=True)
load_dotenv(Path(__file__).parent / '.env', override=False)

import anthropic

PROMPT = """\
Du analyserar HTML från en bolagswebbplats och extraherar alla namngivna personer: \
styrelseledamöter, ledningsgrupp och assistenter.

Returnera ENBART ett JSON-objekt med följande format:
{
  "persons": [
    {
      "name": "Förnamn Efternamn",
      "title": "Titel/befattning",
      "image_url": "URL från src- eller data-src-attributet på närmaste img-tagg (returnera exakt som i HTML:en, kan vara relativ URL)",
      "email": "epost@exempel.com eller null"
    }
  ]
}

Regler:
- Inkludera ALLA namngivna personer du hittar
- image_url: ta src-attributet från personens foto. Prova data-src eller data-lazy-src om src saknas eller är en platshållare (1x1 pixel, spinner, loading.gif). Sätt null om ingen riktig bild finns.
- Ignorera logotypbilder, ikoner och dekorationsbilder
- title = personens befattning/roll på bolaget
- Om du är osäker — inkludera personen

HTML:
"""

MAX_HTML_CHARS = 80_000


def _resolve_url(image_url: str, base_url: str) -> str:
    if not image_url:
        return None
    if image_url.startswith('//'):
        return 'https:' + image_url
    if image_url.startswith('http'):
        return image_url
    return urljoin(base_url, image_url)


def parse(html: str, base_url: str, output_file: str = None) -> list:
    client = anthropic.Anthropic()

    truncated = html[:MAX_HTML_CHARS]
    print(f'  Skickar {len(truncated):,}/{len(html):,} tecken HTML till Claude ...')

    msg = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=4096,
        messages=[{'role': 'user', 'content': PROMPT + truncated}],
    )

    raw = msg.content[0].text.strip()
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        print('  FEL: Claude returnerade inget JSON')
        return []

    data = json.loads(m.group())
    persons = data.get('persons', [])

    for p in persons:
        p['image_url'] = _resolve_url(p.get('image_url'), base_url)

    print(f'  {len(persons)} person(er) extraherade:')
    for p in persons:
        img_mark = '[bild]' if p.get('image_url') else '[    ]'
        print(f'    {img_mark} {p["name"]} - {p.get("title", "")}')

    if output_file:
        Path(output_file).write_text(
            json.dumps(persons, indent=2, ensure_ascii=False), encoding='utf-8'
        )
        print(f'  Sparad: {output_file}')

    return persons


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Användning: python parse_persons.py <raw.html> <base_url> [persons.json]')
        sys.exit(1)
    html_file = sys.argv[1]
    base_url  = sys.argv[2]
    out       = sys.argv[3] if len(sys.argv) > 3 else 'persons.json'
    html      = Path(html_file).read_text(encoding='utf-8')
    parse(html, base_url, out)
