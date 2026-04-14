"""
notion_source.py — läser och skriver behörighetsmatrisen från Notion

Format på Notion-sidan (code-block eller paragraph, # = kommentar):
  email | level | accounts | telegram_id | kodord_scope

  email         : e-postadress (lowercase)
  level         : admin | write | coded | whitelisted
  accounts      : kommaseparerade account_key-värden, eller * för alla
  telegram_id   : numeriskt Telegram-användar-ID (valfritt)
  kodord_scope  : kommaseparerade kodord användaren får använda, tom = alla (valfritt)

Bakåtkompatibelt — rader utan kodord_scope fungerar utan ändring.

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
        "emails": {
          email: {
            "level": str,
            "accounts": list[str],
            "telegram_id": int|None,
            "kodord_scope": list[str],   # tom lista = alla kodord tillåtna
          }
        },
        "telegram_ids": {telegram_id: email},   # omvänd mappning för snabb lookup
        "blocks": list[dict],                   # råa Notion-block (för update_user_permission)
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
            scope_raw = parts[4].strip() if len(parts) > 4 else ""

            accounts = (
                []
                if accounts_raw.strip() in ("*", "")
                else [a.strip() for a in accounts_raw.split(",") if a.strip()]
            )

            tg_id: int | None = None
            if tg_raw and re.fullmatch(r"\d+", tg_raw):
                tg_id = int(tg_raw)

            kodord_scope = (
                [k.strip() for k in scope_raw.split(",") if k.strip()]
                if scope_raw else []
            )

            entry = {
                "level": level,
                "accounts": accounts,
                "telegram_id": tg_id,
                "kodord_scope": kodord_scope,
            }
            emails[email] = entry
            if tg_id:
                telegram_ids[tg_id] = email

    logger.info(f"[clio-access] Matris hämtad: {len(emails)} poster")
    return {"emails": emails, "telegram_ids": telegram_ids, "blocks": blocks}


def _build_row(
    email: str,
    level: str,
    accounts: list[str],
    tg_id: str,
    kodord_scope: list[str],
) -> str:
    """Bygger en pipe-separerad permission-rad."""
    acc_str = ",".join(accounts) if accounts else "*"
    scope_str = ",".join(kodord_scope) if kodord_scope else ""
    return f"{email} | {level} | {acc_str} | {tg_id} | {scope_str}"


def _update_block(block_id: str, block_type: str, new_text: str, token: str) -> None:
    """Uppdaterar texten i ett befintligt Notion-block (paragraph eller code)."""
    url = f"https://api.notion.com/v1/blocks/{block_id}"
    rich = [{"type": "text", "text": {"content": new_text}}]
    if block_type == "code":
        body: dict = {"code": {"rich_text": rich, "language": "plain text"}}
    else:
        body = {"paragraph": {"rich_text": rich}}
    resp = httpx.patch(url, headers=_headers(token), json=body, timeout=30)
    resp.raise_for_status()


def _append_block(page_id: str, text: str, token: str) -> None:
    """Lägger till ett nytt paragraph-block i slutet av sidan."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    body = {
        "children": [{
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
        }]
    }
    resp = httpx.patch(url, headers=_headers(token), json=body, timeout=30)
    resp.raise_for_status()


def update_user_permission(
    page_id: str,
    token: str,
    email: str,
    *,
    level: str | None = None,
    accounts: list[str] | None = None,
    kodord_scope: list[str] | None = None,
) -> bool:
    """
    Uppdaterar eller lägger till en rad i permission-matrisen i Notion.

    Parametrar utan värde (None) behåller nuvarande värde.
    Returnerar True om lyckades, kastar vid fel.
    """
    email = email.lower().strip()

    # Hämta befintliga block
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    resp = httpx.get(url, headers=_headers(token), timeout=30)
    resp.raise_for_status()
    blocks = resp.json().get("results", [])

    # Sök igenom block efter användarens rad
    found_block_id: str | None = None
    found_block_type: str = "paragraph"
    current: dict = {}

    for block in blocks:
        raw = _extract_plain_text(block)
        lines = raw.splitlines()
        new_lines = []
        changed = False

        for line in lines:
            stripped = line.strip()
            if "|" in stripped:
                parts = [p.strip() for p in stripped.split("|")]
                if parts[0].lower() == email:
                    # Spara nuvarande värden
                    current = {
                        "level":        parts[1] if len(parts) > 1 else "whitelisted",
                        "accounts_str": parts[2] if len(parts) > 2 else "*",
                        "tg_id":        parts[3] if len(parts) > 3 else "",
                        "scope_str":    parts[4] if len(parts) > 4 else "",
                    }
                    # Bygg ny rad med uppdaterade fält
                    new_lvl = level if level is not None else current["level"]
                    if accounts is not None:
                        new_acc = accounts
                    else:
                        acc_raw = current["accounts_str"]
                        new_acc = [] if acc_raw in ("*", "") else [a.strip() for a in acc_raw.split(",") if a.strip()]
                    new_tg = current["tg_id"]
                    if kodord_scope is not None:
                        new_scope = kodord_scope
                    else:
                        s = current["scope_str"]
                        new_scope = [k.strip() for k in s.split(",") if k.strip()] if s else []

                    line = _build_row(email, new_lvl, new_acc, new_tg, new_scope)
                    changed = True
                    found_block_id = block["id"]
                    found_block_type = block.get("type", "paragraph")
            new_lines.append(line)

        if changed:
            _update_block(found_block_id, found_block_type, "\n".join(new_lines), token)
            logger.info(f"[clio-access] Behörighet uppdaterad för {email}")
            return True

    # Användaren finns inte i matrisen — lägg till ny rad
    new_lvl = level or "coded"
    new_acc = accounts if accounts is not None else []
    new_tg = ""
    new_scope = kodord_scope if kodord_scope is not None else []
    new_line = _build_row(email, new_lvl, new_acc, new_tg, new_scope)
    _append_block(page_id, new_line, token)
    logger.info(f"[clio-access] Ny behörighetsrad tillagd för {email}")
    return True
