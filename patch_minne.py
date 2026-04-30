"""
patch_minne.py — lägger till [rag_accounts] i clio.config och
uppdaterar _handle_rag_query med multi-collection + bilage-sparning.
Körs en gång på servern: python3 patch_minne.py
"""
from pathlib import Path
import re

ROOT = Path(__file__).parent

# ── 1. clio.config — lägg till [rag_accounts] ────────────────────────────────
cfg_path = ROOT / "clio-agent-mail" / "clio.config"
cfg = cfg_path.read_text(encoding="utf-8")

RAG_SECTION = """
# ── RAG-konton ───────────────────────────────────────────────────────────────
# Format: account_key = collection1, collection2, ...   (kommaseparerade)
# minnet_path = absolut sökväg till Dropbox/*minnet-mapp (för bilage-sparning + cron)
[rag_accounts]
ssf_collections  = cap_ssf_crm, mem_ssf
ssf_minnet_path  = ~/Dropbox/projekt/Capgemini/Skidförbundet/ssfminnet
aiab_collections = mem_aiab
aiab_minnet_path = ~/Dropbox/ftg/AIAB/aiabminnet
gsf_collections  = mem_gsf
gsf_minnet_path  = ~/Dropbox/ftg/GSF/gsfminnet
"""

if "[rag_accounts]" not in cfg:
    cfg = cfg.rstrip() + "\n" + RAG_SECTION
    cfg_path.write_text(cfg, encoding="utf-8")
    print("OK — [rag_accounts] tillagt i clio.config")
else:
    print("INFO — [rag_accounts] finns redan")

# ── 2. handlers.py — ersätt _handle_rag_query ────────────────────────────────
h_path = ROOT / "clio-agent-mail" / "handlers.py"
src = h_path.read_text(encoding="utf-8")

old_fn_start = "\ndef _handle_rag_query("
old_fn_end   = "\ndef _handle_self_query("

start_idx = src.index(old_fn_start)
end_idx   = src.index(old_fn_end, start_idx)

NEW_FN = '''

def _handle_rag_query(mail_item, clf, thread_id: str, config, dry_run: bool):
    """ssf@/aiab@/gsf@ → multi-collection RAG + bilage-sparning i *minnet-mapp."""
    import subprocess
    import re
    import sys
    import json
    import uuid as _uuid
    from datetime import datetime as _dt
    import attachments as att_module

    to_addr    = _extract_email(mail_item.sender)
    account    = clf.account_key   # "ssf" | "aiab" | "gsf"

    # ── Läs config ───────────────────────────────────────────────────────────
    def _cfg(key, fallback=""):
        try:
            return config.get("rag_accounts", f"{account}_{key}", fallback=fallback)
        except Exception:
            return fallback

    collections_raw = _cfg("collections", "cap_ssf_crm" if account == "ssf" else f"mem_{account}")
    collections     = [c.strip() for c in collections_raw.split(",") if c.strip()]
    minnet_path_str = _cfg("minnet_path", "")
    minnet_path     = Path(minnet_path_str).expanduser() if minnet_path_str else None

    # ── Fråga ────────────────────────────────────────────────────────────────
    subject_clean = re.sub(
        r"^(Re|Fwd|Fw|Sv|VS):\\s*", "", mail_item.subject or "", flags=re.IGNORECASE
    ).strip()
    body_raw   = _get_plain_body(mail_item) or ""
    body_lines = [l for l in body_raw.splitlines() if l.strip() and not l.startswith(">")]
    first_para = " ".join(body_lines[:5]).strip()

    question = subject_clean
    if first_para and first_para.lower() != subject_clean.lower():
        question = f"{subject_clean}. {first_para}"
    if not question:
        question = "Ge en översikt av projektets innehåll"

    # ── Konversationshistorik ─────────────────────────────────────────────────
    history: list[dict] = []
    if thread_id:
        for msg in state.get_thread_history(thread_id):
            direction = msg.get("direction", "inbound")
            body      = (msg.get("body") or "").strip()
            clean_lines = []
            for line in body.splitlines():
                if line.startswith(">"):
                    break
                if line.startswith("---") and "mem_" in body:
                    break
                clean_lines.append(line)
            clean_body = "\\n".join(clean_lines).strip()
            if clean_body:
                history.append({
                    "role":    "user" if direction == "inbound" else "assistant",
                    "content": clean_body,
                })

    # ── Bilagor: extrahera + spara till *minnet-mapp ─────────────────────────
    attachment_text: str | None = None
    att_names: list[str]        = []
    sender_slug = re.sub(r"[^a-z0-9]", "_", to_addr.split("@")[0].lower())[:20]
    datestamp   = _dt.utcnow().strftime("%Y%m%d_%H%M%S")

    for att in getattr(mail_item, "attachments", []):
        filepath = getattr(att, "filepath", None) or getattr(att, "path", None)
        filename = getattr(att, "filename", "") or ""
        if not filepath:
            continue
        ext = Path(filepath).suffix.lower()
        if ext not in {".pdf", ".docx", ".pptx", ".txt", ".csv", ".xlsx"}:
            continue
        try:
            result = att_module.extract(filepath)
            if result.text and result.text.strip():
                attachment_text = (attachment_text or "") + (
                    f"[{filename}]\\n{result.text[:3000]}\\n\\n"
                )
                att_names.append(filename)
        except Exception as e:
            logger.warning(f"[rag_query] Kunde inte läsa bilaga {filename}: {e}")

        # Spara till *minnet-mapp
        if minnet_path and not dry_run:
            try:
                minnet_path.mkdir(parents=True, exist_ok=True)
                safe_name  = re.sub(r"[^\\w\\-.]", "_", filename)
                dest       = minnet_path / f"{datestamp}_{sender_slug}_{safe_name}"
                import shutil
                shutil.copy2(filepath, dest)
                logger.info(f"[rag_query] Bilaga sparad: {dest.name}")
            except Exception as e:
                logger.warning(f"[rag_query] Kunde inte spara bilaga till minnet: {e}")

    logger.info(
        f"[rag_query] {account}@ från {to_addr}: {question[:60]}"
        + (f" | collections: {collections}" )
        + (f" | historik: {len(history)} msg" if history else "")
        + (f" | bilagor: {att_names}" if att_names else "")
    )

    # ── Kör query.py mot alla collections, samla hits ─────────────────────────
    rag_script = Path(__file__).parent.parent / "clio-rag" / "query.py"
    combined_output_parts: list[str] = []

    for collection in collections:
        cmd = [
            sys.executable, str(rag_script),
            "--collection", collection,
            "--q",          question,
            "--top",        "4",
        ]
        if history:
            cmd += ["--history", json.dumps(history, ensure_ascii=False)]
        if attachment_text:
            cmd += ["--attachment-text", attachment_text]

        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=90,
                cwd=str(rag_script.parent),
            )
            out = res.stdout.strip() if res.returncode == 0 else f"[{collection}] Fel: {res.stderr[:150]}"
        except subprocess.TimeoutExpired:
            out = f"[{collection}] Tidsgräns överskreds."
        except Exception as e:
            out = f"[{collection}] Tekniskt fel: {e}"

        skip = ("Fråga:", "Collection:", "Söker", "Historik:", "Bilaga:")
        clean = "\\n".join(
            l for l in out.splitlines() if not any(l.startswith(s) for s in skip)
        ).strip()
        if clean:
            combined_output_parts.append(clean)

    reply_text = "\\n\\n".join(combined_output_parts).strip() or "Inga träffar i projektminnet."

    # ── Bygg svarsmail ────────────────────────────────────────────────────────
    col_label    = " + ".join(collections)
    footer_parts = [f"📚 {col_label}"]
    if att_names:
        footer_parts.append(f"📎 Sparad i {account}minnet: {', '.join(att_names)}")

    reply_body = (
        f"**Fråga:** {subject_clean}\\n\\n"
        f"{reply_text}\\n\\n"
        f"---\\n"
        + " | ".join(footer_parts)
    )

    if not dry_run:
        out_msg_id = f"<clio-rag-{_uuid.uuid4()}@arvas.international>"
        smtp_client.send_email(
            config=config,
            from_account_key=clf.account_key,
            to_addr=to_addr,
            subject=f"Re: {mail_item.subject}",
            body=reply_body + _quote_original(mail_item),
            reply_to_message_id=mail_item.message_id,
            message_id=out_msg_id,
        )
        state.save_mail(
            message_id=out_msg_id,
            account=config.get("mail", f"imap_user_{clf.account_key}",
                               fallback=f"{clf.account_key}@arvas.international"),
            sender=config.get("mail", f"imap_user_{clf.account_key}",
                              fallback=f"{clf.account_key}@arvas.international"),
            subject=f"Re: {mail_item.subject}",
            body=reply_body,
            date_received=_dt.utcnow().isoformat(),
            status=state.STATUS_SENT,
            action="RAG_QUERY",
            thread_id=thread_id,
            in_reply_to=mail_item.message_id,
            direction="outbound",
        )
        state.update_status(mail_item.message_id, state.STATUS_SENT)
        logger.info(f"[rag_query] Svar skickat till {to_addr}")

'''

src = src[:start_idx] + NEW_FN + src[end_idx:]
h_path.write_text(src, encoding="utf-8")
print(f"OK — handlers.py uppdaterad ({len(src)} tecken)")
