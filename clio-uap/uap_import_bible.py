#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uap_import_bible.py — importera bible_encounters.json till uap.encounter

Användning:
  python3 uap_import_bible.py [--dry-run] [--json <fil>]

Standardfil: bible_encounters.json (bredvid detta skript)
Duplikatskydd: hoppar över encounter_id som redan finns i Odoo.
"""
import sys
import os
import json
import uuid
import xmlrpc.client
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')
load_dotenv(Path(__file__).parent.parent / '.env')

# VIGIL_ODOO_* = intern URL för UAP-databasen; autentisering via ROTATE_FREDRIK_*
URL  = os.environ.get('VIGIL_ODOO_URL') or os.environ.get('ODOO_URL', 'http://localhost:8079')
DB   = os.environ.get('VIGIL_ODOO_DB')  or os.environ.get('ODOO_DB',  'uap')
USER = os.environ.get('ROTATE_FREDRIK_LOGIN') or os.environ.get('ODOO_USER', '')
PW   = os.environ.get('ROTATE_FREDRIK_PASSWORD') or os.environ.get('ODOO_PASSWORD', '')


def get_uid():
    common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
    uid = common.authenticate(DB, USER, PW, {})
    if not uid:
        raise SystemExit(f"Autentisering misslyckades för {USER} mot {URL}/{DB}")
    return uid

DRY_RUN   = '--dry-run' in sys.argv
JSON_PATH = None
for i, arg in enumerate(sys.argv[1:], 1):
    if arg == '--json' and i < len(sys.argv):
        JSON_PATH = sys.argv[i + 1]

if JSON_PATH is None:
    JSON_PATH = Path(__file__).parent / 'bible_encounters.json'

SOURCE_TAG = 'BIB'

# Israel country_id i Odoo (res.country name='Israel')
# Används som fallback; de flesta bibliska händelser är i Levanten.
ISRAEL_COUNTRY_NAME = 'Israel'

# Mapp: JSON-kategori → encounter_class (1–4)
CATEGORY_TO_CLASS = {
    'ANGEL_APPEARANCE':  '3',
    'THEOPHANY':         '3',
    'ASCENSION':         '4',
    'CHARIOT_VISION':    '2',
    'HEAVENLY_VOICE':    '1',
    'PILLAR_FIRE_CLOUD': '1',
    'POSSESSION':        '3',
    'MIRACLE_NATURE':    '1',
    'MIRACLE_HEALING':   '1',
    'RESURRECTION':      '2',
}

# Mapp: hynek_preliminary → encounter_class om CATEGORY inte ger nog
HYNEK_TO_CLASS = {
    'NL':  '1',
    'CE1': '1',
    'CE2': '2',
    'CE3': '3',
    'CE4': '4',
}


def connect():
    uid    = get_uid()
    models = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object')
    return models, uid


def lookup_country(models, uid, name):
    hits = models.execute_kw(DB, uid, PW, 'res.country', 'search_read',
        [[['name', '=', name]]], {'fields': ['id'], 'limit': 1})
    return hits[0]['id'] if hits else False


def find_existing(models, uid, encounter_id):
    hits = models.execute_kw(DB, uid, PW, 'uap.encounter', 'search_read',
        [[['encounter_id', '=', encounter_id]]],
        {'fields': ['id'], 'limit': 1})
    return hits[0] if hits else None


def build_vals(entry, country_id):
    enc_id  = entry['encounter_id']
    cat     = entry.get('category', '')
    hynek   = entry.get('hynek_preliminary', '')

    enc_class = CATEGORY_TO_CLASS.get(cat) or HYNEK_TO_CLASS.get(hynek) or '1'

    research_parts = []
    if entry.get('source_ref'):
        research_parts.append(f"Bibelref: {entry['source_ref']}")
    if entry.get('hynek_preliminary'):
        research_parts.append(f"Hynek (preliminärt): {entry['hynek_preliminary']}")
    if entry.get('category'):
        research_parts.append(f"Kategori: {entry['category']}")
    if entry.get('person'):
        research_parts.append(f"Person: {entry['person']}")
    if entry.get('research_notes'):
        research_parts.append(entry['research_notes'])

    return {
        'encounter_id':          enc_id,
        'encounter_guid':        str(uuid.uuid4()),
        'title_en':              entry.get('title_en', enc_id),
        'description_en':        entry.get('description_en', ''),
        'location':              entry.get('location', ''),
        'encounter_class':       enc_class,
        'entity_type':           entry.get('entity_type', 'Unknown'),
        'eth_origin':            '2',   # Okänt ursprung — bibliografisk källa
        'is_case_report':        True,
        'status':                'pending',
        'research_notes':        '\n'.join(research_parts),
        'source_url':            entry.get('bible_url', ''),
        'country_id':            country_id or False,
        'language_original':     'other',
    }


def main():
    print(f"Källfil:  {JSON_PATH}")
    print(f"Odoo:     {URL} / db={DB} / user={USER}")
    print(f"Dry-run:  {DRY_RUN}")
    print()

    with open(JSON_PATH, encoding='utf-8') as f:
        entries = json.load(f)

    models, uid = connect()
    print()

    country_id = lookup_country(models, uid, ISRAEL_COUNTRY_NAME)
    if not country_id:
        print("VARNING: Hittade inte 'Israel' i res.country — country_id sätts ej")

    created = skipped = errors = 0

    for entry in entries:
        enc_id = entry.get('encounter_id', '?')

        existing = find_existing(models, uid, enc_id)
        if existing:
            print(f"  HOPPAR ÖVER  {enc_id}  (ID={existing['id']})")
            skipped += 1
            continue

        vals = build_vals(entry, country_id)

        print(f"  {'[DRY]' if DRY_RUN else 'SKAPAR'}  {enc_id}  — {vals['title_en'][:60]}")

        if DRY_RUN:
            created += 1
            continue

        try:
            new_id = models.execute_kw(DB, uid, PW, 'uap.encounter', 'create', [vals])
            print(f"           → ID={new_id}")
            created += 1
        except Exception as exc:
            print(f"           FEL: {exc}")
            errors += 1

    print()
    print(f"{'[DRY] ' if DRY_RUN else ''}Klart: {created} skapade, {skipped} hoppade över, {errors} fel")


if __name__ == '__main__':
    main()
