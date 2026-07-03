#!/usr/bin/env python3
"""
ncc_verify.py — Jämför NCC-kodord i CLAUDE.md mot Notion masterlistan

Hittar:
  - Kodord i CLAUDE.md som saknas i Notion
  - Kodord i Notion som saknas i CLAUDE.md
  - Dubbletter (samma kodord, flera rader) i Notion

Kör:  python3 ncc_verify.py
      python3 ncc_verify.py --claude-md /annan/stig/CLAUDE.md

OBS: Kör helst lokalt (Windows) där ~/.claude/CLAUDE.md är aktuell,
     eller synka CLAUDE.md till servern först.
"""

import io
import os
import re
import sys
import argparse
from pathlib import Path
from collections import Counter

# Säkerställ UTF-8-output på Windows (cmd/PowerShell)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    sys.exit("Saknar 'requests'. Kör: pip install requests")

# ── Konfiguration ──────────────────────────────────────────────────────────────

NOTION_DB_ID   = "c4d630a1252d4d7fb73cd65535c07708"
NOTION_API_URL = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
NOTION_VERSION = "2022-06-28"
DEFAULT_CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"


def get_token() -> str:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        for env_candidate in [
            Path(__file__).parent / ".env",
            Path(__file__).parent.parent / ".env",
        ]:
            if env_candidate.exists():
                for line in env_candidate.read_text(encoding="utf-8").splitlines():
                    if line.startswith("NOTION_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
            if token:
                break
    if not token:
        sys.exit("NOTION_TOKEN saknas. Sätt env-variabeln eller lägg till i .env")
    return token


# ── Läs CLAUDE.md ─────────────────────────────────────────────────────────────

def extract_kodord_from_claude_md(path: Path) -> dict:
    """Returnerar {kodord: notionID} från NCC-blocket i CLAUDE.md.

    Matchar rader på formen:
        kodord:32hexchars
    Tillåter valfri prefix (backslash, blanktecken) och svenska tecken i kodordet.
    """
    if not path.exists():
        sys.exit(f"CLAUDE.md hittades inte: {path}")

    text = path.read_text(encoding="utf-8")
    kodord = {}
    # Flexibelt: kodordet kan innehålla svenska tecken, bindestreck, siffror
    # ID:t är alltid 32 hexadecimala tecken
    pattern = re.compile(
        r"^\s*\\?([A-Za-zåäöÅÄÖ0-9_-]+):([0-9a-fA-F]{32})\s*$",
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        kodord[m.group(1).lower()] = m.group(2).lower()
    return kodord


# ── Hämta Notion-rader ────────────────────────────────────────────────────────

def fetch_notion_rows(token: str) -> list:
    """Returnerar alla rader från masterlistan med kodord, projektnamn, status."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    rows = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        resp = requests.post(NOTION_API_URL, headers=headers, json=payload, timeout=15)
        if resp.status_code != 200:
            sys.exit(f"Notion API-fel {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        for page in data.get("results", []):
            props = page.get("properties", {})

            kodord_val = ""
            if "Kodord" in props:
                rich = props["Kodord"].get("rich_text", [])
                kodord_val = rich[0]["plain_text"].strip().lower() if rich else ""

            projektnamn = ""
            if "Projektnamn" in props:
                title = props["Projektnamn"].get("title", [])
                projektnamn = title[0]["plain_text"].strip() if title else ""

            status = ""
            if "Status" in props and props["Status"].get("select"):
                status = props["Status"]["select"]["name"]

            sfar = ""
            if "Sfär" in props and props["Sfär"].get("select"):
                sfar = props["Sfär"]["select"]["name"]

            nr = ""
            if "Nr" in props:
                rich = props["Nr"].get("rich_text", [])
                nr = rich[0]["plain_text"].strip() if rich else ""

            rows.append({
                "kodord":      kodord_val,
                "projektnamn": projektnamn,
                "status":      status,
                "sfar":        sfar,
                "nr":          nr,
                "url":         page.get("url", ""),
            })
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return rows


# ── Projektlista ──────────────────────────────────────────────────────────────

SFÄR_ORDNING = ["Familj", "Fredrik", "Ulrika", "AIAB", "Capgemini", "GSF"]


def _nr_sort_key(nr: str):
    """Sorterar Nr som 1.1, 2.3 numeriskt; tomma hamnar sist."""
    if not nr:
        return (999, 999)
    parts = nr.split(".")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except ValueError:
        return (999, 999)


def print_list(claude_kodord: dict, notion_rows: list) -> None:
    """Skriver ut alla projekt som en platt tabell: kodord | projektnamn | nr | sfär."""
    from datetime import date

    # Bygg uppslagstabell: kodord → rad (första rad vinner vid dubblett)
    notion_map = {}
    for r in notion_rows:
        k = r["kodord"]
        if k and k not in notion_map:
            notion_map[k] = r

    # Sortera: sfär-ordning → nr numeriskt → kodord alfabetiskt
    sfar_index = {s: i for i, s in enumerate(SFÄR_ORDNING)}

    def sort_key(r):
        si = sfar_index.get(r.get("sfar", ""), 99)
        return (si, _nr_sort_key(r["nr"]), r["kodord"])

    rader = sorted(notion_map.values(), key=sort_key)

    # Kolumnbredder
    w_kod  = max(len(r["kodord"])      for r in rader) + 2
    w_namn = max(len(r["projektnamn"]) for r in rader) + 2
    w_nr   = 6
    w_sfar = max(len(r.get("sfar", "")) for r in rader) + 2
    w_tot  = w_kod + w_namn + w_nr + w_sfar + 2

    print(f"\n{'═'*w_tot}")
    print(f"  Projektlista  —  {len(notion_map)} projekt  |  {date.today()}")
    print(f"{'═'*w_tot}")
    print(f"  {'Kodord':<{w_kod}} {'Projektnamn':<{w_namn}} {'Nr':<{w_nr}} {'Sfär':<{w_sfar}}")
    print(f"  {'─'*(w_tot-2)}")

    for r in rader:
        print(f"  {r['kodord']:<{w_kod}} {r['projektnamn']:<{w_namn}} {r['nr']:<{w_nr}} {r.get('sfar',''):<{w_sfar}}")

    # Kodord i CLAUDE.md utan Notion-rad
    ej_i_notion = sorted(k for k in claude_kodord if k not in notion_map)
    if ej_i_notion:
        print(f"\n  {'─'*(w_tot-2)}")
        print(f"  Ej i Notion: {', '.join(ej_i_notion)}")

    print(f"{'═'*w_tot}\n")


# ── Jämförelse & rapport ──────────────────────────────────────────────────────

def compare(claude_kodord: dict, notion_rows: list) -> None:
    notion_kodord_list = [r["kodord"] for r in notion_rows if r["kodord"]]
    notion_set  = set(notion_kodord_list)
    claude_set  = set(claude_kodord.keys())

    saknas_i_notion  = sorted(claude_set - notion_set)
    saknas_i_claude  = sorted(notion_set - claude_set)
    duplikater       = sorted({k for k, c in Counter(notion_kodord_list).items() if c > 1})

    w = 55
    print(f"\n{'═'*w}")
    print(f"  NCC-verifiering")
    print(f"  {len(claude_set)} kodord i CLAUDE.md  |  {len(notion_set)} unika i Notion  |  {len(notion_kodord_list)} rader totalt")
    print(f"{'═'*w}")

    if not saknas_i_notion and not saknas_i_claude and not duplikater:
        print("\n✅ Allt i sync — inga avvikelser.\n")
        return

    if saknas_i_notion:
        print(f"\n❌ Saknas i Notion ({len(saknas_i_notion)} st) — lägg till rader:")
        for k in saknas_i_notion:
            print(f"   {k}:{claude_kodord[k]}")

    if saknas_i_claude:
        print(f"\n⚠️  I Notion men ej i CLAUDE.md ({len(saknas_i_claude)} st):")
        for k in saknas_i_claude:
            row = next(r for r in notion_rows if r["kodord"] == k)
            print(f"   {k}  —  {row['projektnamn']}  [{row['status']}]")

    if duplikater:
        print(f"\n🔁 Dubbletter i Notion ({len(duplikater)} kodord) — ta bort överskott:")
        for k in duplikater:
            dupes = [r for r in notion_rows if r["kodord"] == k]
            for r in dupes:
                print(f"   {k}  —  {r['projektnamn']}")
                print(f"         {r['url']}")

    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Jämför NCC-kodord i CLAUDE.md mot Notion masterlistan"
    )
    parser.add_argument(
        "--claude-md",
        type=Path,
        default=DEFAULT_CLAUDE_MD,
        metavar="STI",
        help=f"Sökväg till CLAUDE.md (default: {DEFAULT_CLAUDE_MD})",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Visa alla projekt grupperade per Sfär (istället för diff)",
    )
    args = parser.parse_args()

    token         = get_token()
    claude_kodord = extract_kodord_from_claude_md(args.claude_md)
    notion_rows   = fetch_notion_rows(token)

    if args.list:
        print_list(claude_kodord, notion_rows)
    else:
        compare(claude_kodord, notion_rows)


if __name__ == "__main__":
    main()
