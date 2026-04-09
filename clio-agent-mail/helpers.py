"""
helpers.py — rena hjälpfunktioner för clio-agent-mail

Inga side effects, ingen smtp/state-import. Bara strängar, regex,
e-postparsing och config-uppslag. Får importeras av både main.py
och handlers.py utan risk för cirkulära beroenden.
"""
import re
import logging

logger = logging.getLogger("clio-mail")


# ── Strängar ──────────────────────────────────────────────────────────────────

def _extract_email(sender: str) -> str:
    match = re.search(r"<([^>]+)>", sender)
    return match.group(1).strip() if match else sender.strip()


def _short(text: str, n: int) -> str:
    return text[:n] if len(text) > n else text


def _quote_original(mail_item) -> str:
    """
    Returnerar ett citerat ursprungsmeddelande att bifoga under svaret.
    Max 60 rader av brödtexten — resten trunkeras.
    """
    sep = "─" * 40
    lines = (mail_item.body or "").splitlines()
    quoted = "\n".join(f"> {line}" for line in lines[:60])
    if len(lines) > 60:
        quoted += "\n> [...]"
    return (
        f"\n\n{sep}\n"
        f"Svara ovanför strecket\n"
        f"{sep}\n"
        f"Från: {mail_item.sender}\n"
        f"Ämne: {mail_item.subject}\n"
        f"Datum: {mail_item.date_received or ''}\n\n"
        f"{quoted}"
    )


def _get_plain_body(msg) -> str:
    """Extraherar text/plain-brödtext ur ett email.message-objekt."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return ""


# ── Config-uppslag ────────────────────────────────────────────────────────────

def _fredrik_addrs(config) -> set:
    """Returnerar set med admin-adresser (lowercase). Används för SELF_QUERY och CC-logik."""
    raw = config.get("mail", "admin_addresses", fallback="")
    addrs = {a.strip().lower() for a in raw.split(",") if a.strip()}
    # Fallback: notify_address om admin_addresses saknas i config
    if not addrs:
        arvas = config.get("mail", "notify_address",           fallback="").lower().strip()
        cap   = config.get("mail", "notify_address_capgemini", fallback="").lower().strip()
        addrs = {a for a in [arvas, cap] if a}
    return addrs


def _fredrik_in_recipients(mail_item, config) -> bool:
    """Sant om Fredrik finns i original To eller CC."""
    addrs = _fredrik_addrs(config)
    all_recipients = mail_item.to_addresses + mail_item.cc_addresses
    return bool(addrs & set(all_recipients))


def _resolve_fredrik_cc(mail_item, config) -> str | None:
    """
    Bestämmer om och med vilken adress Fredrik ska CC:as på svaret.

    Regler (i prioritetsordning):
      1. Fredrik finns redan i original CC/To → behåll den adressen
      2. Avsändaren är från capgemini.com → använd capgemini-adressen
      3. [CLIO-CC] i ämnesraden → använd arvas-adressen
      4. Annars → ingen CC

    Returnerar e-postadress som sträng eller None.
    """
    notify_arvas    = config.get("mail", "notify_address",            fallback="").lower().strip()
    notify_cap      = config.get("mail", "notify_address_capgemini",  fallback="").lower().strip()
    cc_enabled      = config.get("mail", "cc_if_original_recipient",  fallback="true").lower() == "true"

    all_recipients  = mail_item.to_addresses + mail_item.cc_addresses

    logger.debug(
        f"[cc-resolve] to={mail_item.to_addresses} cc={mail_item.cc_addresses} "
        f"notify_arvas='{notify_arvas}' notify_cap='{notify_cap}' cc_enabled={cc_enabled}"
    )

    if cc_enabled:
        # Fredrik var redan på kopia — behåll exakt den adressen
        if notify_cap and notify_cap in all_recipients:
            logger.debug(f"[cc-resolve] Matchar notify_cap → {notify_cap}")
            return notify_cap
        if notify_arvas and notify_arvas in all_recipients:
            logger.debug(f"[cc-resolve] Matchar notify_arvas → {notify_arvas}")
            return notify_arvas

    # Avsändarens domän avgör adress
    sender_email = _extract_email(mail_item.sender)
    if notify_cap and sender_email.endswith("@capgemini.com"):
        logger.debug(f"[cc-resolve] Capgemini-avsändare → {notify_cap}")
        return notify_cap

    # Explicit [CLIO-CC] i ämnesraden
    if "[CLIO-CC]" in (mail_item.subject or ""):
        logger.debug(f"[cc-resolve] [CLIO-CC] i ämnesrad → {notify_arvas}")
        return notify_arvas or None

    logger.debug(f"[cc-resolve] Ingen CC-match — returnerar None")
    return None


def _account_key_for(account: str, config) -> str:
    """
    Mappar mottagar-adress till account_key.
    Itererar över accounts-listan i config — returnerar första träff.
    Fallback: "clio".
    """
    accounts_raw = config.get("mail", "accounts", fallback="clio")
    account_keys = [a.strip() for a in accounts_raw.split(",") if a.strip()]
    account_lower = account.lower()
    for key in account_keys:
        user = config.get("mail", f"imap_user_{key}", fallback="").lower()
        if user and user in account_lower:
            return key
    return account_keys[0] if account_keys else "clio"
