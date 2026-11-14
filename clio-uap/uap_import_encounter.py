#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uap_import_encounter.py — importera encounter-import-*.md till uap.encounter
Användning: python3 uap_import_encounter.py <fil.md> [--dry-run]
"""
import sys
import os
import re
import uuid
import xmlrpc.client
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('/home/clioadmin/19.0/clio-tools/clio-uap/.env')

URL = os.environ.get('ODOO_URL', 'http://localhost:8079')
DB  = os.environ.get('ODOO_DB',  'uap')
UID = int(os.environ.get('ODOO_UID', '2'))
PW  = os.environ.get('ODOO_PASSWORD', '')

DRY_RUN = '--dry-run' in sys.argv

# --- Parsning ---

def parse_md(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()

    # YAML-block inuti ```yaml ... ```
    yaml_match = re.search(r'```yaml\s*\n(.*?)\n```', text, re.DOTALL)
    if not yaml_match:
        raise ValueError("Ingen ```yaml```-block hittad i filen")

    raw_yaml = yaml_match.group(1)
    fields = {}
    for line in raw_yaml.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        key = key.strip()
        val = val.strip().split('#')[0].strip()  # ta bort inline-kommentarer
        # Ta bort omgivande citattecken
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        fields[key] = val

    # Narrativ beskrivning — allt mellan "## Beskrivning (description_en)" och nästa ##
    desc_match = re.search(
        r'## Beskrivning \(description_en\)\s*\n(.*?)(?=\n## |\Z)',
        text, re.DOTALL
    )
    description_en = desc_match.group(1).strip() if desc_match else ''
    # Rensa markdown-formattering
    description_en = re.sub(r'\*\*([^*]+)\*\*', r'\1', description_en)
    description_en = re.sub(r'\*([^*]+)\*', r'\1', description_en)
    description_en = re.sub(r'`([^`]+)`', r'\1', description_en)

    return fields, description_en


def coerce(fields):
    """Konvertera strängar till rätt Python-typer."""
    result = {}

    str_fields = [
        'title_en', 'title_original', 'location',
        'encounter_class', 'discourse_level', 'official_response',
        'eth_origin', 'language_original',
    ]
    for f in str_fields:
        if f in fields and fields[f] not in ('', 'false', 'False'):
            result[f] = fields[f]

    # intelligence_indicator: kan vara int-sträng
    if 'intelligence_indicator' in fields:
        v = fields['intelligence_indicator']
        if v not in ('', 'false', 'False'):
            result['intelligence_indicator'] = v

    # Datum
    if 'date_observed' in fields and fields['date_observed']:
        try:
            dt = datetime.strptime(fields['date_observed'], '%Y-%m-%d')
            result['date_observed'] = dt.strftime('%Y-%m-%d 12:00:00')
        except ValueError:
            pass

    # Int
    if 'country_id' in fields:
        result['country_id'] = int(fields['country_id'])
    if 'observables_count' in fields:
        result['observables_count'] = int(fields['observables_count'])

    # Bool
    for bf in ['obs_antigravity', 'obs_instant_accel', 'obs_hypersonic',
               'obs_low_observability', 'obs_transmedium']:
        if bf in fields:
            result[bf] = fields[bf].lower() == 'true'

    return result


# --- Duplikatskydd ---

def find_existing(models, title_en):
    hits = models.execute_kw(DB, UID, PW, 'uap.encounter', 'search_read',
        [[['title_en', '=', title_en]]],
        {'fields': ['id', 'title_en'], 'limit': 1})
    return hits[0] if hits else None


# --- Huvud ---

def main():
    md_files = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not md_files:
        print("Användning: python3 uap_import_encounter.py <fil.md> [--dry-run]")
        sys.exit(1)

    models = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object')

    for path in md_files:
        print(f"\n{'='*60}")
        print(f"Importerar: {path}")
        print('='*60)

        try:
            fields, description_en = parse_md(path)
        except Exception as e:
            print(f"  FEL vid parsning: {e}")
            continue

        vals = coerce(fields)
        if description_en:
            vals['description_en'] = description_en

        # Kontrollera obligatoriska fält
        if 'title_en' not in vals:
            print("  FEL: title_en saknas")
            continue

        print(f"  Titel:    {vals.get('title_en')}")
        print(f"  Datum:    {vals.get('date_observed', 'saknas')}")
        print(f"  Land-ID:  {vals.get('country_id', 'saknas')}")
        print(f"  Plats:    {vals.get('location', 'saknas')}")
        print(f"  ETH:      {vals.get('eth_origin', '?')}  "
              f"Intel: {vals.get('intelligence_indicator', '?')}  "
              f"Obs: {vals.get('observables_count', 0)}")
        print(f"  Beskr:    {description_en[:80]}...")

        # Generera encounter_id och encounter_guid om de saknas
        if 'encounter_id' not in vals:
            # Land-prefix från country_id: 196=SWE, 166=NOR, 59=DEN, 70=FIN, 108=ISL
            country_prefix = {196: 'SWE', 166: 'NOR', 59: 'DEN', 70: 'FIN', 108: 'ISL'}
            prefix = country_prefix.get(vals.get('country_id', 0), 'UAP')
            basename = os.path.basename(path).replace('encounter-import-', '').replace('.md', '').upper()
            # Ta bort eventuell landkod i filnamnet (norway-, sweden-, etc.)
            for strip in ['NORWAY_', 'SWEDEN_', 'DENMARK_', 'FINLAND_']:
                basename = basename.replace(strip, '')
            vals['encounter_id'] = f"{prefix}_{basename.replace('-', '_')}"
        if 'encounter_guid' not in vals:
            vals['encounter_guid'] = str(uuid.uuid4())

        print(f"  encounter_id: {vals['encounter_id']}")
        print(f"  encounter_guid: {vals['encounter_guid']}")

        # Duplikatcheck
        existing = find_existing(models, vals['title_en'])
        if existing:
            print(f"  HOPPAR ÖVER — finns redan (ID={existing['id']})")
            continue

        if DRY_RUN:
            print("  [DRY RUN] — skapar ej record")
            continue

        try:
            new_id = models.execute_kw(DB, UID, PW, 'uap.encounter', 'create', [vals])
            print(f"  ✓ Skapad — ID={new_id}")
        except Exception as e:
            print(f"  FEL vid skapande: {e}")

    print("\nKlart.")


if __name__ == '__main__':
    main()
