"""
classifier.py — regelmotor för clio-agent-mail

Klassificerar inkommande mail baserat på:
  - konto (clio@ / info@)
  - avsändare (vitlistad / ej vitlistad)
  - ämneskod ([CLIO-AUTO] / [CLIO-DRAFT] / ingen)

Säkerhetsmodell: vitlista + ämneskod är två oberoende lager.
En ej vitlistad avsändare med rätt ämneskod får ändå bara standardsvar.
"""
import re
from dataclasses import dataclass

from clio_core.utils import t, set_language

CODE_AUTO  = "[CLIO-AUTO]"
CODE_DRAFT = "[CLIO-DRAFT]"
CODE_OBIT  = "[clio-obit]"   # case-insensitive match used below

ACTION_AUTO_SEND         = "AUTO_SEND"
ACTION_SEND_FOR_APPROVAL = "SEND_FOR_APPROVAL"
ACTION_STANDARD_REPLY    = "STANDARD_REPLY"
ACTION_FAQ_CHECK         = "FAQ_CHECK"
ACTION_SELF_QUERY        = "SELF_QUERY"
ACTION_OBIT_IMPORT       = "OBIT_IMPORT"   # Sprint 3: returned watch-list CSV


@dataclass
class Classification:
    action: str
    reason: str
    account_key: str  # "clio" eller "info"


def extract_sender_email(sender: str) -> str:
    """Extraherar e-postadress ur 'Visningsnamn <adress>' eller bara 'adress'."""
    match = re.search(r"<([^>]+)>", sender)
    if match:
        return match.group(1).strip().lower()
    return sender.strip().lower()


def _resolve_account_key(account: str, config) -> str:
    """Mappar mottagar-adress till account_key via accounts-listan i config."""
    accounts_raw = config.get("mail", "accounts", fallback="clio")
    account_keys = [a.strip() for a in accounts_raw.split(",") if a.strip()]
    account_lower = account.lower()
    for key in account_keys:
        user = config.get("mail", f"imap_user_{key}", fallback="").lower()
        if user and user in account_lower:
            return key
    return account_keys[0] if account_keys else "clio"


def _get_permission(sender_email: str, account_key: str, config) -> str:
    """
    Slår upp avsändarens behörighetsnivå för det aktuella kontot via clio-access.
    Returnerar: "admin" | "write" | "coded" | "whitelisted" | "denied"
    """
    import sys
    from pathlib import Path
    # Lägg till clio-access i sys.path om det inte redan finns
    _access_path = str(Path(__file__).parent.parent)
    if _access_path not in sys.path:
        sys.path.insert(0, _access_path)

    from clio_access import AccessManager
    am = AccessManager.from_config(config)
    return am.get_level({"email": sender_email}, scope=account_key)


def classify(mail_item, whitelist: set, config) -> Classification:
    """
    Regelmotor — returnerar Classification med action, reason och account_key.

    mail_item : MailItem
    whitelist : set av lowercase e-postadresser
    config    : ConfigParser med [mail]-sektion

    Behörighetsmodell (Sprint 2):
      admin   → SELF_QUERY (alla kommandon, alla konton)
      write   → SELF_QUERY på tillåtna konton
      coded   → AUTO_SEND med kontextmedveten flagg
      övriga  → vitlista-first som tidigare
    """
    info_account = config.get("mail", "imap_user_info", fallback="").lower()
    account = mail_item.account.lower()
    account_key = _resolve_account_key(account, config)
    sender_email = extract_sender_email(mail_item.sender)

    # ── info@ → FAQ-flöde (före behörighetscheck) ────────────────────────────
    if info_account and account == info_account:
        return Classification(
            action=ACTION_FAQ_CHECK,
            reason=t("mail_reason_faq"),
            account_key="info",
        )

    # ── [clio-obit] — prioriteras före behörighetscheck (gäller alla avsändare) ──
    subject_early = mail_item.subject or ""
    if CODE_OBIT.lower() in subject_early.lower():
        obit_attached = any(
            getattr(a, "filename", "").lower().endswith((".csv", ".xlsx"))
            for a in getattr(mail_item, "attachments", [])
        )
        if obit_attached:
            return Classification(
                action=ACTION_OBIT_IMPORT,
                reason="[clio-obit] subject with watchlist attachment",
                account_key=account_key,
            )

    # ── Behörighetscheck ─────────────────────────────────────────────────────
    perm = _get_permission(sender_email, account_key, config)

    if perm in ("admin", "write"):
        return Classification(
            action=ACTION_SELF_QUERY,
            reason=f"Permission: {perm}",
            account_key=account_key,
        )

    if perm == "coded":
        # Kontextmedveten: behandlas som vitlistad men får #kodord-resolving
        # (handlers._handle_auto_send injicerar NCC via get_knowledge_context)
        return Classification(
            action=ACTION_AUTO_SEND,
            reason="Permission: coded",
            account_key=account_key,
        )

    # ── Vitlista-first för övriga ────────────────────────────────────────────
    if sender_email not in whitelist:
        return Classification(
            action=ACTION_STANDARD_REPLY,
            reason=t("mail_reason_not_whitelisted", sender=sender_email),
            account_key=account_key,
        )

    subject = mail_item.subject or ""

    if CODE_DRAFT in subject:
        return Classification(
            action=ACTION_SEND_FOR_APPROVAL,
            reason=t("mail_reason_draft", code=CODE_DRAFT),
            account_key=account_key,
        )

    # [clio-obit] + CSV attachment → watchlist import
    if CODE_OBIT.lower() in subject.lower():
        csv_attached = any(
            getattr(a, "filename", "").lower().endswith(".csv")
            for a in getattr(mail_item, "attachments", [])
        )
        if csv_attached:
            return Classification(
                action=ACTION_OBIT_IMPORT,
                reason="[clio-obit] subject with CSV attachment",
                account_key=account_key,
            )

    return Classification(
        action=ACTION_AUTO_SEND,
        reason=t("mail_reason_auto"),
        account_key=account_key,
    )
