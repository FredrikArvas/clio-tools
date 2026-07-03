#!/usr/bin/env python3
"""
migrate_permissions_notion_to_db.py

Engångsmigrering: skriver kända behörigheter till state.db (tabell: permissions).

Notion-sidan (33d67...) är strukturellt trasig — bara 1 av ~10 rader syns via
API. Migreringen seedar därför från SEED_DATA (utläst ur Notion MCP 2026-05-23)
och kompletterar med vad API-hämtningen faktiskt returnerar.

Kör från clio-agent-mail-katalogen:
    python3 migrate_permissions_notion_to_db.py [--dry-run]

Idempotent — kan köras flera gånger utan att skapa dubletter.
"""
import argparse
import configparser
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate-permissions")

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR.parent / ".env")
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass

NOTION_API_VERSION = "2022-06-28"

# Känd data utläst ur Notion MCP 2026-05-23 (sida 33d67666d98a816bb207c33822425b0b).
# Notion-tabellens API-struktur är trasig (table_width=53, 1 synlig rad).
# Denna seed är primärkällan vid migrering.
SEED_DATA = [
    # email                                  level       accounts        kodord_read                                                                         kodord_rw
    ("fredrik@arvas.se",                     "admin",    "*",            "",                                                                                  ""),
    ("fredrik.arvas@capgemini.com",          "admin",    "*",            "",                                                                                  ""),
    ("ulrika@arvas.se",                      "write",    "krut,clio",    "",                                                                                  "iaf,uoutcoach,cliotools,kompis,aiab,arvashist,uapbok,udiet,frulrik,ledstat,gtk,famminverk,syvmet"),
    ("ulrika.arvas@arbetsformedlingen.se",   "write",    "krut,clio",    "",                                                                                  "iaf,uoutcoach,kompis,aiab,arvashist,uapbok,udiet,frulrik,ledstat,gtk,famminverk,syvmet"),
    ("stig@arvas.se",                        "coded",    "*",            "cliotools,kompis,arvashist",                                                        "arvashist,gsf75,famminverk"),
    ("carl.lindell@capgemini.com",           "po-pmo",   "ssf",          "iaf",                                                                               ""),
    ("maria.nyberg@capgemini.com",           "po-pmo",   "ssf",          "",                                                                                  ""),
    ("emil.alic@capgemini.com",              "coded",    "ssf",          "",                                                                                  ""),
    ("elin.tann@capgemini.com",              "coded",    "ssf",          "",                                                                                  ""),
    ("linda.stadhammar@capgemini.com",       "po-pmo",   "clio",         "",                                                                                  "liu"),
    ("jessica@leijer.se",                    "whitelisted", "*",         "",                                                                                  "jessica1"),
]


def fetch_notion_permissions(page_id: str, token: str) -> list[dict]:
    """
    Försöker hämta ytterligare poster från Notion via API.
    Returnerar lista med dicts. Kan returnera tom lista om API:t misslyckas.
    """
    if not token:
        logger.warning("Ingen Notion-token — hoppar över API-hämtning")
        return []
    try:
        import httpx
    except ImportError:
        logger.warning("httpx saknas — hoppar över Notion API-hämtning")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }

    def plain(rich_list):
        return "".join(r.get("plain_text", "") for r in rich_list).strip()

    users = []
    try:
        r = httpx.get(f"https://api.notion.com/v1/blocks/{page_id}/children",
                      headers=headers, timeout=30)
        r.raise_for_status()
        blocks = r.json().get("results", [])
    except Exception as e:
        logger.warning(f"Notion API-fel: {e}")
        return []

    for block in blocks:
        btype = block.get("type", "")
        if btype == "table":
            table_id = block["id"]
            try:
                rr = httpx.get(f"https://api.notion.com/v1/blocks/{table_id}/children",
                               headers=headers, timeout=30)
                rr.raise_for_status()
                row_blocks = rr.json().get("results", [])
            except Exception as e:
                logger.warning(f"Notion tabell-hämtning misslyckades: {e}")
                continue
            header_skipped = False
            for rb in row_blocks:
                if rb.get("type") != "table_row":
                    continue
                cells = rb.get("table_row", {}).get("cells", [])
                if not header_skipped:
                    header_skipped = True
                    continue
                if len(cells) < 2:
                    continue
                email = plain(cells[0]).lower()
                # Rensa markdown-länkformat [text](url) → email
                import re
                email_match = re.search(r"[\w.+-]+@[\w.-]+", email)
                if not email_match:
                    continue
                email = email_match.group(0)
                level    = plain(cells[1]).lower() if len(cells) > 1 else "whitelisted"
                accounts = plain(cells[2])         if len(cells) > 2 else "*"
                read_raw = plain(cells[3])         if len(cells) > 3 else ""
                rw_raw   = plain(cells[4])         if len(cells) > 4 else ""
                def clean(s):
                    s = s.strip()
                    return "" if s in ("—", "-", "") else s
                # Ignorera rader med för många celler (troligen sida-rest i trasig tabell)
                if len(cells) > 10:
                    logger.debug(f"  Hoppar trasig rad ({len(cells)} celler): {email}")
                    continue
                users.append({
                    "email":       email,
                    "level":       level,
                    "accounts":    clean(accounts) or "*",
                    "kodord_read": clean(read_raw),
                    "kodord_rw":   clean(rw_raw),
                })
                logger.debug(f"  API-rad: {email} | {level}")

        elif btype in ("code", "paragraph"):
            rich = (block.get("code", {}) if btype == "code"
                    else block.get("paragraph", {})).get("rich_text", [])
            text = plain(rich)
            import re
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 2:
                    continue
                email_match = re.search(r"[\w.+-]+@[\w.-]+", parts[0])
                if not email_match:
                    continue
                email      = email_match.group(0).lower()
                level      = parts[1].lower() if len(parts) > 1 else "whitelisted"
                accounts   = parts[2]         if len(parts) > 2 else "*"
                scope_raw  = parts[4]         if len(parts) > 4 else ""
                read_kws, rw_kws = [], []
                for k in scope_raw.split(","):
                    k = k.strip()
                    if not k:
                        continue
                    if ":" in k:
                        name, _, perm = k.partition(":")
                        (rw_kws if perm.strip() == "rw" else read_kws).append(name.strip())
                    else:
                        read_kws.append(k)
                users.append({
                    "email": email, "level": level,
                    "accounts": accounts.strip() or "*",
                    "kodord_read": ",".join(read_kws),
                    "kodord_rw":   ",".join(rw_kws),
                })

    return users


def run(dry_run: bool = False):
    # Bygg merged lista: seed + API (API-poster har prioritet vid konflikt)
    merged: dict[str, dict] = {}

    for email, level, accounts, kodord_read, kodord_rw in SEED_DATA:
        merged[email.lower()] = {
            "email": email.lower(), "level": level, "accounts": accounts,
            "kodord_read": kodord_read, "kodord_rw": kodord_rw,
        }

    config = configparser.ConfigParser(interpolation=None)
    config.read(BASE_DIR / "clio.config", encoding="utf-8")
    token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN", "")
    page_id = config.get("mail", "permissions_notion_page_id", fallback="")

    if page_id and token:
        api_users = fetch_notion_permissions(page_id, token)
        for u in api_users:
            merged[u["email"]] = u  # API-data överskriver seed
        if api_users:
            logger.info(f"API kompletterade med {len(api_users)} poster")

    users = list(merged.values())
    logger.info(f"Totalt {len(users)} poster att skriva")

    if dry_run:
        logger.info("DRY-RUN — skriver inte till DB")
        for u in users:
            logger.info(f"  {u['email']:<45} {u['level']:<12} accounts={u['accounts']}")
        return

    import state as st
    st.init_db()

    for u in users:
        st.upsert_permission(
            email=u["email"], level=u["level"], accounts=u["accounts"],
            kodord_read=u["kodord_read"], kodord_rw=u["kodord_rw"],
        )
        logger.info(f"  ✓ {u['email']:<45} {u['level']}")

    total = len(st.list_permissions())
    logger.info(f"Klar. {total} poster i state.db.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrera behörigheter → state.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
