"""
handlers.py — mail-routing och svarsgenerering för clio-agent-mail

Innehåller:
  - process_mail()           — entrypoint från run_cycle, dispatchar på classifier-action
  - _handle_*                — en handler per klassificering (auto/approval/standard/faq/...)
  - _send_copy / _send_info_to_fredrik / _send_flagged_notification — notifieringar till Fredrik
  - check_flagged_responses()        — läser VITLISTA/SVARTLISTA/BEHÅLL-svar
  - _process_waiting_mails()         — bearbetar WAITING-mail när avsändare blir vitlistad
  - _send_standard_for_waiting()     — skickar standardsvar vid BEHÅLL
  - _auto_process_newly_whitelisted() — scannar WAITING-mail mot aktuell vitlista

Importeras av main.py. Använder helpers.py för rena hjälpfunktioner.
"""
import logging
import re
import uuid
from pathlib import Path

import state
import classifier
import commands
import smtp_client
import notion_data as notion_client
import faq as faq_module
import reply as reply_module
import approval as approval_module

from helpers import (
    _extract_email,
    _short,
    _quote_original,
    _get_plain_body,
    _fredrik_in_recipients,
    _resolve_fredrik_cc,
    _account_key_for,
)

logger = logging.getLogger("clio-mail")

_INTERNAL_TAGS = {"[CLIO-FLAGGAD]", "[CLIO-KOPIA]", "[CLIO-INFO]"}


# ── Mailhantering ─────────────────────────────────────────────────────────────

def process_mail(mail_item, config, dry_run: bool = False):
    """Klassificerar och hanterar ett inkommande mail."""
    if state.is_seen(mail_item.message_id):
        logger.debug(f"Redan sett: {mail_item.message_id}")
        return

    subject = mail_item.subject or ""
    if any(tag in subject for tag in _INTERNAL_TAGS):
        logger.warning(
            f"Hoppar över internt systemmail (tag i ämnesrad): {subject[:80]}"
        )
        return

    # `help`-kommandot är öppet för alla avsändare
    import commands as cmd_module
    if cmd_module.resolve_command(subject) == "help":
        _handle_help_for_anyone(mail_item, config=config, dry_run=dry_run)
        return

    whitelist_page = config.get("mail", "whitelist_notion_page_id")
    whitelist = notion_client.get_whitelist(whitelist_page)
    clf = classifier.classify(mail_item, whitelist, config)

    logger.info(
        f"[{clf.account_key}@] {_short(mail_item.sender, 40)} → {clf.action} ({clf.reason})"
    )

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
        if clf.action == classifier.ACTION_SELF_QUERY:
            _handle_self_query(mail_item, clf, config, dry_run)

        elif clf.action == classifier.ACTION_FAQ_CHECK:
            _handle_faq(mail_item, clf, config, dry_run)

        elif clf.action == classifier.ACTION_AUTO_SEND:
            _handle_auto_send(mail_item, clf, config, dry_run)

        elif clf.action == classifier.ACTION_SEND_FOR_APPROVAL:
            _handle_approval(mail_item, clf, config, dry_run)

        elif clf.action == classifier.ACTION_STANDARD_REPLY:
            _handle_standard(mail_item, clf, config, dry_run)

        elif clf.action == classifier.ACTION_OBIT_IMPORT:
            _handle_obit_import(mail_item, clf, config, dry_run)

    except Exception as e:
        logger.error(f"Error handling {mail_item.message_id}: {e}", exc_info=True)


def _handle_obit_import(mail_item, clf, config, dry_run: bool):
    """Hanterar returnerad [clio-obit] CSV — importerar bevakningslista och skickar kvitto."""
    import commands as cmd_module
    to_addr = _extract_email(mail_item.sender)
    result = cmd_module.dispatch("obit_import", mail_item, config)
    logger.info(f"[obit_import] {to_addr}: {result.reply_body[:80]}")
    if not dry_run:
        smtp_client.send_email(
            config=config,
            from_account_key=clf.account_key,
            to_addr=to_addr,
            subject=f"Re: {mail_item.subject}",
            body=result.reply_body + _quote_original(mail_item),
            reply_to_message_id=mail_item.message_id,
        )
        state.update_status(mail_item.message_id, state.STATUS_SENT)


def _handle_self_query(mail_item, clf, config, dry_run: bool):
    """Admin frågar/ger kommando till Clio — svarar utan godkännandeflöde eller notiser."""
    import commands as cmd_module

    to_addr = _extract_email(mail_item.sender)
    command = cmd_module.resolve_command(mail_item.subject or "")

    if command:
        # Kommandobehandling — admins når hit, så alla kommandon är tillåtna
        result = cmd_module.dispatch(command, mail_item, config)
        logger.info(f"Command '{command}' dispatched for {to_addr}"
                    + (" [reasoning]" if result.is_reasoning else ""))
        if not dry_run:
            smtp_client.send_email(
                config=config,
                from_account_key=clf.account_key,
                to_addr=to_addr,
                subject=f"Re: {mail_item.subject}",
                body=result.reply_body + _quote_original(mail_item),
                reply_to_message_id=mail_item.message_id,
            )
            for out in result.outbound:
                smtp_client.send_email(
                    config=config,
                    from_account_key=out.from_account_key,
                    to_addr=out.to_addr,
                    subject=out.subject,
                    body=out.body,
                )
            state.update_status(mail_item.message_id, state.STATUS_SENT)
    else:
        # Fri fråga — AI-svar med kunskapsbas
        knowledge = notion_client.get_knowledge_context(
            config, mail_subject=mail_item.subject, mail_body=mail_item.body
        )
        reply_text = reply_module.generate_self_query_reply(mail_item, config, knowledge=knowledge)
        logger.info(f"Self-query AI reply generated for {to_addr}")
        if not dry_run:
            smtp_client.send_email(
                config=config,
                from_account_key=clf.account_key,
                to_addr=to_addr,
                subject=f"Re: {mail_item.subject}",
                body=reply_text + _quote_original(mail_item),
                reply_to_message_id=mail_item.message_id,
            )
            state.update_status(mail_item.message_id, state.STATUS_SENT)


def _handle_help_for_anyone(mail_item, config, dry_run: bool):
    """Svarar på 'help'-kommando från valfri avsändare — ingen admin-behörighet krävs."""
    import commands as cmd_module
    to_addr = _extract_email(mail_item.sender)
    account_key = _account_key_for(mail_item.account, config)
    result = cmd_module.dispatch("help", mail_item, config)
    logger.info(f"Help dispatched to {to_addr}")
    if not dry_run:
        if not state.is_seen(mail_item.message_id):
            state.save_mail(
                message_id=mail_item.message_id,
                account=mail_item.account,
                sender=mail_item.sender,
                subject=mail_item.subject,
                body=mail_item.body,
                date_received=mail_item.date_received,
                status=state.STATUS_NEW,
                action="HELP",
            )
        smtp_client.send_email(
            config=config,
            from_account_key=account_key,
            to_addr=to_addr,
            subject=f"Re: {mail_item.subject}",
            body=result.reply_body,
            reply_to_message_id=mail_item.message_id,
        )
        state.update_status(mail_item.message_id, state.STATUS_SENT)


def _handle_faq(mail_item, clf, config, dry_run: bool):
    faq_page = config.get("mail", "faq_notion_page_id")
    faq_items = notion_client.get_faq(faq_page)
    match = faq_module.match_faq(mail_item, faq_items, config)
    fredrik_in_original = _fredrik_in_recipients(mail_item, config)

    if match.confidence == faq_module.CONFIDENCE_HIGH:
        reply_text = faq_module.generate_faq_reply(mail_item, match, config)
        logger.info(f"FAQ-svar genererat (match: {_short(match.question, 40)})")
        if not dry_run:
            smtp_client.send_email(
                config=config,
                from_account_key="info",
                to_addr=_extract_email(mail_item.sender),
                subject=f"Re: {mail_item.subject}",
                body=reply_text + _quote_original(mail_item),
                reply_to_message_id=mail_item.message_id,
            )
            if not fredrik_in_original:
                _send_copy(mail_item, reply_text, "FAQ-svar skickat autonomt", config)
            state.update_status(mail_item.message_id, state.STATUS_SENT)

    else:
        holding = faq_module.generate_holding_reply(mail_item, config)
        logger.info(f"Holding-svar genererat (konfidens: {match.confidence})")
        if not dry_run:
            smtp_client.send_email(
                config=config,
                from_account_key="info",
                to_addr=_extract_email(mail_item.sender),
                subject=f"Re: {mail_item.subject}",
                body=holding + _quote_original(mail_item),
                reply_to_message_id=mail_item.message_id,
            )
            if not fredrik_in_original:
                _send_info_to_fredrik(
                    mail_item, holding,
                    f"Låg FAQ-konfidens ({match.confidence}): {match.explanation}",
                    config,
                )
            state.update_status(mail_item.message_id, state.STATUS_SENT)


def _handle_auto_send(mail_item, clf, config, dry_run: bool):
    # Kontrollera om det är ett /update-kommando från en skrivbehörig coded-användare
    cmd = commands.resolve_command(mail_item.subject)
    if cmd == "update":
        result = commands.dispatch("update", mail_item, config)
        sender = _extract_email(mail_item.sender)
        if not dry_run:
            smtp_client.send_email(
                config=config,
                from_account_key="clio",
                to_addr=sender,
                subject=f"Re: {mail_item.subject}",
                body=result.reply_body + _quote_original(mail_item),
                reply_to_message_id=mail_item.message_id,
            )
            for outbound in result.outbound:
                smtp_client.send_email(
                    config=config,
                    from_account_key=outbound.from_account_key,
                    to_addr=outbound.to_addr,
                    subject=outbound.subject,
                    body=outbound.body,
                )
            state.update_status(mail_item.message_id, state.STATUS_SENT)
        return

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
    logger.info(f"AUTO reply generated for {_short(mail_item.sender, 40)}"
                + (f" (CC: {fredrik_cc})" if fredrik_cc else ""))
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
        # Skicka kopia till Fredrik bara om han inte redan är CC:ad
        if not fredrik_cc:
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
    logger.info(f"Draft + approval request prepared for {_short(mail_item.sender, 40)}"
                + (f" (CC on approval: {fredrik_cc})" if fredrik_cc else ""))
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
        logger.info(f"Svartlistad avsändare {sender_email} — ingen åtgärd")
        state.update_status(mail_item.message_id, state.STATUS_FLAGGED)
        return

    # Registrera avsändaren i partners med detekterat språk (ej onboardad än)
    import commands as cmd_module
    lang = cmd_module._detect_language(sender_email, config)
    state.upsert_partner(sender_email, language=lang, role="contact")

    # Skicka hållsvar ("tack, vi återkommer") och lägg mailet i vänteläge
    holding = reply_module.generate_holding_reply_for_unknown(mail_item, config)
    account_key = clf.account_key
    logger.info(f"Hållsvar + flaggnotis för okänd avsändare {_short(mail_item.sender, 40)}")
    if not dry_run:
        smtp_client.send_email(
            config=config,
            from_account_key=account_key,
            to_addr=sender_email,
            subject=f"Re: {mail_item.subject}",
            body=holding + _quote_original(mail_item),
            reply_to_message_id=mail_item.message_id,
        )
        notif_msg_id = _send_flagged_notification(mail_item, config)
        mail_id = state.get_mail_id(mail_item.message_id)
        if mail_id and notif_msg_id:
            state.save_flagged_notification(mail_id, notif_msg_id, sender_email)
        state.update_status(mail_item.message_id, state.STATUS_WAITING)


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

        timeout = int(config.get("mail", "imap_timeout_seconds", fallback="30"))
        conn = imaplib.IMAP4_SSL(host, port, timeout=timeout)
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
                    logger.info(f"Vitlistad på Fredriks begäran: {sender_email}")
                    import commands as cmd_module
                    lang = cmd_module._detect_language(sender_email, config)
                    state.upsert_partner(sender_email, language=lang, role="contact")
                    _process_waiting_mails(sender_email, config)
                elif response == bl_kw:
                    state.add_to_blacklist(sender_email)
                    state.upsert_partner(sender_email, role="blacklisted")
                    logger.info(f"Svartlistad på Fredriks begäran: {sender_email}")
                elif response == kp_kw:
                    logger.info(f"Behålls olistad: {sender_email} — skickar standardsvar")
                    _send_standard_for_waiting(sender_email, config)
                break

        conn.logout()

    except Exception as e:
        logger.error(f"Error checking flagged responses: {e}")


# ── Väntande mail ────────────────────────────────────────────────────────────

def _reconstruct_mail_item(mail_data: dict, config):
    """Bygger ett minimalt MailItem från en state.db-rad (utan to/cc-headers)."""
    from imap_client import MailItem, AttachmentMeta, SUPPORTED_EXTENSIONS

    # Försök hitta sparade bilagor på disk
    _raw_attachments = config.get("mail", "attachments_dir", fallback="attachments")
    attachments_dir = Path(_raw_attachments)
    if not attachments_dir.is_absolute():
        attachments_dir = Path(__file__).parent / _raw_attachments
    attachments = []
    # short_id = sista 12 tecken av rensat message_id (nytt format från imap_client)
    short_id = re.sub(r"[^a-zA-Z0-9]", "", mail_data["message_id"])[-12:]
    # Fallback: matcha på datum + avsändar-lokal (gamla mappar saknar short_id)
    sender_raw = _extract_email(mail_data.get("sender", ""))
    sender_local = re.sub(r"[^a-zA-Z0-9åäöÅÄÖ.\-]", "", sender_raw.split("@")[0])[:20]
    date_prefix = mail_data.get("date_received", "")[:10]
    folder_prefix = f"{date_prefix}_{sender_local}" if date_prefix and sender_local else ""

    if attachments_dir.exists():
        for folder in attachments_dir.iterdir():
            if not folder.is_dir():
                continue
            # Primär match: short_id i mappnamnet (nytt format)
            # Fallback: datum+avsändare (gamla mappar)
            if short_id in folder.name or (folder_prefix and folder.name.startswith(folder_prefix)):
                for f in folder.iterdir():
                    if f.suffix.lower() in SUPPORTED_EXTENSIONS:
                        attachments.append(AttachmentMeta(
                            filename=f.name,
                            filepath=str(f),
                            content_type="application/octet-stream",
                        ))
                break

    return MailItem(
        message_id=mail_data["message_id"],
        account=mail_data["account"],
        sender=mail_data["sender"],
        subject=mail_data["subject"] or "",
        body=mail_data["body"] or "",
        date_received=mail_data["date_received"] or "",
        raw_uid="",
        to_addresses=[],
        cc_addresses=[],
        attachments=attachments,
    )


def _process_waiting_mails(sender_email: str, config):
    """
    Hämtar alla väntande mail från avsändaren och skickar riktiga AI-svar.
    Anropas när Fredrik svarat VITLISTA.
    """
    waiting = state.get_waiting_mails_for_sender(sender_email)
    if not waiting:
        logger.info(f"Inga väntande mail från {sender_email}")
        return

    logger.info(f"{len(waiting)} väntande mail från {sender_email} — bearbetar nu")
    for mail_data in waiting:
        try:
            mail_item = _reconstruct_mail_item(mail_data, config)
            knowledge = notion_client.get_knowledge_context(
                config, mail_subject=mail_item.subject, mail_body=mail_item.body
            )
            examples = state.get_learned_replies(limit=5)
            reply_text = reply_module.generate_reply(
                mail_item,
                "Avsändaren är nu vitlistad och väntar på svar.",
                config,
                knowledge=knowledge,
                examples=examples,
            )
            fredrik_cc = _resolve_fredrik_cc(mail_item, config)
            smtp_client.send_email(
                config=config,
                from_account_key=_account_key_for(mail_item.account, config),
                to_addr=_extract_email(mail_item.sender),
                subject=f"Re: {mail_item.subject}",
                body=reply_text + _quote_original(mail_item),
                reply_to_message_id=mail_item.message_id,
                cc_addrs=[fredrik_cc] if fredrik_cc else None,
            )
            state.update_status(mail_item.message_id, state.STATUS_SENT)
            logger.info(f"Väntande mail besvarat: {_short(mail_item.subject, 50)}")
        except Exception as e:
            logger.error(f"Fel vid bearbetning av väntande mail {mail_data['message_id']}: {e}")


def _send_standard_for_waiting(sender_email: str, config):
    """
    Skickar standardsvar på väntande mail när Fredrik svarat BEHÅLL.
    """
    waiting = state.get_waiting_mails_for_sender(sender_email)
    for mail_data in waiting:
        try:
            mail_item = _reconstruct_mail_item(mail_data, config)
            std_reply = reply_module.generate_standard_reply(mail_item, config)
            smtp_client.send_email(
                config=config,
                from_account_key=_account_key_for(mail_item.account, config),
                to_addr=_extract_email(mail_item.sender),
                subject=f"Re: {mail_item.subject}",
                body=std_reply + _quote_original(mail_item),
                reply_to_message_id=mail_item.message_id,
            )
            state.update_status(mail_item.message_id, state.STATUS_FLAGGED)
            logger.info(f"Standardsvar skickat för BEHÅLL: {_short(mail_item.subject, 50)}")
        except Exception as e:
            logger.error(f"Fel vid standardsvar för väntande mail {mail_data['message_id']}: {e}")


def _auto_process_newly_whitelisted(config, dry_run: bool = False):
    """
    Kontrollerar om några WAITING-mail har avsändare som nu är vitlistade.
    Skickar svar på dem automatiskt — oavsett om vitlistningen gjordes via
    mail-svar eller direkt i TUI:n.
    """
    import sqlite3 as _sql
    try:
        whitelist_page = config.get("mail", "whitelist_notion_page_id")
        whitelist = notion_client.get_whitelist(whitelist_page)
        if not whitelist:
            return

        with _sql.connect(str(state.DB_PATH)) as con:
            con.row_factory = _sql.Row
            rows = con.execute(
                "SELECT DISTINCT sender FROM mail WHERE status = ?",
                (state.STATUS_WAITING,)
            ).fetchall()

        for row in rows:
            sender_email = _extract_email(row["sender"]).lower()
            if sender_email in whitelist:
                logger.info(f"Vitlistad avsändare med väntande mail: {sender_email}")
                if not dry_run:
                    _process_waiting_mails(sender_email, config)
    except Exception as e:
        logger.error(f"Fel vid kontroll av nyligen vitlistade: {e}")
