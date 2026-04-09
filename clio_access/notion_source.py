"""
notion_source.py — läser behörighetsmatrisen från Notion

Format på Notion-sidan (code-block eller paragraph, # = kommentar):
  email | level | accounts | telegram_id

  email         : e-postadress (lowercase)
  level         : admin | write | coded | whitelisted
  accounts      : kommaseparerade account_key-värden, eller * för alla
  telegram_id   : numeriskt Telegram-användar-ID (valfritt)

Bakåtkompatibelt — rader utan telegram_id fungerar utan ändring.

Notering: använder httpx direkt (notion-client SDK trasigt på Python 3.14).
"""
import logging
import os
import re

import httpx

logger = logging.getLogger("clio-access")

NOTION_API_VERSION = "2022-06-28"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def _extract_plain_text(block: dict) -> str:
    """Extraherar ren text ur ett Notion-block (paragraph, bullet, code m.m.)."""
    btype = block.get("type", "")
    if btype == "code":
        rich = block.get("code", {}).get("rich_text", [])
    else:
        content = block.get(btype, {})
        rich = content.get("rich_text", [])
    return "".join(r.get("plain_text", "") for r in rich).strip()


def fetch_matrix(page_id: str, token: str) -> dict:
    """
    Hämtar behörighetsmatrisen från en Notion-sida.

    Returnerar dict:
      {
        "emails":      {email: {"level": str, "accounts": list[str], "telegram_id": int|None}},
        "telegram_ids": {telegram_id: email},   # omvänd mappning för snabb lookup
      }
    """
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    try:
        resp = httpx.get(url, headers=_headers(token), timeout=30)
        resp.raise_for_status()
        blocks = resp.json().get("results", [])
    except Exception as e:
        logger.error(f"[clio-access] Notion-hämtning misslyckades för {page_id}: {e}")
        return {"emails": {}, "telegram_ids": {}}

    emails: dict = {}
    telegram_ids: dict = {}

    for block in blocks:
        raw = _extract_plain_text(block)
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" not in line:
                continue

            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue

            email = parts[0].lower()
            if "@" not in email:
                continue

            level = parts[1].lower() if len(parts) > 1 else "whitelisted"
            accounts_raw = parts[2] if len(parts) > 2 else "*"
            tg_raw = parts[3].strip() if len(parts) > 3 else ""

            accounts = (
                []
                if accounts_raw.strip() in ("*", "")
                else [a.strip() for a in accounts_raw.split(",") if a.strip()]
            )

            tg_id: int | None = None
            if tg_raw and re.fullmatch(r"\d+", tg_raw):
                tg_id = int(tg_raw)

            entry = {"level": level, "accounts": accounts, "telegram_id": tg_id}
            emails[email] = entry
            if tg_id:
                telegram_ids[tg_id] = email

    logger.info(f"[clio-access] Matris hämtad: {len(emails)} poster")
    return {"emails": emails, "telegram_ids": telegram_ids}
