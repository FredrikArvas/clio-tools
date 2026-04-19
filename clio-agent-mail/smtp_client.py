"""
smtp_client.py — SMTP-sändning för clio-agent-mail

Skickar mail via SSL på port 465 (Misshosting).
Sparar kopia i IMAP Skickat-mappen efter varje skickat mail.
Stöder valfritt Message-ID (för att kunna spåra godkännandesvar).
"""
import imaplib
import smtplib
import logging
import socket
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# Tvinga IPv4 — mail.arvas.international har IPv6-poster men routrar saknar ofta IPv6-route
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if family == 0:
        family = socket.AF_INET
    return _orig_getaddrinfo(host, port, family, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo


def send_email(
    config,
    from_account_key: str,
    to_addr: str,
    subject: str,
    body: str,
    reply_to_message_id: str = None,
    message_id: str = None,
    cc_addrs: list = None,
    dry_run: bool = False,
    html_body: str = None,
    reply_to_addr: str = None,
):
    """
    Skickar ett mail via SMTP.

    from_account_key    : "clio" eller "info"
    to_addr             : mottagarens e-postadress
    subject             : ämnesrad
    body                : brödtext (plain text)
    reply_to_message_id : Message-ID på mail vi svarar på (sätter In-Reply-To)
    message_id          : eget Message-ID att sätta i headern (för approval-spårning)
    dry_run             : loggar utan att skicka
    """
    host = config.get("mail", "smtp_host")
    port = int(config.get("mail", "smtp_port"))
    user = config.get("mail", f"imap_user_{from_account_key}")
    password = config.get("mail", f"imap_password_{from_account_key}")

    msg = MIMEMultipart("alternative")
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject

    if message_id:
        msg["Message-ID"] = message_id
    if reply_to_addr:
        msg["Reply-To"] = reply_to_addr
    if reply_to_message_id:
        msg["In-Reply-To"] = reply_to_message_id
        msg["References"] = reply_to_message_id
    if cc_addrs:
        msg["CC"] = ", ".join(cc_addrs)

    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body if html_body else _to_html(body), "html", "utf-8"))

    if dry_run:
        cc_str = f", CC: {', '.join(cc_addrs)}" if cc_addrs else ""
        logger.info(f"[DRY-RUN] Skulle skicka: {user} → {to_addr}{cc_str} | {subject[:60]}")
        return

    raw_bytes = msg.as_bytes()
    all_recipients = [to_addr] + (cc_addrs or [])

    try:
        with smtplib.SMTP_SSL(host, port) as server:
            server.ehlo()
            server.login(user, password)
            server.sendmail(user, all_recipients, raw_bytes)
        logger.info(f"Mail skickat: {user} → {to_addr} | {subject[:60]}")
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP-autentiseringsfel för {from_account_key}: {e}")
        raise
    except Exception as e:
        logger.error(f"SMTP-fel: {e}")
        raise

    _append_to_sent(config, from_account_key, raw_bytes)


def _to_html(text: str) -> str:
    """Konverterar plain text till enkel HTML med bevarad struktur."""
    import html as html_lib
    lines = text.splitlines()
    out = ['<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#222;">']
    for line in lines:
        escaped = html_lib.escape(line)
        if set(line.strip()) <= {"─", "━", "-", "=", " "} and len(line.strip()) >= 8:
            out.append('<hr style="border:none;border-top:1px solid #ccc;margin:12px 0;">')
        elif escaped.startswith("&gt; "):
            out.append(
                f'<blockquote style="margin:0 0 0 12px;padding:0 0 0 10px;'
                f'border-left:3px solid #ccc;color:#555;">{escaped[5:]}</blockquote>'
            )
        elif escaped.startswith("&gt;"):
            out.append(
                f'<blockquote style="margin:0 0 0 12px;padding:0 0 0 10px;'
                f'border-left:3px solid #ccc;color:#555;">{escaped[4:]}</blockquote>'
            )
        elif escaped == "":
            out.append("<br>")
        else:
            out.append(f"<p style='margin:0 0 6px 0;'>{escaped}</p>")
    out.append("</div>")
    return "\n".join(out)


def _append_to_sent(config, account_key: str, raw_bytes: bytes):
    """Sparar en kopia av skickat mail i IMAP Skickat-mappen."""
    host = config.get("mail", "imap_host")
    imap_port = int(config.get("mail", "imap_port"))
    user = config.get("mail", f"imap_user_{account_key}")
    password = config.get("mail", f"imap_password_{account_key}")

    # Möjliga namn på Skickat-mappen — provar i ordning
    sent_candidates = ["Sent", "INBOX.Sent", "Sent Messages", "Skickat"]

    try:
        conn = imaplib.IMAP4_SSL(host, imap_port)
        conn.login(user, password)

        # Lista tillgängliga mappar för att hitta rätt Skickat-mapp
        _, folder_data = conn.list()
        folders = []
        for item in folder_data:
            if isinstance(item, bytes):
                parts = item.decode().split('"."')
                name = parts[-1].strip().strip('"')
                folders.append(name)

        sent_folder = None
        for candidate in sent_candidates:
            if any(candidate.lower() == f.lower() for f in folders):
                sent_folder = next(f for f in folders if f.lower() == candidate.lower())
                break

        if not sent_folder:
            logger.warning(f"[{account_key}] Skickat-mapp hittades inte bland: {folders}")
            conn.logout()
            return

        conn.append(
            sent_folder,
            r"\Seen",
            imaplib.Time2Internaldate(time.time()),
            raw_bytes,
        )
        logger.debug(f"[{account_key}] Kopia sparad i '{sent_folder}'")
        conn.logout()

    except Exception as e:
        logger.warning(f"[{account_key}] Kunde inte spara i Skickat: {e}")
