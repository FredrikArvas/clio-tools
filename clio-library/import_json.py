#!/usr/bin/env python3
"""
Arvas Familjebibliotek — JSON-import: Böcker + Exemplar i ett svep

Flöde för varje bok:
  1. Kolla lokalt (bokid_cache.json)          → hittad: gå till steg 5
  2. Fuzzy-match mot Bokregister_*.csv lokalt → hittad: spara i cache, gå till steg 5
  3. Fuzzy-match mot Notion Bokregistret      → hittad: spara i cache, gå till steg 5
  4. Skapa ny bok i Bokregistret              → spara BOK-ID i cache
  5. Kolla om exemplar redan finns            → finns: hoppa
  6. Skapa exemplar i Exemplar-tabellen

JSON-format (import/queue/*.json):
  {
    "_meta": { "import_instructions": [...], ... },
    "books": [
      { "titel": "...", "författare": "...", "hyllplats": "SG1",
        "språk": "sv", "format": "physical" },
      ...
    ]
  }

Fasta värden från _meta: Hus=Stigmansgården, Tillgång=äger

Användning:
  python import_json.py --dry-run
  python import_json.py --dry-run --limit 5
  python import_json.py
"""

import argparse
import csv
import json
import logging
import os
import re
import shutil
import time
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

# ─── Konfig ─────────────────────────────────────────────────────────────────────
NOTION_API     = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
BOKREGISTER_DB = "94906f71-ee0f-4ff8-8c4b-28e822f6e670"
EXEMPLAR_DB    = "b57c75e9-4519-4a16-b2fb-60d29d2d7f53"

HERE           = Path(__file__).parent
QUEUE_DIR      = HERE / "import" / "queue"
IMPORTED_DIR   = HERE / "import" / "imported"
CACHE_FILE     = HERE / "bokid_cache.json"
LOG_FILE       = HERE / "import_json.log"

DEFAULT_HUS      = "Stigmansgården"
DEFAULT_TILLGÅNG = "äger"


# ─── Token ───────────────────────────────────────────────────────────────────────
def _load_token() -> str:
    token = os.environ.get("NOTION_TOKEN", "")
    if token:
        return token
    for env_file in [HERE.parent / ".env", HERE / ".env"]:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("NOTION_TOKEN="):
                    return line.split("=", 1)[1].strip()
    return ""


# ─── Logging ─────────────────────────────────────────────────────────────────────
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", "%H:%M:%S")
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(ch)
    logger.addHandler(fh)


# ─── Normalisering ────────────────────────────────────────────────────────────────
def normalize(s: str) -> str:
    s = re.sub(r'[^\w\s]', '', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def cache_key(titel: str, forfattare: str) -> str:
    return f"{normalize(titel)}||{normalize(forfattare)}"


def fuzzy_score(a: str, b: str) -> int:
    return int(SequenceMatcher(None, normalize(a), normalize(b)).ratio() * 100)


# ─── Cache ────────────────────────────────────────────────────────────────────────
def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(cache: dict):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def next_bok_id(cache: dict) -> str:
    max_num = 0
    for v in cache.values():
        m = re.match(r'BOK-(\d+)', v)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"BOK-{max_num + 1:04d}"


# ─── Fil-val ─────────────────────────────────────────────────────────────────────
def find_json_files() -> list[Path]:
    if not QUEUE_DIR.exists():
        return []
    all_files = sorted(QUEUE_DIR.glob("*.json"))
    if not all_files:
        return []
    if len(all_files) == 1:
        return all_files

    print("\nFiler i import/queue:")
    for i, f in enumerate(all_files, 1):
        print(f"  {i}. {f.name}")
    print(f"  0. Alla ({len(all_files)} filer)")

    while True:
        val = input("\nVälj fil(er) att importera: ").strip()
        if val == "0":
            return all_files
        try:
            idx = int(val)
            if 1 <= idx <= len(all_files):
                return [all_files[idx - 1]]
        except ValueError:
            pass
        print(f"Ange ett nummer mellan 0 och {len(all_files)}.")


# ─── Notion API ──────────────────────────────────────────────────────────────────
def notion_request(method: str, path: str, token: str, body: dict = None) -> dict:
    url = f"{NOTION_API}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def extract_text(prop: dict) -> str:
    if not prop:
        return ""
    ptype = prop.get("type", "")
    if ptype == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    return ""


# ─── Steg 2: Lokal CSV-sökning ───────────────────────────────────────────────────
def load_local_bokregister() -> list[dict]:
    """Laddar senaste Bokregister_*.csv från script-mappen."""
    files = sorted(HERE.glob("Bokregister_*.csv"), reverse=True)
    if not files:
        return []
    latest = files[0]
    logging.info("Lokal bokregister-fil: %s (%d filer totalt)", latest.name, len(files))
    rows = []
    with open(latest, encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            rows.append({k.strip(): v.strip() if v else "" for k, v in row.items()})
    return rows


def build_local_index(rows: list[dict]) -> list[dict]:
    index = []
    for row in rows:
        titel = row.get("Titel", "").strip()
        forfattare = row.get("Författare", "").strip()
        if titel:
            index.append({"titel": titel, "forfattare": forfattare})
    return index


def find_in_local(titel: str, forfattare: str, index: list, threshold: int) -> dict | None:
    key = cache_key(titel, forfattare)
    for entry in index:
        if cache_key(entry["titel"], entry["forfattare"]) == key:
            return entry
    best_score, best_entry = 0, None
    for entry in index:
        t_score = fuzzy_score(titel, entry["titel"])
        a_score = fuzzy_score(forfattare, entry["forfattare"]) if forfattare and entry["forfattare"] else 0
        combined = int(t_score * 0.7 + a_score * 0.3) if a_score else t_score
        if combined > best_score:
            best_score, best_entry = combined, entry
    if best_score >= threshold:
        return best_entry
    return None


# ─── Steg 3: Sök i Notion ────────────────────────────────────────────────────────
def load_notion_books(token: str) -> list[dict]:
    """Hämtar alla böcker från Bokregistret."""
    pages, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        result = notion_request("POST", f"/databases/{BOKREGISTER_DB}/query", token, body)
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        time.sleep(0.2)
    return pages


def build_notion_index(pages: list) -> list[dict]:
    index = []
    for page in pages:
        props = page.get("properties", {})
        titel = extract_text(props.get("Titel", {}))
        forfattare = extract_text(props.get("Författare", {}))
        if titel:
            index.append({
                "page_id": page["id"],
                "titel": titel,
                "forfattare": forfattare,
            })
    return index


def find_in_notion(titel: str, forfattare: str, index: list, threshold: int) -> dict | None:
    """Fuzzy-match mot Notion-index. Returnerar entry eller None."""
    # Exakt nyckel-match först
    key = cache_key(titel, forfattare)
    for entry in index:
        if cache_key(entry["titel"], entry["forfattare"]) == key:
            return entry

    # Fuzzy: 70% titel + 30% författare
    best_score, best_entry = 0, None
    for entry in index:
        t_score = fuzzy_score(titel, entry["titel"])
        a_score = fuzzy_score(forfattare, entry["forfattare"]) if forfattare and entry["forfattare"] else 0
        combined = int(t_score * 0.7 + a_score * 0.3) if a_score else t_score
        if combined > best_score:
            best_score, best_entry = combined, entry

    if best_score >= threshold:
        return best_entry
    return None


# ─── Steg 3: Skapa bok ───────────────────────────────────────────────────────────
def create_book(book: dict, token: str) -> str:
    """Skapar en ny bok i Bokregistret. Returnerar page_id."""
    props = {
        "Titel": {"title": [{"text": {"content": book["titel"]}}]},
    }
    if book.get("författare"):
        props["Författare"] = {"rich_text": [{"text": {"content": book["författare"]}}]}
    if book.get("språk"):
        props["Språk"] = {"select": {"name": book["språk"]}}
    result = notion_request("POST", "/pages", token, {
        "parent": {"database_id": BOKREGISTER_DB},
        "properties": props,
    })
    return result["id"]


# ─── Steg 4–5: Exemplar ──────────────────────────────────────────────────────────
def load_exemplar_index(token: str) -> tuple[dict, int]:
    """Bygger duplikat-index och hittar max EX-nummer."""
    pages, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        result = notion_request("POST", f"/databases/{EXEMPLAR_DB}/query", token, body)
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        time.sleep(0.2)

    seen = {}
    max_num = 0
    for page in pages:
        props = page.get("properties", {})
        ex_id = extract_text(props.get("EXEMPLAR-ID", {}))
        bok_id = extract_text(props.get("BOK-ID", {}))
        hus = extract_text(props.get("Hus", {}))
        hyllplats = extract_text(props.get("Hyllplats", {}))
        if bok_id:
            seen[f"{bok_id}||{hus}||{hyllplats}"] = page["id"]
        m = re.match(r'EX-(\d+)', ex_id)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return seen, max_num


def create_exemplar(ex_id: str, bok_id: str, book: dict, hus: str, tillgång: str, token: str):
    props = {
        "EXEMPLAR-ID": {"title": [{"text": {"content": ex_id}}]},
        "BOK-ID": {"rich_text": [{"text": {"content": bok_id}}]},
        "Hus": {"select": {"name": hus}},
        "Tillgång": {"select": {"name": tillgång}},
    }
    if book.get("hyllplats"):
        props["Hyllplats"] = {"select": {"name": book["hyllplats"]}}
    if book.get("format"):
        props["Format"] = {"select": {"name": book["format"]}}

    notion_request("POST", "/pages", token, {
        "parent": {"database_id": EXEMPLAR_DB},
        "properties": props,
    })


# ─── Main ─────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="JSON-import: Böcker + Exemplar i ett svep (📚 + 📦)")
    parser.add_argument("--dry-run", action="store_true", help="Validera utan Notion-anrop")
    parser.add_argument("--limit", type=int, default=0, help="Max antal böcker (0 = alla)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay mellan API-anrop (s)")
    parser.add_argument("--threshold", type=int, default=85,
                        help="Fuzzy-match tröskel mot Notion (%%) (standard: 85)")
    args = parser.parse_args()

    setup_logging()

    json_files = find_json_files()
    if not json_files:
        logging.error("Inga JSON-filer i %s", QUEUE_DIR)
        logging.error("Lägg din JSON-fil där och kör om scriptet.")
        return

    cache = load_cache()
    logging.info("Cache: %d BOK-ID laddade", len(cache))

    token = _load_token()
    local_index = build_local_index(load_local_bokregister())
    logging.info("Lokal index: %d böcker", len(local_index))

    notion_index = []
    exemplar_seen = {}
    max_ex_num = 0

    if not args.dry_run:
        if not token:
            logging.error("Sätt NOTION_TOKEN i .env eller miljövariabel.")
            return
        logging.info("Hämtar Bokregister från Notion...")
        notion_index = build_notion_index(load_notion_books(token))
        logging.info("  %d böcker i Notion", len(notion_index))

        logging.info("Hämtar Exemplar från Notion...")
        exemplar_seen, max_ex_num = load_exemplar_index(token)
        logging.info("  %d exemplar i Notion (max EX-nr: %d)", len(exemplar_seen), max_ex_num)
    else:
        logging.info("DRY-RUN: ingen data skrivs till Notion")

    for json_file in json_files:
        logging.info("\n── Processar %s ──", json_file.name)
        data = json.loads(json_file.read_text(encoding="utf-8"))
        books = data.get("books", [])
        meta = data.get("_meta", {})

        hus = DEFAULT_HUS
        tillgång = DEFAULT_TILLGÅNG

        logging.info("  %d böcker i filen | Hus: %s | Tillgång: %s", len(books), hus, tillgång)

        created_books = matched_cache = matched_local = matched_notion = 0
        created_ex = skipped_ex = errors = 0

        for i, book in enumerate(books, 1):
            if args.limit and i > args.limit:
                logging.info("  Limit nått: %d", args.limit)
                break

            titel = book.get("titel", "").strip()
            forfattare = book.get("författare", "").strip()

            if not titel:
                logging.warning("  Rad %d: Titel saknas — hoppar", i)
                errors += 1
                continue

            # ── Steg 1: Kolla cache ──────────────────────────────────────────
            key = cache_key(titel, forfattare)
            bok_id = cache.get(key)
            source = ""

            if bok_id:
                matched_cache += 1
                source = "cache"
            elif local_index and (entry := find_in_local(titel, forfattare, local_index, args.threshold)):
                # ── Steg 2: Lokal CSV-match ─────────────────────────────────
                bok_id = next_bok_id(cache)
                cache[key] = bok_id
                matched_local += 1
                source = f"lokal ({entry['titel'][:30]})"
            elif not args.dry_run:
                # ── Steg 3: Sök i Notion ────────────────────────────────────
                entry = find_in_notion(titel, forfattare, notion_index, args.threshold)
                if entry:
                    bok_id = next_bok_id(cache)
                    cache[key] = bok_id
                    notion_index.append({
                        "page_id": entry["page_id"],
                        "titel": titel,
                        "forfattare": forfattare,
                    })
                    matched_notion += 1
                    source = f"Notion-match ({entry['titel'][:30]})"
                else:
                    # ── Steg 3: Skapa ny bok ────────────────────────────────
                    try:
                        page_id = create_book(book, token)
                        bok_id = next_bok_id(cache)
                        cache[key] = bok_id
                        notion_index.append({
                            "page_id": page_id,
                            "titel": titel,
                            "forfattare": forfattare,
                        })
                        created_books += 1
                        source = "ny bok"
                        time.sleep(args.delay)
                    except Exception as e:
                        logging.error("  [%d] Fel vid skapande av bok '%s': %s", i, titel[:40], e)
                        errors += 1
                        continue
            else:
                bok_id = f"DRY-{i:03d}"
                source = "dry-run (ingen cache-träff)"

            logging.info("  [%d] %s → %s | %s | %s %s",
                         i, titel[:35], bok_id, source,
                         hus, book.get("hyllplats", ""))

            if args.dry_run:
                created_ex += 1
                continue

            # ── Steg 4–5: Exemplar ──────────────────────────────────────────
            hyllplats = book.get("hyllplats", "")
            dup_key = f"{bok_id}||{hus}||{hyllplats}"

            if dup_key in exemplar_seen:
                logging.info("         Exemplar finns redan — hoppar")
                skipped_ex += 1
                continue

            max_ex_num += 1
            ex_id = f"EX-{max_ex_num:04d}"
            try:
                create_exemplar(ex_id, bok_id, book, hus, tillgång, token)
                exemplar_seen[dup_key] = ex_id
                logging.info("         Exemplar: %s skapad", ex_id)
                created_ex += 1
                time.sleep(args.delay)
            except Exception as e:
                logging.error("         Fel vid exemplar för '%s': %s", titel[:40], e)
                errors += 1

        save_cache(cache)

        logging.info("\n── Sammanfattning: %s ──", json_file.name)
        logging.info("  Böcker från cache:   %d", matched_cache)
        logging.info("  Matchad lokalt:      %d", matched_local)
        logging.info("  Matchad i Notion:    %d", matched_notion)
        logging.info("  Nya böcker skapade:  %d", created_books)
        logging.info("  Exemplar skapade:    %d", created_ex)
        logging.info("  Exemplar hoppade:    %d (duplikat)", skipped_ex)
        logging.info("  Fel:                 %d", errors)

        if not args.dry_run and errors == 0 and not args.limit:
            IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%dT%H%M")
            dest = IMPORTED_DIR / f"{json_file.stem}_{ts}{json_file.suffix}"
            shutil.move(str(json_file), str(dest))
            logging.info("  Flyttad → %s", dest.name)

    if args.dry_run:
        logging.info("\nDRY-RUN — inget skrivet till Notion, filer ej flyttade.")


if __name__ == "__main__":
    main()
