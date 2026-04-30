"""
patch_rag_handler.py — ersätter _handle_rag_query med tråd + bilage-stöd,
och uppdaterar process_mail att skicka med thread_id.
Körs en gång på servern: python3 patch_rag_handler.py
"""
from pathlib import Path

p = Path(__file__).parent / "clio-agent-mail" / "handlers.py"
src = p.read_text(encoding="utf-8")

# ── 1. Skicka thread_id till _handle_rag_query på alla tre ställen ──────────
for old, new in [
    (
        'if clf.account_key == "ssf":\n'
        '                _handle_rag_query(mail_item, clf, config, dry_run)\n'
        '            else:\n'
        '                _handle_self_query(mail_item, clf, config, dry_run)',
        'if clf.account_key == "ssf":\n'
        '                _handle_rag_query(mail_item, clf, thread_id, config, dry_run)\n'
        '            else:\n'
        '                _handle_self_query(mail_item, clf, config, dry_run)',
    ),
    (
        '            if clf.account_key == "ssf":\n'
        '                _handle_rag_query(mail_item, clf, config, dry_run)\n'
        '            else:\n'
        '                _handle_faq(mail_item, clf, config, dry_run)',
        '            if clf.account_key == "ssf":\n'
        '                _handle_rag_query(mail_item, clf, thread_id, config, dry_run)\n'
        '            else:\n'
        '                _handle_faq(mail_item, clf, config, dry_run)',
    ),
    (
        '            if clf.account_key == "ssf":\n'
        '                _handle_rag_query(mail_item, clf, config, dry_run)\n'
        '            else:\n'
        '                _handle_auto_send(mail_item, clf, config, dry_run)',
        '            if clf.account_key == "ssf":\n'
        '                _handle_rag_query(mail_item, clf, thread_id, config, dry_run)\n'
        '            else:\n'
        '                _handle_auto_send(mail_item, clf, config, dry_run)',
    ),
]:
    assert old in src, f"Hittade inte: {old[:60]}..."
    src = src.replace(old, new, 1)

# ── 2. Ersätt hela _handle_rag_query med tråd + bilage-version ──────────────
old_fn_start = "\ndef _handle_rag_query(mail_item, clf, config, dry_run: bool):"
old_fn_end   = "\ndef _handle_self_query("

start_idx = src.index(old_fn_start)
end_idx   = src.index(old_fn_end, start_idx)

new_fn = '''

def _handle_rag_query(mail_item, clf, thread_id: str, config, dry_run: bool):
    """Admin/coded mailar ssf@arvas.international — RAG mot cap_ssf_crm.
    Stöder trådad konversation (via thread_history) och bifogade filer.
    """
    import subprocess
    import re
    import sys
    import json
    import attachments as att_module

    to_addr = _extract_email(mail_item.sender)

    # ── Fråga: ämnesrad + första stycket av brödtext ─────────────────────────
    subject_clean = re.sub(
        r"^(Re|Fwd|Fw|Sv|VS):\\s*", "", mail_item.subject or "", flags=re.IGNORECASE
    ).strip()
    body_raw = _get_plain_body(mail_item) or ""
    body_lines = [l for l in body_raw.splitlines() if l.strip() and not l.startswith(">")]
    first_para = " ".join(body_lines[:5]).strip()

    question = subject_clean
    if first_para and first_para.lower() != subject_clean.lower():
        question = f"{subject_clean}. {first_para}"
    if not question:
        question = "Ge en översikt av projektets innehåll"

    # ── Konversationshistorik ────────────────────────────────────────────────
    history: list[dict] = []
    if thread_id:
        raw_history = state.get_thread_history(thread_id)
        for msg in raw_history:
            direction = msg.get("direction", "inbound")
            body      = (msg.get("body") or "").strip()
            if not body:
                continue
            # Strippa citerad text (>-rader) och vår footer från outbound
            clean_lines = []
            for line in body.splitlines():
                if line.startswith(">"):
                    break
                if line.startswith("---") and "cap_ssf_crm" in body:
                    break
                clean_lines.append(line)
            clean_body = "\\n".join(clean_lines).strip()
            if not clean_body:
                continue
            role = "user" if direction == "inbound" else "assistant"
            history.append({"role": role, "content": clean_body})

    # ── Bilagor ──────────────────────────────────────────────────────────────
    attachment_text: str | None = None
    att_names: list[str] = []
    for att in getattr(mail_item, "attachments", []):
        filepath = getattr(att, "filepath", None) or getattr(att, "path", None)
        filename = getattr(att, "filename", "")
        if not filepath:
            continue
        ext = Path(filepath).suffix.lower()
        if ext not in {".pdf", ".docx", ".pptx", ".txt", ".csv", ".xlsx"}:
            continue
        try:
            result = att_module.extract(filepath)
            if result.text and result.text.strip():
                attachment_text = (attachment_text or "") + f"[{filename}]\\n{result.text[:3000]}\\n\\n"
                att_names.append(filename)
        except Exception as e:
            logger.warning(f"[rag_query] Kunde inte läsa bilaga {filename}: {e}")

    logger.info(
        f"[rag_query] ssf@ från {to_addr}: {question[:60]}"
        + (f" | historik: {len(history)} msg" if history else "")
        + (f" | bilagor: {att_names}" if att_names else "")
    )

    # ── Kör query.py ─────────────────────────────────────────────────────────
    rag_script = Path(__file__).parent.parent / "clio-rag" / "query.py"
    cmd = [
        sys.executable, str(rag_script),
        "--collection", "cap_ssf_crm",
        "--q",          question,
        "--top",        "5",
    ]
    if history:
        cmd += ["--history", json.dumps(history, ensure_ascii=False)]
    if attachment_text:
        cmd += ["--attachment-text", attachment_text]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(rag_script.parent),
        )
        rag_output = (
            result.stdout.strip()
            if result.returncode == 0
            else f"RAG-fel: {result.stderr[:300]}"
        )
    except subprocess.TimeoutExpired:
        rag_output = "Tidsgräns överskreds (90 s) — försök med en kortare fråga."
    except Exception as e:
        rag_output = f"Tekniskt fel: {e}"

    # ── Rensa query.py-header ─────────────────────────────────────────────────
    skip = ("Fråga:", "Collection:", "Söker", "Historik:", "Bilaga:")
    clean_lines = [
        line for line in rag_output.splitlines()
        if not any(line.startswith(s) for s in skip)
    ]
    reply_text = "\\n".join(clean_lines).strip()

    # ── Bygg svar ────────────────────────────────────────────────────────────
    footer_parts = ["📚 cap_ssf_crm | SSF CRM 2023"]
    if att_names:
        footer_parts.append(f"📎 Bilagor lästa: {', '.join(att_names)}")

    reply_body = (
        f"**Fråga:** {subject_clean}\\n\\n"
        f"{reply_text}\\n\\n"
        f"---\\n"
        + " | ".join(footer_parts)
    )

    if not dry_run:
        out_msg_id = f"<clio-rag-{__import__('uuid').uuid4()}@arvas.international>"
        smtp_client.send_email(
            config=config,
            from_account_key=clf.account_key,
            to_addr=to_addr,
            subject=f"Re: {mail_item.subject}",
            body=reply_body + _quote_original(mail_item),
            reply_to_message_id=mail_item.message_id,
            message_id=out_msg_id,
        )
        # Spara utgående svar i tråden så nästa mail har historik
        state.save_mail(
            message_id=out_msg_id,
            account=config.get("mail", f"imap_user_{clf.account_key}", fallback="ssf@arvas.international"),
            sender=config.get("mail", f"imap_user_{clf.account_key}", fallback="ssf@arvas.international"),
            subject=f"Re: {mail_item.subject}",
            body=reply_body,
            date_received=__import__("datetime").datetime.utcnow().isoformat(),
            status=state.STATUS_SENT,
            action="RAG_QUERY",
            thread_id=thread_id,
            in_reply_to=mail_item.message_id,
            direction="outbound",
        )
        state.update_status(mail_item.message_id, state.STATUS_SENT)
        logger.info(f"[rag_query] Svar skickat till {to_addr} (tråd: {thread_id[:20]}…)")

'''

src = src[:start_idx] + new_fn + src[end_idx:]

p.write_text(src, encoding="utf-8")
print(f"OK — handlers.py uppdaterad ({len(src)} tecken)")
