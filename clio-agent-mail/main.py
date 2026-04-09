"""
main.py — huvudloop för clio-agent-mail

Startar IMAP-polling och kör ett pass per konfigurerat intervall.
Kan köras som systemd-tjänst eller anropas direkt av agent.

Flaggor:
  --dry-run   Kör hela flödet utan att skicka mail eller skriva till databasen
  --once      Kör ett enda poll-pass och avsluta (agent-ready / CI-testning)

Publikt API (agent-ready):
  main(argv=None)   — startar loop eller kör --once/--dry-run
  poll_once(config) — hämtar nya mail från båda konton
"""
import argparse
import configparser
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
ROOT_DIR = BASE_DIR.parent

# Ladda root-.env först (ANTHROPIC_API_KEY, NOTION_API_KEY)
# sedan modul-.env (IMAP_PASSWORD_CLIO, IMAP_PASSWORD_INFO) — override=True
# så att modul-specifika värden vinner om samma nyckel skulle finnas i båda.
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env", override=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clio-tools" / "config"))
from clio_utils import t, set_language

import state
import classifier
import imap_client
import smtp_client
import notion_data as notion_client
import faq as faq_module
import reply as reply_module
import approval as approval_module

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("clio-mail")


# ── Konfiguration ─────────────────────────────────────────────────────────────

def load_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config_path = BASE_DIR / "clio.config"
    if not config_path.exists():
        raise FileNotFoundError(t("mail_config_missing", path=config_path))
    config.read(str(config_path), encoding="utf-8")

    # Injicera lösenord från miljövariabler (skrivs aldrig i clio.config)
    if config.has_section("mail"):
        for key in ("imap_password_clio", "imap_password_info"):
            val = os.environ.get(key.upper())
            if val:
                config.set("mail", key, val)
    return config


# ── Publik API ────────────────────────────────────────────────────────────────

def poll_once(config) -> list:
    """
    Hämtar nya mail från båda IMAP-konton.
    Returnerar lista av MailItem.
    """
    items = []
    for account_key in ("clio", "info"):
        password = config.get("mail", f"imap_password_{account_key}", fallback="").strip()
        if not password:
            logger.debug(t("mail_no_password", account=account_key))
            continue
        try:
            fetched = imap_client.fetch_unseen(config, account_key)
            logger.info(t("mail_fetched", account=account_key, n=len(fetched)))
            items.extend(fetched)
        except Exception as e:
            logger.error(t("mail_polling_failed", account=account_key, error=e))
    return items


# ── Mailhantering ─────────────────────────────────────────────────────────────

_INTERNAL_TAGS = {"[CLIO-FLAGGAD]", "[CLIO-KOPIA]", "[CLIO-INFO]"}


def process_mail(mail_item, config, dry_run: bool = False):
    """Klassificerar och hanterar ett inkommande mail."""
    if state.is_seen(mail_item.message_id):
        logger.debug(f"Redan sett: {mail_item.message_id}")
        return

    subject = mail_item.subject or ""
    if any(tag in subject for tag in _INTERNAL_TAGS):
        logger.warning(t("mail_skip_internal", subject=subject[:80]))
        return

    whitelist_page = config.get("mail", "whitelist_notion_page_id")
    whitelist = notion_client.get_whitelist(whitelist_page)
    clf = classifier.classify(mail_item, whitelist, config)

    logger.info(t("mail_classified", account=clf.account_key,
                  sender=_short(mail_item.sender, 40), action=clf.action, reason=clf.reason))

    if not dry_run:
        state.save_mail(
            message_id=mail_item.message_id,
            account=mail_item.account,
            sender=mail_item.sender,
            subject=mail_item.subject,
            body=mail_item.body,
            date_received=mail_item.date_received,
            status=state.STATUS_NEW,
            action=clf.action,
        )

    try:
        if clf.action == classifier.ACTION_FAQ_CHECK:
            _handle_faq(mail_item, clf, config, dry_run)

        elif clf.action == classifier.ACTION_AUTO_SEND:
            _handle_auto_send(mail_item, clf, config, dry_run)

        elif clf.action == classifier.ACTION_SEND_FOR_APPROVAL:
            _handle_approval(mail_item, clf, config, dry_run)

        elif clf.action == classifier.ACTION_STANDARD_REPLY:
            _handle_standard(mail_item, clf, config, dry_run)

    except Exception as e:
        logger.error(t("mail_handle_error", message_id=mail_item.message_id, error=e), exc_info=True)


def _handle_faq(mail_item, clf, config, dry_run: bool):
    faq_page = config.get("mail", "faq_notion_page_id")
    faq_items = notion_client.get_faq(faq_page)
    match = faq_module.match_faq(mail_item, faq_items, config)

    if match.confidence == faq_module.CONFIDENCE_HIGH:
        reply_text = faq_module.generate_faq_reply(mail_item, match, config)
        logger.info(t("mail_faq_generated", match=_short(match.question, 40)))
        if not dry_run:
            smtp_client.send_email(
                config=config,
                from_account_key="info",
                to_addr=_extract_email(mail_item.sender),
                subject=f"Re: {mail_item.subject}",
                body=reply_text + _quote_original(mail_item),
                reply_to_message_id=mail_item.message_id,
            )
            _send_copy(mail_item, reply_text, "FAQ-svar skickat autonomt", config)
            state.update_status(mail_item.message_id, state.STATUS_SENT)

    else:
        holding = faq_module.generate_holding_reply(mail_item, config)
        logger.info(t("mail_holding_generated", confidence=match.confidence))
        if not dry_run:
            smtp_client.send_email(
                config=config,
                from_account_key="info",
                to_addr=_extract_email(mail_item.sender),
                subject=f"Re: {mail_item.subject}",
                body=holding + _quote_original(mail_item),
                reply_to_message_id=mail_item.message_id,
            )
            _send_info_to_fredrik(
                mail_item, holding,
                f"Låg FAQ-konfidens ({match.confidence}): {match.explanation}",
                config,
            )
            state.update_status(mail_item.message_id, state.STATUS_SENT)


def _handle_auto_send(mail_item, clf, config, dry_run: bool):
    context = (
        "Detta är ett [CLIO-AUTO]-mail. "
        "Avsändaren är vitlistad och förväntar sig ett direkt svar utan mänsklig granskning."
    )
    knowledge = notion_client.get_knowledge_context(
        config, mail_subject=mail_item.subject, mail_body=mail_item.body
    )
    examples = state.get_learned_replies(limit=5)
    reply_text = reply_module.generate_reply(
        mail_item, context, config, knowledge=knowledge, examples=examples
    )
    fredrik_cc = _resolve_fredrik_cc(mail_item, config)
    if fredrik_cc:
        logger.info(t("mail_auto_generated_cc", sender=_short(mail_item.sender, 40), cc=fredrik_cc))
    else:
        logger.info(t("mail_auto_generated", sender=_short(mail_item.sender, 40)))
    if not dry_run:
        smtp_client.send_email(
            config=config,
            from_account_key="clio",
            to_addr=_extract_email(mail_item.sender),
            subject=f"Re: {mail_item.subject}",
            body=reply_text + _quote_original(mail_item),
            reply_to_message_id=mail_item.message_id,
            cc_addrs=[fredrik_cc] if fredrik_cc else None,
        )
        _send_copy(mail_item, reply_text, "AUTO-svar skickat", config)
        state.update_status(mail_item.message_id, state.STATUS_SENT)


def _handle_approval(mail_item, clf, config, dry_run: bool):
    context = (
        "Skriv ett genomarbetat utkast. "
        "En människa (Fredrik) kommer att granska det innan det skickas."
    )
    knowledge = notion_client.get_knowledge_context(
        config, mail_subject=mail_item.subject, mail_body=mail_item.body
    )
    examples = state.get_learned_replies(limit=5)
    draft = reply_module.generate_reply(
        mail_item, context, config, knowledge=knowledge, examples=examples
    )
    appr_subject, appr_body = approval_module.build_approval_request(
        mail_item, draft, config
    )
    notify_addr = config.get("mail", "notify_address")
    approval_msg_id = f"<clio-approval-{uuid.uuid4()}@arvas.international>"

    fredrik_cc = _resolve_fredrik_cc(mail_item, config)
    if fredrik_cc:
        logger.info(t("mail_draft_generated_cc", sender=_short(mail_item.sender, 40), cc=fredrik_cc))
    else:
        logger.info(t("mail_draft_generated", sender=_short(mail_item.sender, 40)))
    if not dry_run:
        smtp_client.send_email(
            config=config,
            from_account_key="clio",
            to_addr=notify_addr,
            subject=appr_subject,
            body=appr_body,
            message_id=approval_msg_id,
        )
        mail_id = state.get_mail_id(mail_item.message_id)
        if mail_id:
            state.save_approval(
                mail_id=mail_id,
                draft=draft,
                approval_message_id=approval_msg_id,
                fredrik_cc=fredrik_cc,
            )
        state.update_status(mail_item.message_id, state.STATUS_PENDING)


def _handle_standard(mail_item, clf, config, dry_run: bool):
    sender_email = _extract_email(mail_item.sender)
    if state.is_blacklisted(sender_email):
        logger.info(t("mail_blacklisted", sender=sender_email))
        state.update_status(mail_item.message_id, state.STATUS_FLAGGED)
        return

    std_reply = reply_module.generate_standard_reply(mail_item, config)
    account_key = clf.account_key
    logger.info(t("mail_standard_generated", sender=_short(mail_item.sender, 40)))
    if not dry_run:
        smtp_client.send_email(
            config=config,
            from_account_key=account_key,
            to_addr=sender_email,
            subject=f"Re: {mail_item.subject}",
            body=std_reply + _quote_original(mail_item),
            reply_to_message_id=mail_item.message_id,
        )
        notif_msg_id = _send_flagged_notification(mail_item, config)
        mail_id = state.get_mail_id(mail_item.message_id)
        if mail_id and notif_msg_id:
            state.save_flagged_notification(mail_id, notif_msg_id, sender_email)
        state.update_status(mail_item.message_id, state.STATUS_FLAGGED)


# ── Citathjälpare ────────────────────────────────────────────────────────────

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


# ── Notifieringshjälpare ──────────────────────────────────────────────────────

def _send_copy(mail_item, reply_text: str, label: str, config):
    """Kopia av skickat svar till Fredrik (ingen JA/NEJ krävs)."""
    notify_addr = config.get("mail", "notify_address")
    smtp_client.send_email(
        config=config,
        from_account_key="clio",
        to_addr=notify_addr,
        subject=f"[CLIO-KOPIA] {label}: {_short(mail_item.subject, 50)}",
        body=(
            f"Clio skickade följande svar automatiskt.\n\n"
            f"Till: {mail_item.sender}\n"
            f"Originalämne: {mail_item.subject}\n\n"
            f"{reply_text}"
        ),
    )


def _send_info_to_fredrik(mail_item, draft: str, label: str, config):
    """Informationsmail till Fredrik om holding-svar (ingen JA/NEJ)."""
    notify_addr = config.get("mail", "notify_address")
    smtp_client.send_email(
        config=config,
        from_account_key="info",
        to_addr=notify_addr,
        subject=f"[CLIO-INFO] {_short(label, 50)}: {_short(mail_item.subject, 40)}",
        body=(
            f"Clio skickade ett holding-svar. Detaljer nedan.\n\n"
            f"Från: {mail_item.sender}\n"
            f"Ämne: {mail_item.subject}\n"
            f"Anledning: {label}\n\n"
            f"Skickat svar:\n{draft}"
        ),
    )


def _send_flagged_notification(mail_item, config) -> str:
    """
    Notifiering till Fredrik om flaggat mail (ej vitlistad avsändare).
    Returnerar det genererade Message-ID:t för uppföljning.
    """
    notify_addr = config.get("mail", "notify_address")
    wl_kw  = config.get("mail", "whitelist_keyword",  fallback="VITLISTA")
    bl_kw  = config.get("mail", "blacklist_keyword",  fallback="SVARTLISTA")
    kp_kw  = config.get("mail", "keep_keyword",       fallback="BEHÅLL")
    notif_msg_id = f"<flagged-{uuid.uuid4()}@clio.arvas.international>"
    sender_email = _extract_email(mail_item.sender)
    sep = "━" * 40
    smtp_client.send_email(
        config=config,
        from_account_key="clio",
        to_addr=notify_addr,
        subject=f"[CLIO-FLAGGAD] Okänd avsändare: {_short(mail_item.sender, 50)}",
        message_id=notif_msg_id,
        body=(
            f"Clio fick ett mail från en ej vitlistad avsändare och skickade standardsvar.\n\n"
            f"{sep}\n"
            f"Från:  {mail_item.sender}\n"
            f"Ämne:  {mail_item.subject}\n"
            f"{sep}\n\n"
            f"{mail_item.body[:1000]}"
            f"{'...' if len(mail_item.body) > 1000 else ''}\n\n"
            f"{sep}\n"
            f"Svara på detta mail med ett av följande:\n\n"
            f"  {wl_kw}    — lägg till {sender_email} i vitlistan\n"
            f"  {bl_kw} — blockera {sender_email} permanent\n"
            f"  {kp_kw}      — behåll som olistad (ingen åtgärd)\n"
            f"{sep}\n"
        ),
    )
    return notif_msg_id


# ── Vitlista/svartlista-svar från Fredrik ─────────────────────────────────────

def check_flagged_responses(config):
    """
    Kontrollerar om Fredrik svarat VITLISTA/SVARTLISTA/BEHÅLL på flaggade notifieringar.
    Anropas i slutet av varje poll-cykel.
    """
    wl_kw = config.get("mail", "whitelist_keyword",  fallback="VITLISTA").upper()
    bl_kw = config.get("mail", "blacklist_keyword",  fallback="SVARTLISTA").upper()
    kp_kw = config.get("mail", "keep_keyword",       fallback="BEHÅLL").upper()
    notify_addr = config.get("mail", "notify_address").lower()
    wl_page_id  = config.get("mail", "whitelist_notion_page_id", fallback="")

    pending = state.get_pending_flagged_notifications()
    if not pending:
        return

    host     = config.get("mail", "imap_host")
    port     = int(config.get("mail", "imap_port"))
    imap_user = config.get("mail", "imap_user_clio")
    imap_pw   = config.get("mail", "imap_password_clio")

    try:
        import imaplib, email as email_lib
        from email.header import decode_header as _dh

        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(imap_user, imap_pw)
        conn.select("INBOX")

        for row in pending:
            notif_id   = row["id"]
            notif_msgid = row["notification_message_id"]
            sender_email = row["sender_email"]

            _, data = conn.uid("search", None, f'HEADER In-Reply-To "{notif_msgid}"')
            uids = data[0].split() if data[0] else []

            for uid in uids:
                _, msg_data = conn.uid("fetch", uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)

                from_raw = "".join(
                    p.decode(e or "utf-8") if isinstance(p, bytes) else p
                    for p, e in _dh(msg.get("From", ""))
                ).lower()
                if notify_addr not in from_raw:
                    continue

                body = _get_plain_body(msg).strip().upper()
                response = None
                for line in body.splitlines():
                    line = line.strip()
                    if line == wl_kw:
                        response = wl_kw
                        break
                    if line == bl_kw:
                        response = bl_kw
                        break
                    if line == kp_kw:
                        response = kp_kw
                        break

                if response is None:
                    continue

                state.record_flagged_response(notif_id, response)

                if response == wl_kw and wl_page_id:
                    notion_client.add_to_whitelist(wl_page_id, sender_email)
                    logger.info(t("mail_whitelisted", sender=sender_email))
                elif response == bl_kw:
                    state.add_to_blacklist(sender_email)
                    logger.info(t("mail_blacklisted_response", sender=sender_email))
                elif response == kp_kw:
                    logger.info(t("mail_kept_unlisted", sender=sender_email))
                break

        conn.logout()

    except Exception as e:
        logger.error(t("mail_flagged_check_error", error=e))


def _get_plain_body(msg) -> str:
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


# ── Poll-cykel ────────────────────────────────────────────────────────────────

def run_cycle(config, dry_run: bool = False) -> bool:
    """
    Kör ett komplett poll-pass: hämta mail + hantera godkännanden.
    Returnerar True om minst ett nytt mail hämtades.
    """
    logger.info(t("mail_poll_start"))

    mail_items = poll_once(config)
    for item in mail_items:
        process_mail(item, config, dry_run)

    def _smtp_send(**kwargs):
        smtp_client.send_email(config=config, dry_run=dry_run, **kwargs)

    approval_module.check_approvals(
        config=config,
        smtp_send_fn=_smtp_send,
        dry_run=dry_run,
    )
    check_flagged_responses(config)

    logger.info(t("mail_poll_done"))
    return len(mail_items) > 0


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t("mail_description")
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=t("mail_dry_run_help"),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help=t("mail_once_help"),
    )
    args = parser.parse_args(argv)

    config = load_config()

    if not args.dry_run:
        state.init_db()

    interval = int(config.get("mail", "poll_interval_seconds", fallback="300"))

    if args.once or args.dry_run:
        run_cycle(config, dry_run=args.dry_run)
        return

    burst_interval = 60          # sekunder mellan polls efter aktivitet
    burst_duration = 300         # sekunder burst-läget håller (5 min)
    night_interval = int(config.get("mail", "poll_interval_night_seconds", fallback="900"))
    night_start    = int(config.get("mail", "poll_night_start_hour", fallback="22"))
    night_end      = int(config.get("mail", "poll_night_end_hour",   fallback="6"))
    last_activity = 0.0          # tidsstämpel för senaste mail

    logger.info(t("mail_agent_starting", interval=interval,
                  night_start=night_start, night_end=night_end,
                  night_interval=night_interval,
                  burst_interval=burst_interval, burst_duration=burst_duration))
    while True:
        try:
            had_mail = run_cycle(config)
            if had_mail:
                last_activity = time.time()
        except Exception as e:
            logger.error(t("mail_poll_error", error=e), exc_info=True)

        from datetime import datetime as _dt
        hour = _dt.now().hour
        if night_start <= hour or hour < night_end:
            base_interval = night_interval
            mode_label = "natt"
        else:
            base_interval = interval
            mode_label = "dag"

        since_activity = time.time() - last_activity
        if last_activity and since_activity < burst_duration:
            sleep_time = burst_interval
            remaining = int(burst_duration - since_activity)
            logger.info(t("mail_burst_mode", sleep=sleep_time, remaining=remaining))
        else:
            sleep_time = base_interval
            logger.debug(t("mail_sleep_mode", mode=mode_label, sleep=sleep_time))
        time.sleep(sleep_time)


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

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


def _extract_email(sender: str) -> str:
    match = re.search(r"<([^>]+)>", sender)
    return match.group(1).strip() if match else sender.strip()


def _short(text: str, n: int) -> str:
    return text[:n] if len(text) > n else text


if __name__ == "__main__":
    main()
