"""
imap_client.py — IMAP-polling för clio-agent-mail

Hämtar olästa mail (UNSEEN) från ett konto och returnerar
dem som MailItem-objekt. Markerar inte som lästa — det hanteras
av state.py (vi trackar via message_id i SQLite).
"""
import imaplib
import email
import re
from datetime import datetime
from email.header import decode_header
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".xls", ".pptx",
    ".png", ".jpg", ".jpeg", ".gif",
    ".csv", ".txt", ".md",
}


@dataclass
class AttachmentMeta:
    filename: str
    filepath: str
    content_type: str


@dataclass
class MailItem:
    message_id: str
    account: str
    sender: str
    subject: str
    body: str
    date_received: str
    raw_uid: str
    to_addresses: List[str] = field(default_factory=list)
    cc_addresses: List[str] = field(default_factory=list)
    attachments: List[AttachmentMeta] = field(default_factory=list)


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _decode_str(value, encoding=None) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode(encoding or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError):
            return value.decode("latin-1", errors="replace")
    return value or ""


def _get_header(msg, header: str) -> str:
    raw = msg.get(header, "")
    parts = decode_header(raw)
    return "".join(_decode_str(part, enc) for part, enc in parts).strip()


def _extract_addresses(header_value: str) -> List[str]:
    """Extraherar alla e-postadresser ur en To/CC-header."""
    return [m.lower() for m in re.findall(r"[\w.+\-]+@[\w.\-]+", header_value)]


def _safe_filename(name: str) -> str:
    """Sanerar filnamn — tar bort tecken som är ogiltiga i Windows-sökvägar."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:200] or "bilaga"


def _folder_name(msg, date_prefix: str, short_id: str = "") -> str:
    """
    Bygger ett läsbart mappnamn: {datum}_{avsändar-lokal}_{ämne-slug}_{short_id}
    Exempel: 2026-04-08_carl.lindell_Analys-av-enkätundersökning_3f9a2b1c8d4e
    short_id används för säker rekonstruktion av bilagor från databasen.
    """
    # Avsändarens lokala del (före @)
    from_raw = msg.get("From", "")
    decoded_parts = decode_header(from_raw)
    from_str = "".join(
        p.decode(e or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, e in decoded_parts
    )
    addr_match = re.search(r"[\w.+\-]+@", from_str)
    sender_local = addr_match.group(0).rstrip("@")[:20] if addr_match else "okand"
    sender_local = re.sub(r"[^a-zA-Z0-9åäöÅÄÖ.\-]", "", sender_local)

    # Ämne — ta bort Re:/Sv:/Fwd:-prefix, slug-ify
    subject_raw = msg.get("Subject", "")
    decoded_s = decode_header(subject_raw)
    subject = "".join(
        p.decode(e or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, e in decoded_s
    )
    subject = re.sub(r"^(Re|Sv|Fwd|VS|VB|AW)\s*:\s*", "", subject, flags=re.IGNORECASE).strip()
    subject_slug = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", subject)
    subject_slug = re.sub(r"\s+", "-", subject_slug)[:30].strip("-")

    base = f"{date_prefix}_{sender_local}"
    if subject_slug:
        base = f"{base}_{subject_slug}"
    if short_id:
        base = f"{base}_{short_id}"
    return base


def _save_attachments(msg, attachments_dir: Path, message_id: str) -> List[AttachmentMeta]:
    """
    Extraherar och sparar bilagor från ett e-postmeddelande.
    Skapar undermapp: attachments_dir / {datum}_{avsändar-lokal}_{ämne-slug}/
    """
    saved = []
    if not msg.is_multipart():
        return saved

    date_prefix = datetime.now().strftime("%Y-%m-%d")
    short_id = re.sub(r"[^a-zA-Z0-9]", "", message_id)[-12:]
    base_name = _folder_name(msg, date_prefix, short_id=short_id)

    # Räknare vid namnkrock på mappnivå
    folder = attachments_dir / base_name
    counter = 2
    while folder.exists() and any(folder.iterdir()):
        folder = attachments_dir / f"{base_name}_{counter}"
        counter += 1

    for part in msg.walk():
        disposition = str(part.get("Content-Disposition", ""))
        content_type = part.get_content_type()

        # Hämta filnamn
        filename = part.get_filename()
        if not filename:
            continue  # inte en bilaga

        # Avkoda filnamn om det är MIME-kodat
        decoded_parts = decode_header(filename)
        filename = "".join(
            p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
            for p, enc in decoded_parts
        )
        filename = _safe_filename(filename)

        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            logger.debug(f"[bilagor] Skippar ej stöddt format: {filename}")
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        folder.mkdir(parents=True, exist_ok=True)
        filepath = folder / filename

        # Undvik namnkollisioner
        counter = 1
        while filepath.exists():
            filepath = folder / f"{filepath.stem}_{counter}{filepath.suffix}"
            counter += 1

        filepath.write_bytes(payload)
        saved.append(AttachmentMeta(
            filename=filename,
            filepath=str(filepath),
            content_type=content_type,
        ))
        logger.info(f"[bilagor] Sparad: {filepath}")

    return saved


def _get_body(msg) -> str:
    """Extraherar text/plain-brödtext, hanterar multipart."""
    if msg.is_multipart():
        for part in msg.walk():
            if (part.get_content_type() == "text/plain"
                    and "attachment" not in str(part.get("Content-Disposition", ""))):
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace").strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace").strip()
    return ""


# ── Publik API ────────────────────────────────────────────────────────────────

def fetch_unseen(config, account_key: str) -> list:
    """
    Hämtar olästa mail från ett IMAP-konto.

    account_key : "clio" eller "info"
    Returnerar  : lista av MailItem (med attachments sparade till disk)
    """
    host = config.get("mail", "imap_host")
    port = int(config.get("mail", "imap_port"))
    user = config.get("mail", f"imap_user_{account_key}")
    password = config.get("mail", f"imap_password_{account_key}")

    _raw_attachments = config.get("mail", "attachments_dir", fallback="attachments")
    attachments_dir = Path(_raw_attachments)
    if not attachments_dir.is_absolute():
        attachments_dir = Path(__file__).parent / attachments_dir

    timeout = int(config.get("mail", "imap_timeout_seconds", fallback="30"))

    items = []
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=timeout)
        conn.login(user, password)
        conn.select("INBOX")

        _, data = conn.uid("search", None, "UNSEEN")
        uid_list = data[0].split() if data[0] else []

        for uid in uid_list:
            try:
                _, msg_data = conn.uid("fetch", uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                message_id = msg.get(
                    "Message-ID",
                    f"uid-{uid.decode()}-{user}"
                ).strip()

                saved_attachments = _save_attachments(msg, attachments_dir, message_id)

                items.append(MailItem(
                    message_id=message_id,
                    account=user,
                    sender=_get_header(msg, "From"),
                    subject=_get_header(msg, "Subject"),
                    body=_get_body(msg),
                    date_received=_get_header(msg, "Date"),
                    raw_uid=uid.decode(),
                    to_addresses=_extract_addresses(_get_header(msg, "To")),
                    cc_addresses=_extract_addresses(_get_header(msg, "CC")),
                    attachments=saved_attachments,
                ))
            except Exception as e:
                logger.error(f"[{account_key}] Fel vid parsning av UID {uid}: {e}")

        conn.logout()

    except imaplib.IMAP4.error as e:
        logger.error(f"[{account_key}] IMAP-autentiseringsfel: {e}")
    except Exception as e:
        logger.error(f"[{account_key}] IMAP-anslutningsfel: {e}")

    return items
