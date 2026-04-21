"""
odoo_reply.py — postar Clio-svar i en discuss.channel via Odoo JSON-RPC.

Autentiserar som Clio Bot via pyodoo_connect (session-cookie).
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
load_dotenv(Path(__file__).parent / '.env', override=True)

for _p in [str(ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger('clio-agent-odoo.reply')

_ODOO_URL     = os.environ.get('ODOO_URL',           'http://localhost:8069')
_ODOO_DB      = os.environ.get('ODOO_DB',            'aiab')
_BOT_LOGIN    = os.environ.get('ODOO_BOT_LOGIN',     'clio-bot')
_BOT_PASSWORD = os.environ.get('ODOO_BOT_PASSWORD',  '')

_session_cache: dict[str, str] = {}


def _get_session() -> str:
    """Returnerar en cachad Odoo session-id för Clio Bot."""
    cache_key = f'{_ODOO_URL}/{_ODOO_DB}/{_BOT_LOGIN}'
    if cache_key not in _session_cache:
        from pyodoo_connect import connect_odoo
        sid = connect_odoo(_ODOO_URL, _ODOO_DB, _BOT_LOGIN, _BOT_PASSWORD)
        if not sid:
            raise RuntimeError(
                f'Odoo-autentisering misslyckades för {_BOT_LOGIN}. '
                'Kontrollera ODOO_BOT_LOGIN och ODOO_BOT_PASSWORD i .env.'
            )
        _session_cache[cache_key] = sid
        logger.debug('Ny Odoo-session skapad för Clio Bot')
    return _session_cache[cache_key]


def _md_to_html(text: str) -> str:
    """
    Konverterar markdown till Odoo-säker HTML.
    Odoo saniterar okända tags — vi HTML-escaper all text först
    och lägger sedan till <br/> för radbrytningar.
    """
    import html as html_lib

    # Extrahera kodblockar innan escaping
    code_blocks: list[str] = []

    def _save_code(m: re.Match) -> str:
        code_blocks.append(m.group(2))
        return f'\x00CODE{len(code_blocks) - 1}\x00'

    text = re.sub(r'```(\w*)\n(.*?)```', _save_code, text, flags=re.DOTALL)

    # Escape all HTML-specialtecken i resterande text
    text = html_lib.escape(text)

    # Återställ kodblockar som <pre><code>...</code></pre>
    for i, code in enumerate(code_blocks):
        text = text.replace(
            f'\x00CODE{i}\x00',
            f'<pre><code>{html_lib.escape(code)}</code></pre>',
        )

    # Stycken → separata <p>-block (Odoo renderar dessa korrekt)
    # Enkla radbrytningar → mellanslag inom stycket
    paragraphs = text.split('\n\n')
    parts = []
    for para in paragraphs:
        inner = para.replace('\n', ' ').strip()
        if inner:
            parts.append(f'<p>{inner}</p>')
    return ''.join(parts) if parts else f'<p>{text}</p>'


def post_reply(channel_id: int, text: str) -> None:
    """Postar text som meddelande i angiven discuss.channel."""
    import requests

    sid = _get_session()
    html_body = _md_to_html(text)

    resp = requests.post(
        f'{_ODOO_URL}/web/dataset/call_kw',
        json={
            'jsonrpc': '2.0',
            'method':  'call',
            'id':      1,
            'params': {
                'model':  'discuss.channel',
                'method': 'clio_post_reply',
                'args':   [channel_id, html_body],
                'kwargs': {},
            },
        },
        cookies={'session_id': sid},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get('error'):
        raise RuntimeError(data['error'])

    # Om sessionen gick ut, töm cachen så nästa anrop återautentiserar
    result = data.get('result')
    if result is None and not data.get('error'):
        cache_key = f'{_ODOO_URL}/{_ODOO_DB}/{_BOT_LOGIN}'
        _session_cache.pop(cache_key, None)

    logger.info('Svar postat i kanal %d (%d tecken)', channel_id, len(text))
