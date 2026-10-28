"""
coach_import.py -- Importerar handoff-JSON fran en BMC-coachsession till lokal session.

Stodjer tva format:
  1. Med 'blocks'-nyckel: {"bolag": ..., "version": ..., "datum": ..., "blocks": {...}}
  2. Plant format:        {"kundsegment": ..., "vardeerbjudande": ..., ...}
"""

import json
from pathlib import Path

from session import BLOCK_NAMES, load_or_create, save, set_block_text


def import_coach_output(input_file: str, bolag: str, version: str,
                        datum: str = None, base_dir=None) -> dict:
    """
    Laser handoff-JSON och populerar en ny session med coach-text per block.

    Returns:
        Den uppdaterade session-dicten.
    Raises:
        FileNotFoundError: om input_file inte finns.
        json.JSONDecodeError: om filen inte ar giltig JSON.
    """
    path = Path(input_file)
    if not path.exists():
        raise FileNotFoundError(f'Handoff-fil saknas: {input_file}')

    raw = json.loads(path.read_text(encoding='utf-8'))

    if 'blocks' in raw:
        blocks  = raw['blocks']
        bolag   = raw.get('bolag', bolag)
        version = raw.get('version', version)
        datum   = raw.get('datum', datum)
    else:
        blocks = raw

    missing = set(BLOCK_NAMES) - set(blocks.keys())
    if missing:
        print(f'  Varning: saknade block i handoff: {", ".join(sorted(missing))}')

    session = load_or_create(bolag, version, datum, base_dir)

    imported = 0
    for block_name in BLOCK_NAMES:
        text = (blocks.get(block_name) or '').strip()
        if text:
            set_block_text(session, block_name, text)
            imported += 1
            print(f'  [OK] {block_name}: {len(text)} tecken')
        else:
            print(f'  [--] {block_name}: tomt')

    print(f'\n  {imported}/{len(BLOCK_NAMES)} block importerade.')
    save(session, base_dir)
    return session
