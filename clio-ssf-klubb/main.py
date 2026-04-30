"""
main.py — clio-ssf-klubb: hämta klubbar → scrapa kontakter → pusha till Odoo

Steg:
  1. fetch   — hämtar klubbar från skidor.com API
  2. scrape  — besöker webbplatser och extraherar personer
  3. push    — skapar/uppdaterar poster i Odoo

Användning:
  python main.py                            # alla steg, Alla distrikt, db=ssf
  python main.py --step fetch               # bara hämta klubbar
  python main.py --step scrape              # bara scrapa (kräver clubs.json)
  python main.py --step push                # bara pusha (kräver contacts.json)
  python main.py --district Värmland        # ett distrikt
  python main.py --db ssf_t2               # annan databas
"""

import argparse, sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='clio-ssf-klubb')
    parser.add_argument('--step',          choices=['fetch', 'scrape', 'push', 'all'], default='all')
    parser.add_argument('--district',      default='Alla')
    parser.add_argument('--clubs-file',    default='clubs.json')
    parser.add_argument('--contacts-file', default='contacts.json')
    parser.add_argument('--db',            default=None,
                        help='Odoo-databas (default: env ODOO_DB eller ssf)')
    args = parser.parse_args()

    import os
    os.chdir(Path(__file__).parent)

    if args.step in ('fetch', 'all'):
        print('\n=== STEG 1: Hämtar klubbar ===')
        from fetch_clubs import fetch_clubs
        fetch_clubs(args.district, args.clubs_file)

    if args.step in ('scrape', 'all'):
        if not Path(args.clubs_file).exists():
            print(f'FEL: {args.clubs_file} saknas. Kör --step fetch först.')
            sys.exit(1)
        print('\n=== STEG 2: Scrapar kontakter ===')
        from scrape_contacts import scrape_all
        scrape_all(args.clubs_file, args.contacts_file)

    if args.step in ('push', 'all'):
        contacts = args.contacts_file if Path(args.contacts_file).exists() else None
        clubs    = args.clubs_file    if Path(args.clubs_file).exists()    else None
        if not contacts and not clubs:
            print('FEL: Varken contacts.json eller clubs.json finns.')
            sys.exit(1)
        print('\n=== STEG 3: Pushar till Odoo ===')
        from push_odoo import push_all
        push_all(contacts, clubs, db=args.db)

    print('\nKlart!')


if __name__ == '__main__':
    main()
