"""
clio_core.mail — delad mail-utility med tjänst-fallback

Försöker skicka via clio-agent-mails HTTP-tjänst (POST /send).
Faller tillbaka på direkt SMTP om tjänsten inte svarar.

Miljövariabler (root .env per maskin):
  CLIO_MAIL_SERVICE_URL  — URL till mail-tjänsten (default http://127.0.0.1:7100)
  SMTP_HOST              — SMTP-server (default mail.arvas.international)
  SMTP_PORT              — SMTP-port SSL (default 465)
  SMTP_USER              — Avsändaradress (default clio@arvas.international)
  SMTP_PASSWORD          — Lösenord för direkt SMTP-fallback
"""

import json
import logging
import os
import smtplib
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_SERVICE_URL = os.getenv("CLIO_MAIL_SERVICE_URL", "http://127.0.0.1:7100")
_SMTP_HOST   = os.getenv("SMTP_HOST",     "mail.arvas.international")
_SMTP_PORT   = int(os.getenv("SMTP_PORT", "465"))
_SMTP_USER   = os.getenv("SMTP_USER",     "clio@arvas.international")
_SMTP_PASS   = os.getenv("SMTP_PASSWORD", "")


def send(to: str, subject: str, body: str, html: str = None) -> bool:
    """Skickar mail via agent-tjänst om tillgänglig, annars direkt SMTP."""
    if _try_service(to, subject, body, html):
        return True
    logger.info("Mail-tjänst ej nåbar — faller tillbaka på direkt SMTP")
    return _send_smtp(to, subject, body, html)


def _try_service(to: str, subject: str, body: str, html) -> bool:
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
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                logger.info(f"Mail skickat via tjänst: → {to} | {subject[:60]}")
                return True
            logger.warning(f"Mail-tjänst svarade {resp.status}")
            return False
    except Exception as e:
        logger.debug(f"Mail-tjänst ej nåbar: {e}")
        return False


def _send_smtp(to: str, subject: str, body: str, html: str = None) -> bool:
    if not _SMTP_PASS:
        logger.error("SMTP_PASSWORD saknas i .env — kan inte skicka direkt")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"]    = _SMTP_USER
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html or _plain_to_html(body), "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT) as server:
            server.login(_SMTP_USER, _SMTP_PASS)
            server.sendmail(_SMTP_USER, [to], msg.as_bytes())
        logger.info(f"Mail skickat direkt via SMTP: → {to} | {subject[:60]}")
        return True
    except Exception as e:
        logger.error(f"Direkt SMTP-fel: {e}")
        return False


def _plain_to_html(text: str) -> str:
    import html
    lines = text.splitlines()
    parts = ['<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5;">']
    for line in lines:
        esc = html.escape(line)
        if not esc:
            parts.append("<br>")
        else:
            parts.append(f"<p style='margin:0 0 6px 0;'>{esc}</p>")
    parts.append("</div>")
    return "\n".join(parts)
