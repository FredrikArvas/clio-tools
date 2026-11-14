#!/usr/bin/env python3
"""
audit_cliotools.py — Jämför clio-tools repo mot cliotools-kortets verktygsregister.

Kör:        python3 audit_cliotools.py
Förutsätter: NOTION_TOKEN i ~/19.0/clio-tools/.env
Idempotent: läser bara, skriver ingenting.
"""

import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("pip install requests saknas — kör: pip install requests")

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

REPO_ROOT = Path(__file__).resolve().parent
CLIOTOOLS_PAGE_ID = "35b67666d98a81498cfeecc2df238893"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def load_token():
    env_file = REPO_ROOT / ".env"
    if load_dotenv and env_file.exists():
        load_dotenv(env_file)
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit("❌  NOTION_TOKEN saknas — sätt den i .env eller som miljövariabel")
    return token


def fetch_blocks(token, page_id):
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    blocks = []
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        r = requests.get(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=headers,
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        blocks.extend(data["results"])
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return blocks


def block_text(block):
    btype = block["type"]
    rt = block.get(btype, {}).get("rich_text", [])
    return "".join(t.get("plain_text", "") for t in rt)


def get_card_tools(token):
    """
    Returns:
      tools_with_ncc:    dict  clio-name -> kodord  (e.g. "clio-vigil" -> "#vigil")
      tools_without_ncc: list  clio-name
    """
    blocks = fetch_blocks(token, CLIOTOOLS_PAGE_ID)

    tools_with_ncc = {}
    tools_without_ncc = []

    STOP_HEADINGS = {"Delade bibliotek", "Designprinciper", "Backup",
                     "Att åtgärda", "Beslutslogg", "Audit"}

    section = None

    for block in blocks:
        btype = block["type"]
        text = block_text(block)

        if btype in ("heading_2", "heading_3"):
            if "Verktyg med eget NCC" in text:
                section = "with_ncc"
            elif "Verktyg utan NCC" in text:
                section = "without_ncc"
            elif any(s in text for s in STOP_HEADINGS):
                section = None
            continue

        if btype == "bulleted_list_item" and section:
            if section == "with_ncc":
                # "**clio-foo** — #bar — beskrivning"
                m = re.search(r"(clio-[\w-]+).*?(#[\w-]+)", text)
                if m:
                    tools_with_ncc[m.group(1)] = m.group(2)
            elif section == "without_ncc":
                m = re.search(r"(clio-[\w-]+)", text)
                if m:
                    tools_without_ncc.append(m.group(1))

    return tools_with_ncc, tools_without_ncc


def get_repo_dirs():
    return {p.name for p in REPO_ROOT.iterdir() if p.is_dir() and p.name.startswith("clio-")}


def activity_signals(name):
    """Returns list of signals that suggest a tool is active."""
    d = REPO_ROOT / name
    signals = []
    if (d / "README.md").exists():
        signals.append("README")
    if any(d.rglob("*.timer")):
        signals.append("systemd-timer")
    py_files = list(d.rglob("*.py"))
    for f in py_files:
        try:
            if "__main__" in f.read_text(errors="ignore"):
                signals.append("__main__")
                break
        except OSError:
            pass
    if py_files and not signals:
        signals.append(f"{len(py_files)} .py-filer")
    return signals


def main():
    token = load_token()

    print("⏳ Hämtar cliotools-kort från Notion...")
    tools_with_ncc, tools_without_ncc = get_card_tools(token)
    card_all = set(tools_with_ncc) | set(tools_without_ncc)
    repo_dirs = get_repo_dirs()

    print(f"   Kort:  {len(tools_with_ncc)} med NCC + {len(tools_without_ncc)} utan = {len(card_all)} totalt")
    print(f"   Repo:  {len(repo_dirs)} clio-* kataloger\n")

    missing = sorted(repo_dirs - card_all)
    dead    = sorted(card_all - repo_dirs)
    ncc_candidates = sorted(
        t for t in tools_without_ncc
        if t in repo_dirs and activity_signals(t)
    )

    # ── 1. I repot men saknas på kortet ─────────────────────────────────────
    if missing:
        print("━━ 1. I repot men SAKNAS på kortet ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for t in missing:
            sig = activity_signals(t)
            label = ", ".join(sig) if sig else "inga aktivitetssignaler"
            print(f"  {t:<40}  [{label}]")
    else:
        print("✅ 1. Inga saknade — repot är fullt täckt av kortet")

    print()

    # ── 2. På kortet men saknas i repot ─────────────────────────────────────
    if dead:
        print("━━ 2. På kortet men SAKNAS i repot (döda rader) ━━━━━━━━━━━━━━━━━━━")
        for t in dead:
            ncc = tools_with_ncc.get(t, "")
            print(f"  {t:<40}  {ncc}")
    else:
        print("✅ 2. Inga döda rader — allt på kortet finns i repot")

    print()

    # ── 3. Utan NCC men verkar aktiva ────────────────────────────────────────
    if ncc_candidates:
        print("━━ 3. Utan NCC men aktiva (NCC-kandidater) ━━━━━━━━━━━━━━━━━━━━━━━━")
        for t in ncc_candidates:
            sig = activity_signals(t)
            print(f"  {t:<40}  [{', '.join(sig)}]")
    else:
        print("✅ 3. Inga uppenbara NCC-kandidater bland verktygen utan NCC")

    print()
    if not missing and not dead and not ncc_candidates:
        print("🎉 Registret verkar komplett och uppdaterat.")


if __name__ == "__main__":
    main()
