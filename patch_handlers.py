"""
patch_handlers.py — lägger till _handle_rag_query i handlers.py
Körs en gång på servern: python3 patch_handlers.py
"""
from pathlib import Path

p = Path(__file__).parent / "clio-agent-mail" / "handlers.py"
src = p.read_text(encoding="utf-8")

# ── 1. Route: ssf-konto → RAG-handler ────────────────────────────────────────
old_route = (
    "        elif clf.action == classifier.ACTION_SELF_QUERY:\n"
    "            _handle_self_query(mail_item, clf, config, dry_run)"
)
new_route = (
    "        elif clf.action == classifier.ACTION_SELF_QUERY:\n"
    "            if clf.account_key == \"ssf\":\n"
    "                _handle_rag_query(mail_item, clf, config, dry_run)\n"
    "            else:\n"
    "                _handle_self_query(mail_item, clf, config, dry_run)"
)
assert old_route in src, "Route-sträng hittades inte!"
src = src.replace(old_route, new_route, 1)

# ── 2. Ny funktion, infogas precis före _handle_self_query ────────────────────
new_fn = '''

def _handle_rag_query(mail_item, clf, config, dry_run: bool):
    """Admin mailar ssf@arvas.international — frågar RAG-collectionen cap_ssf_crm."""
    import subprocess
    import re
    import sys

    to_addr = _extract_email(mail_item.sender)

    # Bygg frågan: ämnesrad (utan Re:/Fwd:) + första stycket av brödtext
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

    logger.info(f"[rag_query] ssf@ från {to_addr}: {question[:80]}")

    # Kör query.py mot cap_ssf_crm
    rag_script = Path(__file__).parent.parent / "clio-rag" / "query.py"
    try:
        result = subprocess.run(
            [sys.executable, str(rag_script),
             "--collection", "cap_ssf_crm",
             "--q", question,
             "--top", "5"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(rag_script.parent),
        )
        rag_output = (
            result.stdout.strip()
            if result.returncode == 0
            else f"RAG-fel: {result.stderr[:200]}"
        )
    except subprocess.TimeoutExpired:
        rag_output = "Tidsgräns överskreds (60 s) — försök med en kortare fråga."
    except Exception as e:
        rag_output = f"Tekniskt fel: {e}"

    # Rensa query.py-header (Fråga: / Collection: / Söker …)
    skip = ("Fråga:", "Collection:", "Söker")
    clean_lines = [
        line for line in rag_output.splitlines()
        if not any(line.startswith(s) for s in skip)
    ]
    reply_text = "\\n".join(clean_lines).strip()

    reply_body = (
        f"**Fråga:** {subject_clean}\\n\\n"
        f"{reply_text}\\n\\n"
        f"---\\n"
        f"📚 Collection: cap_ssf_crm | SSF CRM 2023"
    )

    if not dry_run:
        smtp_client.send_email(
            config=config,
            from_account_key=clf.account_key,
            to_addr=to_addr,
            subject=f"Re: {mail_item.subject}",
            body=reply_body + _quote_original(mail_item),
            reply_to_message_id=mail_item.message_id,
        )
        state.update_status(mail_item.message_id, state.STATUS_SENT)
        logger.info(f"[rag_query] Svar skickat till {to_addr}")

'''

anchor = "\ndef _handle_self_query("
assert anchor in src, "Hittade inte _handle_self_query!"
src = src.replace(anchor, new_fn + "\ndef _handle_self_query(", 1)

p.write_text(src, encoding="utf-8")
print(f"OK — handlers.py uppdaterad ({len(src)} tecken)")
