"""
push_odoo.py — Skapar/uppdaterar partner-poster i Odoo.

res.partner (company) = Förening  (ref = klubbid/rfNumber)
res.partner (person, parent_id=förening) = Kontaktperson  (function = roll)

Databas styrs av env-variabel ODOO_DB eller --db-argument (default: ssf).
"""

import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clio_odoo import connect

TAG_NAME = 'SSF-Klubb'
COMMENT  = 'Importerad av clio-ssf-klubb'


def _get_or_create_tag(env, tag_name):
    TagModel = env['res.partner.category']
    tags = TagModel.search_read([('name', '=', tag_name)], ['id'])
    if tags:
        return tags[0]['id']
    return TagModel.create({'name': tag_name})


def _upsert_club(env, club, tag_id):
    Partner = env['res.partner']
    addr = club.get('klubbaddress', {})
    vals = {
        'name':        club['klubbnamn'],
        'is_company':  True,
        'ref':         str(club.get('klubbid', '')),
        'website':     club.get('klubb_url', '') or '',
        'email':       club.get('klubb_epost', '') or '',
        'street':      addr.get('gata', ''),
        'zip':         addr.get('postnr', ''),
        'city':        addr.get('ort', ''),
        'comment':     COMMENT,
        'category_id': [(4, tag_id)],
    }
    existing = []
    if vals['ref']:
        existing = Partner.search_read(
            [('ref', '=', vals['ref']), ('is_company', '=', True)], ['id'])
    if not existing:
        existing = Partner.search_read(
            [('name', '=', vals['name']), ('is_company', '=', True)], ['id'])
    if existing:
        pid = existing[0]['id']
        Partner.write([pid], vals)
        return pid, 'updated'
    else:
        pid = Partner.create(vals).id
        return pid, 'created'


def _upsert_person(env, kontakt, parent_id, tag_id):
    Partner = env['res.partner']
    namn = (kontakt.get('namn') or '').strip()
    if not namn:
        return None, 'skip'
    vals = {
        'name':        namn,
        'is_company':  False,
        'parent_id':   parent_id,
        'function':    kontakt.get('roll') or '',
        'email':       kontakt.get('epost') or '',
        'phone':       kontakt.get('telefon') or '',
        'comment':     COMMENT,
        'category_id': [(4, tag_id)],
    }
    existing = Partner.search_read(
        [('name', '=', namn), ('parent_id', '=', parent_id), ('is_company', '=', False)],
        ['id'])
    if existing:
        pid = existing[0]['id']
        Partner.write([pid], vals)
        return pid, 'updated'
    else:
        pid = Partner.create(vals).id
        return pid, 'created'


def push_all(contacts_file='contacts.json', clubs_file=None, db=None):
    target_db = db or os.environ.get('ODOO_DB', 'ssf')
    print(f'Ansluter till Odoo {target_db}...')
    env    = connect(db=target_db)
    tag_id = _get_or_create_tag(env, TAG_NAME)
    print(f'Tagg "{TAG_NAME}" id={tag_id}')

    if contacts_file and Path(contacts_file).exists():
        data = json.loads(Path(contacts_file).read_text())
    elif clubs_file and Path(clubs_file).exists():
        clubs = json.loads(Path(clubs_file).read_text())
        data  = [{'klubb': c, 'kontakter': []} for c in clubs]
    else:
        print('FEL: Ingen datafil hittad.')
        sys.exit(1)

    stats = {'club_created': 0, 'club_updated': 0,
             'person_created': 0, 'person_updated': 0, 'skipped': 0}

    for item in data:
        club     = item['klubb']
        kontakter = item.get('kontakter', [])
        name      = club.get('klubbnamn', '?')
        try:
            partner_id, action = _upsert_club(env, club, tag_id)
            stats[f'club_{action}'] += 1
            print(f'  {action.upper()}: {name} (id={partner_id})')
            for k in kontakter:
                pid, paction = _upsert_person(env, k, partner_id, tag_id)
                if paction == 'skip':
                    stats['skipped'] += 1
                else:
                    stats[f'person_{paction}'] += 1
                    print(f'    {paction}: {k.get("namn")} ({k.get("roll")})')
        except Exception as e:
            print(f'  FEL för {name}: {e}')

    print('\n=== Resultat ===')
    print(f'Klubbar skapade:      {stats["club_created"]}')
    print(f'Klubbar uppdaterade:  {stats["club_updated"]}')
    print(f'Personer skapade:     {stats["person_created"]}')
    print(f'Personer uppdaterade: {stats["person_updated"]}')
    print(f'Hoppade over:         {stats["skipped"]}')
    return stats


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--contacts', default='contacts.json')
    p.add_argument('--clubs',    default='clubs.json')
    p.add_argument('--db',       default=None, help='Odoo-databas (default: env ODOO_DB eller ssf)')
    args = p.parse_args()
    push_all(args.contacts, args.clubs, args.db)
