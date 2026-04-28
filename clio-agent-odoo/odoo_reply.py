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
load_dotenv(Path(__file__).parent / '.env')

for _p in [str(ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger('clio-agent-odoo.reply')

_ODOO_URL     = os.environ.get('ODOO_URL',           'http://localhost:8069')
_ODOO_DB      = os.environ.get('ODOO_DB',            'aiab')
_BOT_LOGIN    = os.environ.get('ODOO_BOT_LOGIN',     'clio-bot')
_BOT_PASSWORD = os.environ.get('ODOO_BOT_PASSWORD',  '')

_session_cache: dict[str, str] = {}


def _get_session(db: str, bot_login: str, bot_password: str) -> str:
    """Returnerar en cachad Odoo session-id för Clio Bot."""
    cache_key = f'{_ODOO_URL}/{db}/{bot_login}'
    if cache_key not in _session_cache:
        from pyodoo_connect import connect_odoo
        sid = connect_odoo(_ODOO_URL, db, bot_login, bot_password)
        if not sid:
            raise RuntimeError(
                f'Odoo-autentisering misslyckades för {bot_login}@{db}. '
                'Kontrollera clio_discuss.bot_password i Odoo-konfigurationen.'
            )
        _session_cache[cache_key] = sid
        logger.debug('Ny Odoo-session skapad för %s@%s', bot_login, db)
    return _session_cache[cache_key]


def _md_to_html(text: str) -> str:
    """Konverterar markdown till HTML via markdown-biblioteket."""
    try:
        import markdown
        html = markdown.markdown(
            text,
            extensions=['nl2br', 'fenced_code'],
        )
        return html
    except ImportError:
        # Fallback: enkel konvertering om markdown inte finns
        import html as html_lib
        paragraphs = text.split('\n\n')
        parts = []
        for para in paragraphs:
            inner = html_lib.escape(para).replace('\n', '<br/>').strip()
            if inner:
                parts.append(f'<p>{inner}</p>')
        return ''.join(parts) if parts else f'<p>{html_lib.escape(text)}</p>'


def post_reply(
    channel_id: int,
    text: str,
    db: str | None = None,
    bot_login: str | None = None,
    bot_password: str | None = None,
) -> None:
    """Postar text som meddelande i angiven discuss.channel."""
    import requests

    _db       = db or _ODOO_DB
    _login    = bot_login or _BOT_LOGIN
    _password = bot_password or _BOT_PASSWORD

    sid = _get_session(_db, _login, _password)
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

    result = data.get('result')
    if result is None and not data.get('error'):
        cache_key = f'{_ODOO_URL}/{_db}/{_login}'
        _session_cache.pop(cache_key, None)

    logger.info('Svar postat i kanal %d@%s (%d tecken)', channel_id, _db, len(text))
