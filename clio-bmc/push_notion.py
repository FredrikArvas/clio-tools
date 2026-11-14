"""
push_notion.py -- Skapar och uppdaterar Notion-sida med BMC-sessiondata.

Kräver NOTION_TOKEN i miljon.
Parent-sida: NOTION_BMC_PARENT_ID (env) eller DEFAULT_PARENT_ID (bmctools NCC).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / '.env', override=True)
load_dotenv(Path(__file__).parent / '.env', override=False)

from notion_client import Client
from notion_client.errors import APIResponseError

from session import BLOCK_DISPLAY, BLOCK_NAMES, save, set_block_pushed

logger = logging.getLogger(__name__)

DEFAULT_PARENT_ID = '35867666d98a81e180ebc2bf0624da5c'  # bmctools NCC


# ── Block-byggare ──────────────────────────────────────────────────────────────

def _text_block(text: str) -> dict:
    return {
        'object': 'block',
        'type': 'paragraph',
        'paragraph': {
            'rich_text': [{'type': 'text', 'text': {'content': text[:2000]}}]
        },
    }


def _heading(text: str, level: int = 2) -> dict:
    h = f'heading_{min(max(level, 1), 3)}'
    return {
        'object': 'block',
        'type': h,
        h: {'rich_text': [{'type': 'text', 'text': {'content': text}}]},
    }


def _divider() -> dict:
    return {'object': 'block', 'type': 'divider', 'divider': {}}


def _text_chunks(text: str, chunk: int = 2000) -> list[dict]:
    """Delar upp lang text i paragraph-block om max 2000 tecken."""
    return [_text_block(text[i:i + chunk]) for i in range(0, len(text), chunk)]


# ── Sidbyggare ─────────────────────────────────────────────────────────────────

def build_page_children(session: dict) -> list:
    """Bygger Notion-block-lista fran session-data."""
    children = [
        _text_block(
            f"Bolag: {session['bolag']}  |  "
            f"Version: {session['version']}  |  "
            f"Datum: {session['datum']}"
        ),
        _divider(),
    ]

    for block_name in BLOCK_NAMES:
        block   = session['blocks'][block_name]
        display = BLOCK_DISPLAY[block_name]
        children.append(_heading(display, level=2))

        coach_text = (block.get('coach_text') or '').strip()
        if coach_text:
            children.append(_heading('Coach-session', level=3))
            children.extend(_text_chunks(coach_text))

        enriched = (block.get('enriched_text') or '').strip()
        if enriched:
            children.append(_heading('Clio-analys', level=3))
            children.extend(_text_chunks(enriched))

        if not coach_text and not enriched:
            children.append(_text_block('(inte ifyllt)'))

        children.append(_divider())

    return children


# ── Push ───────────────────────────────────────────────────────────────────────

def push(session: dict, dry_run: bool = False, base_dir=None) -> str | None:
    """
    Skapar eller uppdaterar Notion-sida for sessionen.

    Returns:
        Notion page ID (str) eller None vid dry_run/fel.
    Raises:
        EnvironmentError: om NOTION_TOKEN saknas.
    """
    token = os.environ.get('NOTION_TOKEN')
    if not token:
        raise EnvironmentError('NOTION_TOKEN saknas i miljon.')

    parent_id = os.environ.get('NOTION_BMC_PARENT_ID', DEFAULT_PARENT_ID)
    title     = f"BMC -- {session['bolag']} -- {session['version']} -- {session['datum']}"
    children  = build_page_children(session)

    if dry_run:
        print(f'  [dry-run] Skulle skrivit: "{title}" ({len(children)} block)')
        return None

    client = Client(auth=token)
    existing_id = session.get('notion_page_id')

    try:
        if existing_id:
            print(f'  Uppdaterar befintlig sida ({existing_id}) ...')
            old_blocks = client.blocks.children.list(block_id=existing_id)
            for blk in old_blocks.get('results', []):
                try:
                    client.blocks.delete(block_id=blk['id'])
                except APIResponseError:
                    pass
            _append_in_batches(client, existing_id, children)
            page_id = existing_id
            print(f'  Uppdaterad: {page_id}')
        else:
            print(f'  Skapar ny sida: "{title}" ...')
            page = client.pages.create(
                parent={'page_id': parent_id},
                properties={'title': [{'text': {'content': title}}]},
                children=children[:100],
            )
            page_id = page['id']
            session['notion_page_id'] = page_id
            if len(children) > 100:
                _append_in_batches(client, page_id, children[100:])
            print(f'  Skapad: {page_id}')

        for block_name in BLOCK_NAMES:
            if session['blocks'][block_name]['status'] == 'enriched':
                set_block_pushed(session, block_name)
        save(session, base_dir)
        return page_id

    except APIResponseError as exc:
        logger.error('Notion API-fel: %s', exc)
        print(f'  FEL: {exc}')
        return None


def _append_in_batches(client: Client, page_id: str, blocks: list,
                       batch: int = 100) -> None:
    """Appendar block i omgangar om max 100 (Notion-gransen)."""
    for i in range(0, len(blocks), batch):
        client.blocks.children.append(block_id=page_id, children=blocks[i:i + batch])
