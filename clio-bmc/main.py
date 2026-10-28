"""
main.py -- clio-bmc

Berikar BMC-coachsessioner med Claude-analys och sparar till Notion.

Steg:
  import  -- laser handoff-JSON fran coachsession
  enrich  -- berikar ett eller alla block med Claude-reasoning (+valfri URL)
  push    -- sparar till Notion
  status  -- visar aktuellt lage

Anvandning:
  python main.py --bolag "Acme AB" --version as-is --step import --input session.json
  python main.py --bolag "Acme AB" --version as-is --step enrich --block vp
  python main.py --bolag "Acme AB" --version as-is --step enrich --block all --url https://...
  python main.py --bolag "Acme AB" --version as-is --step push
  python main.py --bolag "Acme AB" --version as-is --step status
  python main.py --bolag "Acme AB" --version as-is --step all --input session.json
"""

import argparse
import os
import sys
from pathlib import Path

os.chdir(Path(__file__).parent)

from session import BLOCK_NAMES, load_or_create, status_summary

# Kortkommandon for block-namn
BLOCK_ALIAS = {
    'vp':   'vardeerbjudande',
    'ks':   'kundsegment',
    'k':    'kanaler',
    'kr':   'kundrelationer',
    'is':   'intaktsstromar',
    'nr':   'nyckelresurser',
    'na':   'nyckelaktiviteter',
    'np':   'nyckelpartners',
    'kost': 'kostnadsstruktur',
}

STATUS_ICON = {'pending': '[ ]', 'enriched': '[~]', 'pushed': '[X]'}


def _resolve_block(name: str) -> str:
    return BLOCK_ALIAS.get(name, name)


def _print_status(session: dict) -> None:
    bolag   = session['bolag']
    version = session['version']
    print(f'\n=== STATUS: {bolag} ({version}) ===')
    for block_name in BLOCK_NAMES:
        block      = session['blocks'][block_name]
        icon       = STATUS_ICON.get(block['status'], '?')
        coach_len  = len(block.get('coach_text') or '')
        enrich_len = len(block.get('enriched_text') or '')
        print(f'  {icon} {block_name:<22} coach={coach_len:>5}  enrich={enrich_len:>5}')
    counts = status_summary(session)
    print(f'\n  Totalt: pending={counts["pending"]}  '
          f'enriched={counts["enriched"]}  pushed={counts["pushed"]}')
    if session.get('notion_page_id'):
        pid = session['notion_page_id'].replace('-', '')
        print(f'  Notion: https://notion.so/{pid}')


def main():
    parser = argparse.ArgumentParser(
        description='clio-bmc -- Berikar BMC-sessioner med Claude-analys'
    )
    parser.add_argument('--bolag',   required=True,
                        help='Bolagsnamn, t.ex. "Acme AB"')
    parser.add_argument('--version', default='as-is',
                        choices=['as-is', 'to-be'],
                        help='BMC-version (default: as-is)')
    parser.add_argument('--datum',   default=None,
                        help='Datum YYYY-MM-DD (default: idag)')
    parser.add_argument('--step',
                        choices=['import', 'enrich', 'push', 'status', 'all'],
                        default='status',
                        help='Steg att kora (default: status)')
    parser.add_argument('--block',   default='all',
                        help='Block-namn eller "all" (for enrich-steget)')
    parser.add_argument('--input',   default=None,
                        help='Handoff-JSON fran coachsessionen')
    parser.add_argument('--url',     default=None,
                        help='URL att hamta som berikningskalla (valfritt)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Simulera utan att skriva till Notion')
    args = parser.parse_args()

    # ── Import ────────────────────────────────────────────────────────────────
    if args.step in ('import', 'all'):
        if not args.input:
            print('FEL: --input kravs for import-steget.')
            sys.exit(1)
        print(f'\n=== STEG 1: Importerar coach-output ===')
        from coach_import import import_coach_output
        session = import_coach_output(args.input, args.bolag, args.version, args.datum)

    # ── Enrich ────────────────────────────────────────────────────────────────
    if args.step in ('enrich', 'all'):
        print(f'\n=== STEG 2: Berikar block ===')
        from enrich_block import enrich, enrich_all

        session   = load_or_create(args.bolag, args.version, args.datum)
        url_html  = None
        if args.url:
            from fetch_page import fetch as fetch_html
            url_html = fetch_html(args.url)

        block_name = _resolve_block(args.block)
        if block_name == 'all':
            count = enrich_all(session)
            print(f'\n  {count} block berikade.')
        else:
            if block_name not in BLOCK_NAMES:
                print(f'FEL: Okant block "{args.block}". '
                      f'Giltiga: {", ".join(BLOCK_NAMES)}')
                sys.exit(1)
            enrich(session, block_name, url_html)

    # ── Push ──────────────────────────────────────────────────────────────────
    if args.step in ('push', 'all'):
        print(f'\n=== STEG 3: Pushar till Notion ===')
        from push_notion import push

        session = load_or_create(args.bolag, args.version, args.datum)
        page_id = push(session, dry_run=args.dry_run)
        if page_id:
            print(f'  Notion: https://notion.so/{page_id.replace("-", "")}')

    # ── Status ────────────────────────────────────────────────────────────────
    if args.step == 'status':
        session = load_or_create(args.bolag, args.version, args.datum)
        _print_status(session)

    print('\nKlart!')


if __name__ == '__main__':
    main()
