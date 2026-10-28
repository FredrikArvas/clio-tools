"""
session.py -- Hanterar sessionstillstand for en BMC-korning.

Sessionen sparas som JSON i .bmc/sessions/<bolag>_<version>_<datum>.json.
Varje block har status: pending -> enriched -> pushed.
"""

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

SESSIONS_DIR = Path('.bmc') / 'sessions'

BLOCK_NAMES = [
    'kundsegment',
    'vardeerbjudande',
    'kanaler',
    'kundrelationer',
    'intaktsstromar',
    'nyckelresurser',
    'nyckelaktiviteter',
    'nyckelpartners',
    'kostnadsstruktur',
]

BLOCK_DISPLAY = {
    'kundsegment':       'Kundsegment',
    'vardeerbjudande':   'Vardeerbjudande',
    'kanaler':           'Kanaler',
    'kundrelationer':    'Kundrelationer',
    'intaktsstromar':    'Intaktsstromar',
    'nyckelresurser':    'Nyckelresurser',
    'nyckelaktiviteter': 'Nyckelaktiviteter',
    'nyckelpartners':    'Nyckelpartners',
    'kostnadsstruktur':  'Kostnadsstruktur',
}

VALID_STATUSES = ('pending', 'enriched', 'pushed')


def _slugify(text: str) -> str:
    norm = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', norm.lower()).strip('-')


def session_path(bolag: str, version: str, datum: str = None,
                 base_dir: Path = None) -> Path:
    datum = datum or date.today().isoformat()
    slug = _slugify(bolag)
    base = base_dir or SESSIONS_DIR
    return base / f'{slug}_{version}_{datum}.json'


def _empty_block() -> dict:
    return {'coach_text': '', 'enriched_text': '', 'urls_fetched': [], 'status': 'pending'}


def load_or_create(bolag: str, version: str, datum: str = None,
                   base_dir: Path = None) -> dict:
    """Laddar befintlig session eller skapar en ny tom."""
    path = session_path(bolag, version, datum, base_dir)
    if path.exists():
        session = json.loads(path.read_text(encoding='utf-8'))
        print(f'  Session laddad: {path}')
        return session
    session = {
        'bolag': bolag,
        'version': version,
        'datum': datum or date.today().isoformat(),
        'notion_page_id': None,
        'blocks': {name: _empty_block() for name in BLOCK_NAMES},
    }
    print(f'  Ny session: {path}')
    return session


def save(session: dict, base_dir: Path = None) -> Path:
    """Sparar session till fil och returnerar sokvagen."""
    path = session_path(
        session['bolag'], session['version'], session['datum'], base_dir
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding='utf-8')
    return path


def set_block_text(session: dict, block_name: str, coach_text: str) -> None:
    """Satter coach-text for ett block."""
    session['blocks'][block_name]['coach_text'] = coach_text


def set_block_enriched(session: dict, block_name: str,
                       enriched_text: str, urls: list = None) -> None:
    """Markerar blocket som berikat."""
    session['blocks'][block_name]['enriched_text'] = enriched_text
    if urls:
        session['blocks'][block_name]['urls_fetched'] = list(urls)
    session['blocks'][block_name]['status'] = 'enriched'


def set_block_pushed(session: dict, block_name: str) -> None:
    """Markerar blocket som pushat till Notion."""
    session['blocks'][block_name]['status'] = 'pushed'


def get_block(session: dict, block_name: str) -> dict:
    """Hamtar ett block ur sessionen."""
    return session['blocks'][block_name]


def status_summary(session: dict) -> dict:
    """Returnerar statusrakning per status-typ."""
    counts = {s: 0 for s in VALID_STATUSES}
    for block in session['blocks'].values():
        counts[block['status']] += 1
    return counts
