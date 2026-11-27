#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uap_bible_sources.py — skapa uap.source-rader för bibliska encounters
och länka dem via source_ids.

Deduplicerar på URL: ett och samma kapitel delar källpost.
Hoppar över encounters som redan har källan länkad.
"""
import json, os, xmlrpc.client
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')
load_dotenv(Path(__file__).parent.parent / '.env')

URL  = os.environ.get('VIGIL_ODOO_URL') or os.environ.get('ODOO_URL', 'http://localhost:8079')
DB   = os.environ.get('VIGIL_ODOO_DB')  or os.environ.get('ODOO_DB',  'uap')
USER = os.environ.get('ROTATE_FREDRIK_LOGIN') or os.environ.get('ODOO_USER', '')
PW   = os.environ.get('ROTATE_FREDRIK_PASSWORD') or os.environ.get('ODOO_PASSWORD', '')

common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
uid = common.authenticate(DB, USER, PW, {})
if not uid:
    raise SystemExit(f"Autentisering misslyckades för {USER}")
models = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object')

json_path = Path(__file__).parent / 'bible_encounters.json'
entries = json.loads(json_path.read_text(encoding='utf-8'))

# Bygg source_id från bible_url: sista path-delen utan .NIV
# t.ex. https://…/GEN.5.NIV  →  BIBLE_GEN_5
def url_to_source_id(url: str) -> str:
    seg = url.rstrip('/').split('/')[-1]          # "GEN.5.NIV"
    book, chapter, *_ = seg.split('.')
    return f"BIBLE_{book}_{chapter}"

# Bygg läsbart namn från book-fält + chapter ur source_ref
def build_name(entry: dict) -> str:
    ref = entry['source_ref'].split(';')[0].strip()  # "Gen 5:24"
    import re
    m = re.match(r'^((?:\d\s+)?[A-Za-z]+)\s+(\d+)', ref)
    chapter = m.group(2) if m else '?'
    return f"Bibeln — {entry['book']} {chapter} (NIV)"

# --- Skapa/hämta uap.source per unik URL ---
url_to_odoo_source_id: dict[str, int] = {}

for entry in entries:
    burl = entry.get('bible_url', '')
    if not burl or burl in url_to_odoo_source_id:
        continue

    sid = url_to_source_id(burl)
    name = build_name(entry)

    existing = models.execute_kw(DB, uid, PW, 'uap.source', 'search_read',
        [[['source_id', '=', sid]]], {'fields': ['id'], 'limit': 1})

    if existing:
        odoo_id = existing[0]['id']
        print(f"  FINNS   {sid:20s}  (ID={odoo_id})")
    else:
        odoo_id = models.execute_kw(DB, uid, PW, 'uap.source', 'create', [{
            'source_id':   sid,
            'name':        name,
            'source_type': 'web',
            'tier':        'tier_1',
            'url':         burl,
            'language':    'sv',
        }])
        print(f"  SKAPAR  {sid:20s}  {name}  (ID={odoo_id})")

    url_to_odoo_source_id[burl] = odoo_id

# --- Länka sources till encounters ---
linked = already = 0

for entry in entries:
    burl = entry.get('bible_url', '')
    if not burl:
        continue
    source_odoo_id = url_to_odoo_source_id[burl]

    hits = models.execute_kw(DB, uid, PW, 'uap.encounter', 'search_read',
        [[['encounter_id', '=', entry['encounter_id']]]],
        {'fields': ['id', 'source_ids'], 'limit': 1})
    if not hits:
        print(f"  SAKNAS  {entry['encounter_id']}")
        continue

    enc = hits[0]
    if source_odoo_id in enc['source_ids']:
        already += 1
        continue

    models.execute_kw(DB, uid, PW, 'uap.encounter', 'write',
        [[enc['id']], {'source_ids': [(4, source_odoo_id)]}])
    linked += 1

print(f"\nKällfiler: {len(url_to_odoo_source_id)} unika")
print(f"Länkade: {linked} encounter-source-par, {already} redan länkade")
