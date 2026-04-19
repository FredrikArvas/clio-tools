"""
clio_core.mail — delad mail-utility med HTTP-relä och smtp_client-fallback

Prioritetsordning:
  1. POST CLIO_MAIL_SERVICE_URL/send  (relä via laptopens mail_service.py)
  2. smtp_client direkt               (fungerar lokalt på maskiner med port 465 öppen)

Miljövariabler (root .env per maskin):
  CLIO_MAIL_SERVICE_URL — URL till mail_service.py (default http://127.0.0.1:7100)
"""

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_SERVICE_URL = os.getenv("CLIO_MAIL_SERVICE_URL", "http://127.0.0.1:7100")
_AGENT_MAIL  = Path(__file__).parent.parent.parent / "clio-agent-mail"


def send(to: str, subject: str, body: str, html: str = None) -> bool:
    """Skickar mail via HTTP-relä om tillgängligt, annars smtp_client direkt."""
    if _try_service(to, subject, body, html):
        return True
    logger.info("Mail-relä ej nåbart — försöker smtp_client direkt")
    return _try_smtp_client(to, subject, body, html)


def _try_service(to, subject, body, html) -> bool:
    try:
        payload = json.dumps(
            {"to": to, "subject": subject, "body": body, "html": html}
        ).encode()
        req = urllib.request.Request(
            f"{_SERVICE_URL}/send",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                logger.info(f"Mail skickat via relä: → {to} | {subject[:60]}")
                return True
            logger.warning(f"Mail-relä svarade {resp.status}")
            return False
    except Exception as e:
        logger.debug(f"Mail-relä ej nåbart: {e}")
        return False


def _try_smtp_client(to, subject, body, html) -> bool:
    import configparser

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
        logger.info(f"Mail skickat via smtp_client: → {to} | {subject[:60]}")
        return True

    except Exception as e:
        logger.error(f"smtp_client-fel: {e}")
        return False
