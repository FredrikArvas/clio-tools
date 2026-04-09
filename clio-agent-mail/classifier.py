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
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clio-tools" / "config"))
from clio_utils import t, set_language

CODE_AUTO = "[CLIO-AUTO]"
CODE_DRAFT = "[CLIO-DRAFT]"

ACTION_AUTO_SEND = "AUTO_SEND"
ACTION_SEND_FOR_APPROVAL = "SEND_FOR_APPROVAL"
ACTION_STANDARD_REPLY = "STANDARD_REPLY"
ACTION_FAQ_CHECK = "FAQ_CHECK"


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


def classify(mail_item, whitelist: set, config) -> Classification:
    """
    Regelmotor — returnerar Classification med action, reason och account_key.

    mail_item : MailItem
    whitelist : set av lowercase e-postadresser (gäller enbart clio@)
    config    : ConfigParser med [mail]-sektion
    """
    clio_account = config.get("mail", "imap_user_clio").lower()
    info_account = config.get("mail", "imap_user_info").lower()
    account = mail_item.account.lower()

    # ── info@ ────────────────────────────────────────────────────────────────
    if account == info_account:
        return Classification(
            action=ACTION_FAQ_CHECK,
            reason=t("mail_reason_faq"),
            account_key="info",
        )

    # ── clio@ ────────────────────────────────────────────────────────────────
    if account == clio_account:
        sender_email = extract_sender_email(mail_item.sender)

        if sender_email not in whitelist:
            return Classification(
                action=ACTION_STANDARD_REPLY,
                reason=t("mail_reason_not_whitelisted", sender=sender_email),
                account_key="clio",
            )

        subject = mail_item.subject or ""

        if CODE_DRAFT in subject:
            return Classification(
                action=ACTION_SEND_FOR_APPROVAL,
                reason=t("mail_reason_draft", code=CODE_DRAFT),
                account_key="clio",
            )

        # Vitlistad avsändare → AUTO_SEND oavsett ämneskod
        # [CLIO-AUTO] i ämnesraden är frivilligt men stöds fortfarande
        return Classification(
            action=ACTION_AUTO_SEND,
            reason=t("mail_reason_auto"),
            account_key="clio",
        )

    # ── Okänt konto — säker fallback ─────────────────────────────────────────
    return Classification(
        action=ACTION_STANDARD_REPLY,
        reason=t("mail_reason_unknown_account", account=account),
        account_key="clio",
    )
