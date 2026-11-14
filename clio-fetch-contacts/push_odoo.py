"""
push_odoo.py — Upserterar res.partner i Odoo med bild från webben.

ref-format : agm-<company>-<slug>
Tagg       : AGM
Databas    : aiab (default)
"""

import base64
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clio_odoo import connect

TAG_NAME = 'AGM'
COMMENT  = 'Importerad av clio-fetch-contacts'
IMG_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (clio-fetch-contacts/1.0)',
    'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
}


def slugify(name: str) -> str:
    norm = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', norm.lower()).strip('-')


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif', '.svg'}

def _download_image(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=IMG_HEADERS, timeout=12)
        ct = r.headers.get('content-type', '')
        url_lower = url.split('?')[0].lower()
        is_image = 'image' in ct or any(url_lower.endswith(ext) for ext in IMAGE_EXTENSIONS)
        if r.status_code == 200 and is_image:
            return r.content
        print(f'    Bild-svar ej bild (status={r.status_code}, content-type={ct})')
    except Exception as e:
        print(f'    Bildhämtning misslyckades: {e}')
    return None


def _get_or_create_tag(env, name: str) -> int:
    Tag  = env['res.partner.category']
    tags = Tag.search_read([('name', '=', name)], ['id'])
    return tags[0]['id'] if tags else Tag.create({'name': name})


def _upsert_person(env, person: dict, company: str, tag_id: int,
                   parent_id: int = None) -> tuple:
    Partner = env['res.partner']
    name    = (person.get('name') or '').strip()
    if not name:
        return None, 'skip'

    slug = slugify(name)
    ref  = f'agm-{company}-{slug}'

    vals = {
        'name':        name,
        'is_company':  False,
        'function':    person.get('title') or '',
        'email':       person.get('email') or '',
        'ref':         ref,
        'comment':     COMMENT,
        'category_id': [(4, tag_id)],
    }
    if parent_id:
        vals['parent_id'] = parent_id

    image_url = person.get('image_url')
    if image_url:
        img_data = _download_image(image_url)
        if img_data:
            vals['image_1920'] = base64.b64encode(img_data).decode()
            print(f'    [bild] hamtad ({len(img_data):,} bytes)')
        else:
            print(f'    [!] Ingen bild: {image_url}')

    existing = Partner.search_read([('ref', '=', ref)], ['id'])
    if existing:
        pid = existing[0]['id']
        Partner.write([pid], vals)
        return pid, 'updated'
    else:
        pid = Partner.create(vals).id
        return pid, 'created'


def _find_or_create_company(env, name: str, create: bool = False) -> int | None:
    Partner = env['res.partner']
    hits = Partner.search_read(
        [('name', 'ilike', name), ('is_company', '=', True)], ['id', 'name']
    )
    if hits:
        exact = [h for h in hits if h['name'].lower() == name.lower()]
        match = exact[0] if exact else hits[0]
        print(f'  Moderbolag: {match["name"]} (id={match["id"]})')
        return match['id']
    if create:
        pid = Partner.create({'name': name, 'is_company': True,
                              'comment': COMMENT}).id
        print(f'  Moderbolag skapat: {name} (id={pid})')
        return pid
    print(f'  [!] Hittade inget bolag for "{name}" - fortsatter utan parent_id')
    return None


def push_all(persons_file: str, company: str, db: str = 'aiab',
             parent_name: str = None, create_parent: bool = False) -> dict:
    print(f'Ansluter till Odoo ({db}) ...')
    env    = connect(db=db)
    tag_id = _get_or_create_tag(env, TAG_NAME)
    print(f'Tagg "{TAG_NAME}" id={tag_id}')

    parent_id = None
    if parent_name:
        parent_id = _find_or_create_company(env, parent_name, create=create_parent)

    persons = json.loads(Path(persons_file).read_text(encoding='utf-8'))
    stats   = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}

    for p in persons:
        name = p.get('name', '?')
        print(f'\n  >> {name} ({p.get("title", "")})')
        try:
            pid, action = _upsert_person(env, p, company, tag_id, parent_id)
            if action == 'skip':
                stats['skipped'] += 1
                print(f'    Hoppade (inget namn)')
            else:
                stats[action] += 1
                print(f'    {action.upper()} (id={pid})')
        except Exception as e:
            stats['errors'] += 1
            print(f'    FEL: {e}')

    print(f'\n=== Resultat ===')
    print(f'Skapade:   {stats["created"]}')
    print(f'Uppdaterade: {stats["updated"]}')
    print(f'Hoppade:   {stats["skipped"]}')
    print(f'Fel:       {stats["errors"]}')
    return stats


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--persons', required=True, help='persons_<company>.json')
    p.add_argument('--company', required=True, help='Bolagsslug, t.ex. norion')
    p.add_argument('--db',      default='aiab')
    args = p.parse_args()
    push_all(args.persons, args.company, db=args.db)
