"""
agent.py — clio-agent-odoo

Flask-endpoint som tar emot meddelanden från Odoo #clio-kanalen,
anropar Claude API och postar svaret tillbaka i kanalen via XML-RPC.

RAG: Kanaler med CHANNEL_RAG_MAP söker projektminnet innan Claude svarar.
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
load_dotenv(Path(__file__).parent / '.env')

for _p in [str(ROOT), str(ROOT / 'clio-core'), str(ROOT / 'clio-rag')]:
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

# Kanal-id -> Qdrant-collection (RAG-projektminne)
CHANNEL_RAG_MAP: dict[int, str] = {
    4: "cap_ssf_pmo",   # #SSF-PMO i ssf_t2
    5: "cap_ssf_pmo",   # #SSF-PMO i aiab
}

SYSTEM_PROMPT_BASE = (
    'Du är Clio, AI-assistent på Arvas International AB, Muskö. '
    'Du svarar i Odoo Discuss. Håll svaren koncisa och använd markdown '
    'när det hjälper läsbarheten. Svara alltid på samma språk som frågan.'
)

SYSTEM_PROMPT_RAG = (
    'Du är Clio, AI-assistent och projektminne för Capgemini-SSF-projektet. '
    'Du svarar i Odoo Discuss #SSF-PMO. '
    'Du får relevanta textpassager från projektdokumenten som kontext. '
    'Basera ditt svar på dessa passager. Ange källdokument i hakparentes, '
    'ex. [SSF Digitaliseringsstrategisk handlingsplan]. '
    'Om svaret inte finns i passagerna, säg det tydligt. '
    'Håll svaren koncisa. Svara alltid på samma språk som frågan.'
)


# ---------------------------------------------------------------------------
# RAG-sökning
# ---------------------------------------------------------------------------

def _rag_search(question: str, collection: str, top_k: int = 5) -> str:
    """Söker RAG-collection och returnerar formaterad kontext-sträng."""
    try:
        from openai import OpenAI
        from qdrant_client import QdrantClient

        oai    = OpenAI()
        vec    = oai.embeddings.create(input=[question], model="text-embedding-3-small").data[0].embedding
        qdrant = QdrantClient(host="localhost", port=6333)
        hits   = qdrant.query_points(
            collection_name=collection,
            query=vec,
            limit=top_k,
            with_payload=True,
        ).points

        if not hits:
            return ""

        parts = []
        for i, hit in enumerate(hits, 1):
            p     = hit.payload
            title = p.get("title", "Okänt dokument")
            text  = p.get("summary", "")
            parts.append(f"[Passage {i} — {title}]\n{text}")
        return "\n\n".join(parts)

    except Exception as exc:
        logger.warning("RAG-sökning misslyckades: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Behörighetskontroll
# ---------------------------------------------------------------------------

def _check_access(sender_email: str) -> str:
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


# ---------------------------------------------------------------------------
# Claude-anrop
# ---------------------------------------------------------------------------

def _build_reply(message: str, sender_name: str, rag_context: str = "") -> str:
    client  = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    if rag_context:
        system       = SYSTEM_PROMPT_RAG
        user_content = (
            f"Projektdokument (kontext):\n\n{rag_context}\n\n"
            f"Fråga från {sender_name}: {message}"
        )
    else:
        system       = SYSTEM_PROMPT_BASE
        user_content = f'[{sender_name}]: {message}'

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=system,
        messages=[{'role': 'user', 'content': user_content}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# Meddelandehantering
# ---------------------------------------------------------------------------

def _process(
    message: str,
    sender_email: str,
    sender_name: str,
    channel_id: int,
    db: str | None = None,
    bot_login: str | None = None,
    bot_password: str | None = None,
):
    level = _check_access(sender_email)
    logger.info('Meddelande från %s (nivå: %s) i kanal %d@%s: %s',
                sender_email, level, channel_id, db or '?', message[:80])

    if level == 'denied':
        reply = f'Hej {sender_name} — du har tyvärr inte behörighet att använda Clio här.'
    else:
        try:
            rag_context = ""
            collection  = CHANNEL_RAG_MAP.get(channel_id)
            if collection:
                logger.info('RAG-sökning i collection: %s', collection)
                rag_context = _rag_search(message, collection)
            reply = _build_reply(message, sender_name, rag_context)
        except Exception as exc:
            logger.error('Claude API-fel: %s', exc)
            reply = 'Tekniskt fel — kunde inte generera svar. Försök igen.'

    try:
        post_reply(
            channel_id=channel_id,
            text=reply,
            db=db,
            bot_login=bot_login,
            bot_password=bot_password,
        )
    except Exception as exc:
        logger.error('Kunde inte posta svar i Odoo: %s', exc)


# ---------------------------------------------------------------------------
# Flask-endpoints
# ---------------------------------------------------------------------------

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
    db           = (data.get('db') or '').strip() or None
    bot_login    = (data.get('bot_login') or '').strip() or None
    bot_password = (data.get('bot_password') or '').strip() or None

    if not message or not sender_email or not channel_id:
        return jsonify({'error': 'message, sender_email och channel_id krävs'}), 400

    t = threading.Thread(
        target=_process,
        args=(message, sender_email, sender_name, channel_id, db, bot_login, bot_password),
        daemon=True,
    )
    t.start()

    return jsonify({'status': 'accepted'}), 202


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'model': MODEL, 'rag_channels': list(CHANNEL_RAG_MAP.keys())})


def main():
    port = int(os.environ.get('CLIO_ODOO_PORT', 8100))
    host = os.environ.get('CLIO_ODOO_HOST', '127.0.0.1')
    logger.info('clio-agent-odoo startar på %s:%d', host, port)
    app.run(host=host, port=port, threaded=True)


if __name__ == '__main__':
    main()
