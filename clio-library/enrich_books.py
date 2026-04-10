#!/usr/bin/env python3
"""
Arvas Familjebibliotek — Google Books Enrichment Script
Berikar befintliga Notion-sidor med år, ISBN och förlag via Google Books API.

Användning:
  python enrich_books.py                        # kör normalt
  python enrich_books.py --dry-run              # testa utan att skriva till Notion
  python enrich_books.py --limit 10             # processa max 10 böcker
  python enrich_books.py --delay 0.5            # längre delay
  python enrich_books.py --lang sv              # filtrera på språk

Kräver: requests  (pip install requests)
        notion-client  (pip install notion-client)

Sätt din Notion API-nyckel som miljövariabel:
  export NOTION_TOKEN="secret_xxxx"
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ─── Banner ────────────────────────────────────────────────────────────────────
from clio_core.banner import print_banner
print_banner("Berikning")

# ─── .ENV LOADER ──────────────────────────────────────────
def _load_dotenv():
    """Läser .env-fil i script-mappen och sätter miljövariabler som inte redan är satta."""
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

_load_dotenv()

# ─── KONFIGURATION ────────────────────────────────────────
DATABASE_ID    = "94906f71-ee0f-4ff8-8c4b-28e822f6e670"
GOOGLE_API     = "https://www.googleapis.com/books/v1/volumes"
NOTION_API     = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

LOG_FILE       = Path(__file__).parent / "enrich_books.log"
PROGRESS_FILE  = Path(__file__).parent / "enrich_progress.json"


# ─── LOGGING ──────────────────────────────────────────────
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", "%H:%M:%S")

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(fmt)

    logger.addHandler(console)
    logger.addHandler(file_handler)


# ─── GOOGLE BOOKS LOOKUP ──────────────────────────────────
def lookup_google_books(title: str, author: str, lang: str = None) -> dict:
    """
    Slår upp bok via Google Books API.
    Returnerar dict med year, isbn, publisher eller tomt dict.
    """
    # Bygg query — prova med och utan författare
    queries = [
        f'intitle:"{title}" inauthor:"{author}"',
        f'intitle:"{title}"',
    ]

    api_key = os.environ.get("GOOGLE_API_KEY", "")
    logging.info("  API-nyckel: '%s...' (%s)", api_key[:10] if api_key else "(saknas)", "laddad" if api_key else "EJ LADDAD - låg kvot!")

    for query in queries:
        params = {"q": query, "maxResults": 1, "fields": "items(volumeInfo)"}
        if lang:
            params["langRestrict"] = lang
        if api_key:
            params["key"] = api_key

        url = f"{GOOGLE_API}?{urllib.parse.urlencode(params)}"
        logging.info("  URL (debug): %s", url[:120])
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ArvasLibrary/1.0", "Accept": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())

            items = data.get("items", [])
            if not items:
                continue

            info = items[0].get("volumeInfo", {})

            # Extrahera år
            published = info.get("publishedDate", "")
            year = int(published[:4]) if published and published[:4].isdigit() else None

            # Extrahera ISBN-13 (föredra) eller ISBN-10
            isbn = None
            for id_info in info.get("industryIdentifiers", []):
                if id_info.get("type") == "ISBN_13":
                    isbn = id_info["identifier"]
                    break
            if not isbn:
                for id_info in info.get("industryIdentifiers", []):
                    if id_info.get("type") == "ISBN_10":
                        isbn = id_info["identifier"]
                        break

            publisher = info.get("publisher")

            if year or isbn or publisher:
                logging.debug("Hittade '%s': år=%s, isbn=%s, förlag=%s", title, year, isbn, publisher)
                return {"year": year, "isbn": isbn, "publisher": publisher}

        except urllib.error.HTTPError as e:
            if e.code == 429:
                logging.warning("Rate limit från Google Books — väntar 5s...")
                time.sleep(5)
            else:
                logging.warning("HTTP %d för '%s': %s", e.code, title, e)
            break
        except Exception as e:
            logging.warning("Fel vid lookup av '%s': %s", title, e)
            break

    logging.debug("Ingen träff: '%s' av %s", title, author)
    return {}


# ─── NOTION API ───────────────────────────────────────────
def notion_request(method: str, path: str, token: str, body: dict = None) -> dict:
    url = f"{NOTION_API}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def get_pages_without_year(token: str, lang_filter: str = None) -> list:
    """Hämtar alla sidor i databasen som saknar År-fält."""
    pages = []
    cursor = None

    while True:
        body = {
            "filter": {"property": "År", "number": {"is_empty": True}},
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor
        if lang_filter:
            body["filter"] = {
                "and": [
                    {"property": "År", "number": {"is_empty": True}},
                    {"property": "Språk", "select": {"equals": lang_filter}},
                ]
            }

        result = notion_request("POST", f"/databases/{DATABASE_ID}/query", token, body)
        pages.extend(result.get("results", []))

        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")

    return pages


def update_notion_page(page_id: str, token: str, updates: dict) -> bool:
    """Uppdaterar en Notion-sida med år, isbn och/eller förlag."""
    props = {}

    if updates.get("year"):
        props["År"] = {"number": updates["year"]}
    if updates.get("isbn"):
        props["ISBN"] = {"rich_text": [{"text": {"content": updates["isbn"]}}]}
    if updates.get("publisher"):
        props["Förlag"] = {"rich_text": [{"text": {"content": updates["publisher"]}}]}

    if not props:
        return False

    try:
        notion_request("PATCH", f"/pages/{page_id}", token, {"properties": props})
        return True
    except Exception as e:
        logging.warning("Kunde inte uppdatera sida %s: %s", page_id, e)
        return False


# ─── PROGRESS ─────────────────────────────────────────────
def load_progress() -> set:
    if PROGRESS_FILE.exists():
        try:
            data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            return set(data.get("done_ids", []))
        except Exception:
            pass
    return set()


def save_progress(done_ids: set) -> None:
    PROGRESS_FILE.write_text(
        json.dumps({"done_ids": sorted(done_ids)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ─── MAIN ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Berika Arvas Familjebibliotek med Google Books metadata")
    parser.add_argument("--dry-run", action="store_true", help="Kör utan att skriva till Notion")
    parser.add_argument("--limit", type=int, default=0, help="Max antal böcker (0 = alla)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay mellan API-anrop (default: 0.5s)")
    parser.add_argument("--lang", type=str, default=None, help="Filtrera på språk: sv, en, etc.")
    args = parser.parse_args()

    setup_logging()

    token = os.environ.get("NOTION_TOKEN")
    if not token and not args.dry_run:
        logging.error("Sätt NOTION_TOKEN som miljövariabel: export NOTION_TOKEN='secret_...'")
        return

    logging.info("Hämtar sidor utan år från Notion...")
    if args.dry_run:
        logging.info("DRY-RUN: ingen data skrivs till Notion")
        pages = []  # Dry-run hoppar hämtningen
    else:
        pages = get_pages_without_year(token, args.lang)

    logging.info("Hittade %d sidor att berika", len(pages))

    done_ids = load_progress()
    enriched = 0
    skipped  = 0
    failed   = 0

    try:
        for i, page in enumerate(pages):
            page_id = page["id"]

            if page_id in done_ids:
                continue
            if args.limit and enriched >= args.limit:
                logging.info("Limit nått: %d böcker berikade.", args.limit)
                break

            props    = page.get("properties", {})
            title    = props.get("Titel", {}).get("title", [{}])[0].get("plain_text", "")
            author   = props.get("Författare", {}).get("rich_text", [{}])[0].get("plain_text", "")
            lang     = (props.get("Språk") or {}).get("select", {}).get("name", "")

            if not title:
                skipped += 1
                done_ids.add(page_id)
                continue

            logging.info("[%d/%d] Söker: %s av %s", i + 1, len(pages), title, author)

            result = lookup_google_books(title, author, lang if lang else None)
            time.sleep(args.delay)

            if result:
                if not args.dry_run:
                    success = update_notion_page(page_id, token, result)
                    if success:
                        enriched += 1
                        logging.info("  ✓ Uppdaterad: år=%s, isbn=%s, förlag=%s",
                                     result.get("year"), result.get("isbn"), result.get("publisher"))
                    else:
                        failed += 1
                else:
                    logging.info("  DRY: skulle uppdaterat med %s", result)
                    enriched += 1
            else:
                skipped += 1

            done_ids.add(page_id)

            if (i + 1) % 25 == 0 and not args.dry_run:
                save_progress(done_ids)
                logging.info("  Checkpoint sparad: %d/%d", i + 1, len(pages))

    except KeyboardInterrupt:
        logging.info("\nAvbrutet! Sparar checkpoint...")
        if not args.dry_run:
            save_progress(done_ids)

    # Rensa progress-fil om allt gick igenom
    if not args.dry_run and len(done_ids) >= len(pages):
        PROGRESS_FILE.unlink(missing_ok=True)

    logging.info("\n─── Sammanfattning ───────────────────────")
    logging.info("  Berikade:  %d", enriched)
    logging.info("  Hoppade:   %d (ingen träff)", skipped)
    logging.info("  Misslyckade: %d", failed)
    logging.info("  Totalt processerat: %d", enriched + skipped + failed)


if __name__ == "__main__":
    main()
