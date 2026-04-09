"""
approval.py — godkännandeflöde via mail för clio-agent-mail

Flöde:
  1. Clio skickar ett godkännandemail till Fredrik med draft + original
  2. Fredrik svarar med JA eller NEJ (på en egen rad)
  3. Nästa poll-cykel anropar check_approvals() som:
     - Söker i clio@-inkorgen efter svar med rätt In-Reply-To-header
     - Verifierar att avsändaren är Fredriks adress
     - Agerar på JA (skicka) eller NEJ (avbryt)

Sprint 1: Fredrik kan bara svara JA/NEJ, inte redigera utkastet.
"""
import imaplib
import email as email_lib
import re
import logging
from email.header import decode_header

import state
import smtp_client

logger = logging.getLogger(__name__)


# ── Bygg godkännandemail ──────────────────────────────────────────────────────

def build_approval_request(original_mail, draft: str, config) -> tuple:
    """
    Bygger ämne och brödtext för godkännandemail till Fredrik.
    Returnerar (subject, body).
    """
    yes_kw = config.get("mail", "approval_keyword_yes", fallback="JA")
    no_kw = config.get("mail", "approval_keyword_no", fallback="NEJ")

    subject = f"[CLIO-GODKÄNN] Svar till {_short(original_mail.sender, 50)}"

    separator = "━" * 40

    body = (
        f"Hej Fredrik,\n\n"
        f"Clio har mottagit ett mail och föreslår följande svar.\n"
        f"Svara på detta mail med {yes_kw} för att skicka, eller {no_kw} för att avbryta.\n\n"
        f"{separator}\n"
        f"URSPRUNGSMAIL\n"
        f"{separator}\n"
        f"Från:  {original_mail.sender}\n"
        f"Ämne:  {original_mail.subject}\n"
        f"Konto: {original_mail.account}\n\n"
        f"{original_mail.body[:2000]}"
        f"{'...' if len(original_mail.body) > 2000 else ''}\n\n"
        f"{separator}\n"
        f"CLIOS FÖRESLAGNA SVAR\n"
        f"{separator}\n"
        f"{draft}\n\n"
        f"{separator}\n"
        f"Svara med:\n"
        f"  {yes_kw}  — skicka svaret\n"
        f"  {no_kw}  — avbryt\n\n"
        f"/Clio"
    )
    return subject, body


# ── Kontrollera godkännandesvar ───────────────────────────────────────────────

def check_approvals(config, smtp_send_fn, dry_run: bool = False):
    """
    Kontrollerar om Fredrik svarat JA/NEJ på väntande godkännanden.

    Anropas i slutet av varje poll-cykel.
    Läser pending approvals från state.py och söker i IMAP efter svar.
    """
    yes_kw = config.get("mail", "approval_keyword_yes", fallback="JA").upper()
    no_kw = config.get("mail", "approval_keyword_no", fallback="NEJ").upper()

    pending = state.get_pending_approvals()
    if not pending:
        return

    logger.info(f"{len(pending)} väntande godkännanden kontrolleras")

    for row in pending:
        approval_id = row["id"]
        original_message_id = row["message_id"]
        draft = row["draft"]
        account = row["account"]
        sender = row["sender"]
        subject = row["subject"]
        approval_message_id = row["approval_message_id"]

        if not approval_message_id:
            logger.warning(f"Godkännande {approval_id} saknar approval_message_id — hoppar över")
            continue

        response = _find_response(config, approval_message_id, yes_kw, no_kw)

        if response is None:
            logger.debug(f"Inget svar ännu för godkännande {approval_id}")
            continue

        state.record_approval_response(approval_id, response)

        if response == yes_kw:
            fredrik_cc = row["fredrik_cc"] or None
            logger.info(f"Godkänt av Fredrik — skickar svar till {_short(sender, 40)}"
                        + (f" (CC: {fredrik_cc})" if fredrik_cc else ""))
            account_key = _account_key(account, config)
            quoted = _quote_original_from_row(row)
            if not dry_run:
                smtp_send_fn(
                    from_account_key=account_key,
                    to_addr=_extract_email(sender),
                    subject=f"Re: {subject}",
                    body=draft + quoted,
                    reply_to_message_id=original_message_id,
                    cc_addrs=[fredrik_cc] if fredrik_cc else None,
                )
            state.update_status(original_message_id, state.STATUS_SENT)
            state.save_learned_reply(
                original_subject=row["subject"],
                original_body=row["body"],
                original_sender=row["sender"],
                approved_reply=draft,
            )
            logger.info(f"Läroexempel sparat: '{_short(subject, 50)}'")

        elif response == no_kw:
            logger.info(f"Avbrutet av Fredrik för mail från {_short(sender, 40)}")
            state.update_status(original_message_id, state.STATUS_REJECTED)


# ── IMAP-sökning efter godkännandesvar ────────────────────────────────────────

def _find_response(config, approval_message_id: str, yes_kw: str, no_kw: str):
    """
    Söker i clio@-inkorgen efter Fredriks svar på ett godkännandemail.

    Matchar på In-Reply-To: <approval_message_id> och verifierar avsändare.
    Returnerar yes_kw, no_kw eller None.
    """
    host = config.get("mail", "imap_host")
    port = int(config.get("mail", "imap_port"))
    user = config.get("mail", "imap_user_clio")
    password = config.get("mail", "imap_password_clio")
    notify_addr = config.get("mail", "notify_address").lower()

    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(user, password)
        conn.select("INBOX")

        # Sök efter mail med rätt In-Reply-To-header
        search_id = approval_message_id.strip()
        _, data = conn.uid("search", None, f'HEADER In-Reply-To "{search_id}"')
        uids = data[0].split() if data[0] else []

        for uid in uids:
            _, msg_data = conn.uid("fetch", uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)

            from_addr = _decode_header_str(msg.get("From", "")).lower()
            if notify_addr not in from_addr:
                logger.debug(f"Ignorerar svar från okänd avsändare: {from_addr}")
                continue

            body = _get_plain_body(msg).strip().upper()

            for line in body.splitlines():
                line = line.strip()
                if line == yes_kw:
                    conn.logout()
                    return yes_kw
                if line == no_kw:
                    conn.logout()
                    return no_kw

        conn.logout()

    except Exception as e:
        logger.error(f"Fel vid sökning av godkännandesvar: {e}")

    return None


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _quote_original_from_row(row) -> str:
    """Citerar ursprungsmeddelandet utifrån en approvals-databasrad."""
    sep = "─" * 40
    body = row["body"] or ""
    lines = body.splitlines()
    quoted = "\n".join(f"> {line}" for line in lines[:60])
    if len(lines) > 60:
        quoted += "\n> [...]"
    return (
        f"\n\n{sep}\n"
        f"Svara ovanför strecket\n"
        f"{sep}\n"
        f"Från: {row['sender']}\n"
        f"Ämne: {row['subject']}\n\n"
        f"{quoted}"
    )


def _extract_email(sender: str) -> str:
    match = re.search(r"<([^>]+)>", sender)
    return match.group(1).strip() if match else sender.strip()


def _account_key(account: str, config) -> str:
    if config.get("mail", "imap_user_clio").lower() in account.lower():
        return "clio"
    return "info"


def _short(text: str, n: int) -> str:
    return text[:n] if len(text) > n else text


def _decode_header_str(value: str) -> str:
    parts = decode_header(value)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _get_plain_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""
