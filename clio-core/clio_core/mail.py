"""
clio_core.mail — delad mail-utility

Delegerar till clio-agent-mail/smtp_client som finns på alla clio-maskiner.
Credentials: clio-agent-mail/.env (IMAP_PASSWORD_CLIO).
"""

import configparser
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# clio-core ligger i clio-tools/clio-core/clio_core/ → root = tre nivåer upp
_AGENT_MAIL = Path(__file__).parent.parent.parent / "clio-agent-mail"


def send(to: str, subject: str, body: str, html: str = None) -> bool:
    """Skickar mail via clio-agent-mail smtp_client. Returnerar True vid lyckat sändning."""
    if str(_AGENT_MAIL) not in sys.path:
        sys.path.insert(0, str(_AGENT_MAIL))

    try:
        import smtp_client
        from dotenv import load_dotenv

        load_dotenv(_AGENT_MAIL / ".env", override=False)
        imap_pass = os.getenv("IMAP_PASSWORD_CLIO", "")
        if not imap_pass:
            raise EnvironmentError("IMAP_PASSWORD_CLIO saknas i clio-agent-mail/.env")

        config = configparser.ConfigParser()
        config.read(_AGENT_MAIL / "clio.config")
        config.set("mail", "imap_password_clio", imap_pass)

        smtp_client.send_email(
            config=config,
            from_account_key="clio",
            to_addr=to,
            subject=subject,
            body=body,
            html_body=html,
        )
        logger.info(f"Mail skickat: clio → {to} | {subject[:60]}")
        return True

    except Exception as e:
        logger.error(f"Mail-fel: {e}")
        return False
