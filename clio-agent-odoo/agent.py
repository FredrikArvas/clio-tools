"""
agent.py — clio-agent-odoo

Flask-endpoint som tar emot meddelanden från Odoo #clio-kanalen,
anropar Claude API och postar svaret tillbaka i kanalen via XML-RPC.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
load_dotenv(Path(__file__).parent / '.env', override=True)

# Gör clio_access och clio_core tillgängliga
for _p in [str(ROOT), str(ROOT / 'clio-core')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import anthropic
from odoo_reply import post_reply

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('clio-agent-odoo')

app = Flask(__name__)

SHARED_SECRET  = os.environ.get('CLIO_ODOO_SECRET', '')
ANTHROPIC_KEY  = os.environ.get('ANTHROPIC_API_KEY', '')
MODEL          = os.environ.get('CLIO_MODEL', 'claude-sonnet-4-6')
SYSTEM_PROMPT  = (
    'Du är Clio, AI-assistent på Arvas International AB, Muskö. '
    'Du svarar i Odoo Discuss. Håll svaren koncisa och använd markdown '
    'när det hjälper läsbarheten. Svara alltid på samma språk som frågan.'
)


def _check_access(sender_email: str) -> str:
    """
    Returnerar behörighetsnivå för avsändaren.
    Försöker använda clio_access om konfigurerat, annars enkel e-post-lista.
    """
    matrix_page_id = os.environ.get('CLIO_ACCESS_MATRIX_PAGE_ID', '')
    notion_token   = os.environ.get('NOTION_API_KEY', '')
    admin_emails   = {
        e.strip().lower()
        for e in os.environ.get('CLIO_ADMIN_EMAILS', '').split(',')
        if e.strip()
    }

    if matrix_page_id and notion_token:
        try:
            from clio_access import AccessManager
            am = AccessManager(
                notion_token=notion_token,
                matrix_page_id=matrix_page_id,
                admin_identities=admin_emails,
            )
            return am.get_level({'email': sender_email.lower()})
        except Exception as exc:
            logger.warning('clio_access misslyckades: %s — faller tillbaka på e-postlista', exc)

    email_lower = sender_email.lower()
    if email_lower in admin_emails:
        return 'admin'

    allowed_emails = {
        e.strip().lower()
        for e in os.environ.get('CLIO_ALLOWED_EMAILS', '').split(',')
        if e.strip()
    }
    if email_lower in allowed_emails:
        return 'write'

    return 'denied'


def _build_reply(message: str, sender_name: str, level: str) -> str:
    """Anropar Claude och returnerar svarstext (markdown)."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    user_content = f'[{sender_name}]: {message}'
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': user_content}],
    )
    return response.content[0].text


def _process(message: str, sender_email: str, sender_name: str, channel_id: int):
    level = _check_access(sender_email)
    logger.info('Meddelande från %s (nivå: %s): %s', sender_email, level, message[:80])

    if level == 'denied':
        reply = f'Hej {sender_name} — du har tyvärr inte behörighet att använda Clio här.'
    else:
        try:
            reply = _build_reply(message, sender_name, level)
        except Exception as exc:
            logger.error('Claude API-fel: %s', exc)
            reply = 'Tekniskt fel — kunde inte generera svar. Försök igen.'

    try:
        post_reply(channel_id=channel_id, text=reply)
    except Exception as exc:
        logger.error('Kunde inte posta svar i Odoo: %s', exc)


@app.route('/message', methods=['POST'])
def handle_message():
    data = request.get_json(silent=True) or {}

    if SHARED_SECRET and data.get('secret') != SHARED_SECRET:
        logger.warning('Obehörigt anrop från %s', request.remote_addr)
        return jsonify({'error': 'unauthorized'}), 401

    message      = (data.get('message') or '').strip()
    sender_email = (data.get('sender_email') or '').strip()
    sender_name  = (data.get('sender_name') or sender_email).strip()
    channel_id   = data.get('channel_id')

    if not message or not sender_email or not channel_id:
        return jsonify({'error': 'message, sender_email och channel_id krävs'}), 400

    t = threading.Thread(
        target=_process,
        args=(message, sender_email, sender_name, channel_id),
        daemon=True,
    )
    t.start()

    return jsonify({'status': 'accepted'}), 202


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'model': MODEL})


def main():
    port = int(os.environ.get('CLIO_ODOO_PORT', 8100))
    host = os.environ.get('CLIO_ODOO_HOST', '127.0.0.1')
    logger.info('clio-agent-odoo startar på %s:%d', host, port)
    app.run(host=host, port=port, threaded=True)


if __name__ == '__main__':
    main()
