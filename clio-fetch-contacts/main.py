"""
main.py — clio-fetch-contacts

Scrapar styrelse/ledning från en bolagswebbplats och importerar till Odoo.

Steg:
  1. fetch  — hämtar och rensar HTML från given URL
  2. parse  — extraherar personer med Claude (namn, titel, bild-URL)
  3. push   — upserterar res.partner med bild i Odoo

Användning:
  python main.py --company norion --url https://norionbank.se/om-oss/styrelse/
  python main.py --company lindab --url https://... --dry-run
  python main.py --company norion --step push --db aiab
  python main.py --company norion --step fetch --url https://...   # bara hämta HTML
"""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description='clio-fetch-contacts — importera bolagspersoner till Odoo'
    )
    parser.add_argument('--company', required=True,
                        help='Bolagsslug (används i ref och filnamn), t.ex. norion')
    parser.add_argument('--url',     default=None,
                        help='URL till sidan med styrelse/ledning (krävs för fetch)')
    parser.add_argument('--step',    choices=['fetch', 'parse', 'push', 'all'],
                        default='all',
                        help='Vilket steg att köra (default: all)')
    parser.add_argument('--db',      default='aiab',
                        help='Odoo-databas (default: aiab)')
    parser.add_argument('--parent',  default=None,
                        help='Moderbolagets namn i Odoo, t.ex. "Norion Bank AB"')
    parser.add_argument('--create-parent', action='store_true',
                        help='Skapa moderbolaget i Odoo om det inte finns')
    parser.add_argument('--dry-run', action='store_true',
                        help='Visa extraherade personer utan att pusha till Odoo')
    args = parser.parse_args()

    os.chdir(Path(__file__).parent)

    html_file    = f'raw_{args.company}.html'
    persons_file = f'persons_{args.company}.json'

    # ── Steg 1: Fetch ─────────────────────────────────────────────────────────
    if args.step in ('fetch', 'all'):
        if not args.url:
            print('FEL: --url krävs för fetch-steget.')
            sys.exit(1)
        print(f'\n=== STEG 1: Hämtar HTML ===')
        from fetch_page import fetch
        fetch(args.url, html_file)

    # ── Steg 2: Parse ─────────────────────────────────────────────────────────
    if args.step in ('parse', 'all'):
        if not Path(html_file).exists():
            print(f'FEL: {html_file} saknas — kör --step fetch först.')
            sys.exit(1)
        print(f'\n=== STEG 2: Extraherar personer med Claude ===')
        from parse_persons import parse
        html     = Path(html_file).read_text(encoding='utf-8')
        base_url = args.url or ''
        persons  = parse(html, base_url, persons_file)

        if args.dry_run:
            print('\n--- DRY RUN: skulle pusha följande till Odoo ---')
            for p in persons:
                slug = _slugify(p['name'])
                ref  = f'agm-{args.company}-{slug}'
                print(f'  {p["name"]}')
                print(f'    titel : {p.get("title", "")}')
                print(f'    ref   : {ref}')
                print(f'    bild  : {p.get("image_url") or "ingen"}')
            return

    # ── Steg 3: Push ──────────────────────────────────────────────────────────
    if args.step in ('push', 'all') and not args.dry_run:
        if not Path(persons_file).exists():
            print(f'FEL: {persons_file} saknas — kör --step parse först.')
            sys.exit(1)
        print(f'\n=== STEG 3: Pushar till Odoo ({args.db}) ===')
        from push_odoo import push_all
        push_all(persons_file, args.company, db=args.db,
                 parent_name=args.parent, create_parent=args.create_parent)

    print('\nKlart!')


def _slugify(name: str) -> str:
    import re, unicodedata
    norm = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', norm.lower()).strip('-')


if __name__ == '__main__':
    main()
