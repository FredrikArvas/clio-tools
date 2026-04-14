"""
notion_data.py — hämtar vitlista, FAQ, kunskapsbas och Context Cards från Notion

Vitlista:      en sida med en e-postadress per rad (# = kommentar)
FAQ:           en sida med ## Fråga / brödtext Svar -struktur
Kunskapsbas:   Notion-databaser (komma-separerade ID:n i clio.config)
Context Cards: sidor länkade i databasens Context Card URL-kolumn

Allt cachas i 15 minuter för att minska API-anrop.
"""
import os
import re
import time
import logging
import httpx
from notion_client import Client

logger = logging.getLogger(__name__)

_cache: dict = {}
CACHE_TTL = 900  # 15 minuter


def _get_client() -> Client:
    token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_API_KEY (eller NOTION_TOKEN) saknas i miljövariabler")
    return Client(auth=token)


def _query_database(db_id: str) -> list:
    """
    Direkt httpx-anrop mot Notion database query-endpunkten.
    Kringgår notion-client SDK:s trasiga databases.query på Python 3.14.
    Hanterar pagination automatiskt.
    """
    token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN")
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    results = []
    body: dict = {}
    while True:
        resp = httpx.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        body["start_cursor"] = data["next_cursor"]
    return results


def _cached(key: str):
    if key in _cache:
        value, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return value
    return None


def _store(key: str, value):
    _cache[key] = (value, time.time())


def _extract_plain_text(block: dict) -> str:
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich = content.get("rich_text", [])
    return "".join(r.get("plain_text", "") for r in rich).strip()


def _url_to_page_id(url: str) -> str:
    """Extraherar Notion page-ID ur en URL och returnerar det med bindestreck."""
    match = re.search(r"([a-f0-9]{32})(?:[?#]|$)", url.replace("-", ""))
    if match:
        pid = match.group(1)
        return f"{pid[:8]}-{pid[8:12]}-{pid[12:16]}-{pid[16:20]}-{pid[20:]}"
    return ""


# ── Vitlista ──────────────────────────────────────────────────────────────────

def get_whitelist(page_id: str) -> set:
    """
    Hämtar vitlistan från en Notion-sida.
    Returnerar set av lowercase e-postadresser.
    """
    cache_key = f"whitelist:{page_id}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        client = _get_client()
        response = client.blocks.children.list(block_id=page_id)
        blocks = response.get("results", [])

        addresses: set = set()
        for block in blocks:
            text = _extract_plain_text(block)
            if not text:
                continue
            for part in text.splitlines():
                part = part.strip()
                if part and not part.startswith("#") and "@" in part:
                    addresses.add(part.lower())

        _store(cache_key, addresses)
        logger.info(f"Vitlista hämtad: {len(addresses)} adresser")
        return addresses

    except Exception as e:
        logger.error(f"Fel vid hämtning av vitlista från Notion: {e}")
        return set()


# ── FAQ ───────────────────────────────────────────────────────────────────────

def get_faq(page_id: str) -> list:
    """
    Hämtar FAQ från en Notion-sida.
    Returnerar lista av dict: [{"question": str, "answer": str}, ...]

    Struktur på Notion-sidan:
      ## Frågan
      Svaret i ett eller flera stycken.
    """
    cache_key = f"faq:{page_id}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        client = _get_client()
        response = client.blocks.children.list(block_id=page_id)
        blocks = response.get("results", [])

        faq_items = []
        current_question: str | None = None
        current_answer_parts: list = []

        for block in blocks:
            btype = block.get("type", "")
            text = _extract_plain_text(block)

            if btype == "heading_2" and text:
                if current_question and current_answer_parts:
                    faq_items.append({
                        "question": current_question,
                        "answer": " ".join(current_answer_parts),
                    })
                current_question = text
                current_answer_parts = []

            elif btype == "paragraph" and text and current_question:
                current_answer_parts.append(text)

        if current_question and current_answer_parts:
            faq_items.append({
                "question": current_question,
                "answer": " ".join(current_answer_parts),
            })

        _store(cache_key, faq_items)
        logger.info(f"FAQ hämtad: {len(faq_items)} poster")
        return faq_items

    except Exception as e:
        logger.error(f"Fel vid hämtning av FAQ från Notion: {e}")
        return []


# ── Kunskapsbas: databaser + Context Cards ────────────────────────────────────

def _prop_value(prop: dict) -> str:
    """Extraherar läsbart värde ur en Notion-sidpropertydict."""
    ptype = prop.get("type", "")
    val = prop.get(ptype)
    if val is None:
        return ""
    if ptype == "title":
        return "".join(r.get("plain_text", "") for r in val)
    if ptype in ("rich_text", "email", "phone_number"):
        if isinstance(val, list):
            return "".join(r.get("plain_text", "") for r in val)
        return str(val)
    if ptype == "select":
        return val.get("name", "") if val else ""
    if ptype == "multi_select":
        return ", ".join(o.get("name", "") for o in val)
    if ptype in ("number", "checkbox"):
        return str(val)
    if ptype == "url":
        return val or ""
    if ptype == "date":
        return val.get("start", "") if val else ""
    return ""


def _extract_page_text(page_id: str) -> str:
    """
    Hämtar alla block från en Notion-sida och returnerar läsbar text.
    Hanterar heading, paragraph, bullet, numbered, quote, callout, code, divider.
    """
    cache_key = f"page:{page_id}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        client = _get_client()
        response = client.blocks.children.list(block_id=page_id)
        blocks = response.get("results", [])

        lines = []
        for block in blocks:
            btype = block.get("type", "")
            text = _extract_plain_text(block)

            if not text:
                if btype == "divider":
                    lines.append("---")
                continue

            if btype == "heading_1":
                lines.append(f"# {text}")
            elif btype == "heading_2":
                lines.append(f"## {text}")
            elif btype == "heading_3":
                lines.append(f"### {text}")
            elif btype == "bulleted_list_item":
                lines.append(f"- {text}")
            elif btype == "numbered_list_item":
                lines.append(f"• {text}")
            elif btype == "quote":
                lines.append(f"> {text}")
            elif btype == "callout":
                lines.append(f"[!] {text}")
            elif btype == "code":
                lines.append(f"`{text}`")
            else:
                lines.append(text)

        result = "\n".join(lines)
        _store(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"Fel vid hämtning av sida {page_id}: {e}")
        return ""


def get_database_as_text(db_id: str, label: str = "") -> str:
    """
    Hämtar en Notion-databas och returnerar dess innehåll som
    läsbar text lämplig för Claude-prompter.
    """
    cache_key = f"db:{db_id}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        pages = _query_database(db_id)

        if not pages:
            result = f"[{label or db_id}: tom databas]"
            _store(cache_key, result)
            return result

        col_names = list(pages[0].get("properties", {}).keys())

        lines = [f"### {label or 'Databas'} ({len(pages)} poster)"]
        for page in pages:
            props = page.get("properties", {})
            parts = []
            for col in col_names:
                val = _prop_value(props.get(col, {}))
                if val:
                    parts.append(f"{col}: {val}")
            if parts:
                lines.append("- " + " | ".join(parts))

        result = "\n".join(lines)
        _store(cache_key, result)
        logger.info(f"Databas hämtad: {label or db_id} ({len(pages)} poster)")
        return result

    except Exception as e:
        logger.error(f"Fel vid hämtning av databas {db_id}: {e}")
        return ""


def get_project_index(db_id: str) -> list:
    """
    Returnerar en lista med dicts per projekt, inklusive kodord.
    Cachas 15 min. Används för semantisk routing.
    """
    cache_key = f"project_index:{db_id}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        pages = _query_database(db_id)

        index = []
        for page in pages:
            props = page.get("properties", {})
            context_url = _prop_value(props.get("Context Card URL", {}))
            page_id = _url_to_page_id(context_url) if context_url else ""
            index.append({
                "name":        _prop_value(props.get("Projektnamn", {})),
                "sfar":        _prop_value(props.get("Sfär", {})),
                "status":      _prop_value(props.get("Status", {})),
                "kodord":      _prop_value(props.get("Kodord", {})).lower().strip(),
                "context_url": context_url,
                "page_id":     page_id,
            })

        _store(cache_key, index)
        return index

    except Exception as e:
        logger.error(f"Fel vid hämtning av projektindex ({db_id}): {e}")
        return []


def get_relevant_context_cards(db_id: str, mail_subject: str, mail_body: str) -> str:
    """
    Matchar mailinnehållet mot projektkodord (primärt) och projektnamn (fallback).
    Kodord är precisa och korta — t.ex. 'ssf', 'peter', 'aiab'.

    För projekt utan Context Card (❌ Saknas) returneras en notering
    så att Clio vet att projektet finns men saknar underlag.
    """
    index = get_project_index(db_id)
    if not index:
        return ""

    needle = (mail_subject + " " + mail_body).lower()

    matched = []
    for proj in index:
        kodord = proj["kodord"]
        name   = proj["name"].lower()

        # Primär matchning: kodord (exakt ord i mailtext)
        if kodord and re.search(r'\b' + re.escape(kodord) + r'\b', needle):
            matched.append(proj)
            continue

        # Fallback: ord ur projektnamnet (minst 3 tecken, undviker korta ord)
        words = [w for w in re.split(r"[\s\-/×]+", name) if len(w) >= 3]
        if any(re.search(r'\b' + re.escape(w) + r'\b', needle) for w in words):
            matched.append(proj)

    if not matched:
        return ""

    parts = []
    for proj in matched:
        name   = proj["name"]
        sfar   = proj["sfar"]
        status = proj["status"]

        if proj["page_id"]:
            text = _extract_page_text(proj["page_id"])
            if text:
                header = f"### Context Card: {name} | {sfar} | {status}"
                parts.append(f"{header}\n{text}")
                logger.info(f"Routing → Context Card: {name} (kodord: {proj['kodord']})")
        else:
            # Projektet identifierat men saknar NCC
            parts.append(
                f"### Projekt identifierat (saknar Context Card): {name} | {sfar}\n"
                f"Status: {status}\n"
                f"Kodord: {proj['kodord']}\n"
                f"OBS: Ingen detaljerad projektinformation tillgänglig. "
                f"Bekräfta att frågan gäller detta projekt och låt Fredrik svara med detaljer."
            )
            logger.info(f"Routing → projekt utan NCC: {name} (kodord: {proj['kodord']})")

    return "\n\n---\n\n".join(parts)


def get_all_context_cards(db_id: str) -> str:
    """
    Hämtar alla Context Card-sidor länkade i databasens Context Card URL-kolumn.
    Varje kort cachas individuellt. Returnerar kombinerad text.
    """
    cache_key = f"context_cards:{db_id}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        pages = _query_database(db_id)

        card_texts = []
        for page in pages:
            props = page.get("properties", {})
            projektnamn = _prop_value(props.get("Projektnamn", {}))
            sfar = _prop_value(props.get("Sfär", {}))
            status = _prop_value(props.get("Status", {}))
            context_url = _prop_value(props.get("Context Card URL", {}))

            if not context_url:
                continue

            page_id = _url_to_page_id(context_url)
            if not page_id:
                continue

            page_text = _extract_page_text(page_id)
            if page_text:
                header = f"### Context Card: {projektnamn} | {sfar} | {status}"
                card_texts.append(f"{header}\n{page_text}")

        result = "\n\n---\n\n".join(card_texts)
        _store(cache_key, result)
        logger.info(f"Context Cards hämtade: {len(card_texts)} kort")
        return result

    except Exception as e:
        logger.error(f"Fel vid hämtning av Context Cards för {db_id}: {e}")
        return ""


def get_knowledge_context(config, mail_subject: str = "", mail_body: str = "") -> str:
    """
    Hämtar och sammanfogar kunskapskällor konfigurerade i clio.config.

    Om mail_subject/mail_body anges görs semantisk routing:
      → bara Context Cards för matchande projekt hämtas

    Annars laddas alla Context Cards (fallback, t.ex. vid test eller oklar kontext).

    Format: knowledge_notion_db_ids = db_id:Visningsnamn, db_id2:Namn2
    """
    raw = config.get("mail", "knowledge_notion_db_ids", fallback="").strip()
    if not raw:
        return ""

    db_entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not db_entries:
        return ""

    blocks = []
    for entry in db_entries:
        if ":" in entry:
            db_id, label = entry.split(":", 1)
        else:
            db_id, label = entry, ""
        db_id = db_id.strip()
        label = label.strip()

        db_text = get_database_as_text(db_id, label)
        if db_text:
            blocks.append(db_text)

        if mail_subject or mail_body:
            cards_text = get_relevant_context_cards(db_id, mail_subject, mail_body)
            source = "relevanta"
        else:
            cards_text = get_all_context_cards(db_id)
            source = "alla"

        if cards_text:
            blocks.append(f"## Context Cards ({source})\n\n{cards_text}")

    if not blocks:
        return ""

    return "## Kunskapsbas (aktuell data från Notion)\n\n" + "\n\n".join(blocks)


# ── Cache-hantering ───────────────────────────────────────────────────────────

# Behörighetsmatris hanteras av clio-access paketet (clio-tools/clio-access/).
# Se classifier._get_permission() och clio_access.AccessManager.


def append_to_context_card(page_id: str, text: str, author: str = "") -> None:
    """
    Appendar ett nytt stycke i slutet av en context card-sida i Notion.
    Används av /update-kommandot för att låta skrivbehöriga användare uppdatera projektkort.

    page_id : Notion-sidans ID (från projekt-indexets page_id-fält)
    text    : Brödtexten att lägga till
    author  : Avsändarens e-post (visas som inledning i stycket)
    """
    try:
        client = _get_client()
        content = f"[{author}]: {text.strip()}" if author else text.strip()
        client.blocks.children.append(
            block_id=page_id,
            children=[{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
            }]
        )
        # Rensa sidcachen så nästa läsning hämtar uppdaterad text
        _cache.pop(f"page:{page_id}", None)
        logger.info(f"Context card uppdaterad: {page_id} av {author or '?'}")
    except Exception as e:
        logger.error(f"Fel vid uppdatering av context card {page_id}: {e}")
        raise


def add_to_whitelist(page_id: str, email: str):
    """
    Lägger till en e-postadress i Notion-vitlistan och rensar den lokala cachen
    så att nästa poll hämtar den uppdaterade listan direkt.
    """
    try:
        client = _get_client()
        client.blocks.children.append(
            block_id=page_id,
            children=[{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": email.lower()}}]
                }
            }]
        )
        _cache.pop(f"whitelist:{page_id}", None)
        logger.info(f"Vitlistan uppdaterad: {email} tillagd")
    except Exception as e:
        logger.error(f"Fel vid tillägg i vitlistan: {e}")
        raise


def clear_cache():
    """Tömmer cacheminnet. Används i tester och vid reload."""
    _cache.clear()
