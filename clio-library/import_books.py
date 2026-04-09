#!/usr/bin/env python3
"""
Arvas Familjebibliotek — Sprint 3: Importera böcker till Notion
Läser bokregister*.csv från import/queue/, upsert mot 📚 Bokregister,
tilldelar BOK-ID lokalt och sparar bokid_cache.json.

CSV-format (sep=;, UTF-8 BOM):
  Titel;Författare;Författare_Enamn;Författare_Fnamn;Hyllplats;Språk;Format;Hus

Användning:
  python import_books.py --dry-run           # validera utan Notion-anrop
  python import_books.py --dry-run --limit 5 # testa 5 rader
  python import_books.py                     # kör mot Notion
  python import_books.py --delay 0.5         # långsammare API-anrop
"""

import argparse
import csv
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# ─── Banner ────────────────────────────────────────────────────────────────────

# ─── Konfig ────────────────────────────────────────────────────────────────────
DATA_SOURCE_ID = "a36a4f25-56ae-4001-a476-e5437acaa88e"
NOTION_API     = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
BOKREGISTER_DB = "94906f71-ee0f-4ff8-8c4b-28e822f6e670"

HERE           = Path(__file__).parent
QUEUE_DIR      = HERE / "import" / "queue"
IMPORTED_DIR   = HERE / "import" / "imported"
CACHE_FILE     = HERE / "bokid_cache.json"
LOG_FILE       = HERE / "import_books.log"

# Giltiga select-options (från Notion-schemat)
VALID_HYLLPLATS = {
    "A1","A2","A3","A4","A5","A6",
    "B1","B2","B3","B4","B5","B6",
    "C1","C2","C3","C4","C5","C6",
    "W1","W2","W3","Kök1","Kök2",
}
VALID_SPRAK  = {"sv","en","de","no","da"}
VALID_FORMAT = {"physical","ebook","audio"}
VALID_HUS    = {"FrUlleBo","Stigmansgården","Ekshäradsgatan","Annat"}


# ─── Token ──────────────────────────────────────────────────────────────────────
def _load_token_from_env_file() -> str:
    """Läser NOTION_TOKEN från .env i script-mappen om miljövariabel saknas."""
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("NOTION_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


# ─── Logging ────────────────────────────────────────────────────────────────────
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


# ─── Normalisering ──────────────────────────────────────────────────────────────
def normalize_key(titel: str, forfattare: str) -> str:
    """Normaliserad nyckel för fuzzy-match cache: lowercase, stripped."""
    t = re.sub(r'[^\w\s]', '', titel.lower()).strip()
    a = re.sub(r'[^\w\s]', '', forfattare.lower()).strip()
    t = re.sub(r'\s+', ' ', t)
    a = re.sub(r'\s+', ' ', a)
    return f"{t}||{a}"


def fuzzy_ratio(s1: str, s2: str) -> int:
    """Enkel token-sort-ratio utan externa beroenden."""
    if not s1 or not s2:
        return 0
    tokens1 = sorted(s1.lower().split())
    tokens2 = sorted(s2.lower().split())
    str1 = " ".join(tokens1)
    str2 = " ".join(tokens2)
    # Levenshtein-liknande similarity via SequenceMatcher
    from difflib import SequenceMatcher
    return int(SequenceMatcher(None, str1, str2).ratio() * 100)


# ─── Cache ──────────────────────────────────────────────────────────────────────
def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(cache: dict):
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def next_bok_id(cache: dict) -> str:
    """Nästa lediga BOK-ID baserat på cache."""
    if not cache:
        return "BOK-0001"
    max_num = 0
    for bok_id in cache.values():
        m = re.match(r'BOK-(\d+)', bok_id)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"BOK-{max_num + 1:04d}"


# ─── CSV ────────────────────────────────────────────────────────────────────────
def find_csv_files() -> list[Path]:
    """Listar alla CSV-filer i queue/ och låter användaren välja."""
    if not QUEUE_DIR.exists():
        return []
    all_files = sorted(QUEUE_DIR.glob("*.csv"))
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


def load_csv(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            rows.append({k.strip(): v.strip() if v else "" for k, v in row.items()})
    return rows


def validate_row(row: dict, idx: int) -> list[str]:
    """Validerar en rad mot Notion-schemat. Returnerar lista med varningar."""
    warnings = []
    if not row.get("Titel"):
        warnings.append(f"Rad {idx}: Titel saknas")
    if row.get("Hyllplats") and row["Hyllplats"] not in VALID_HYLLPLATS:
        warnings.append(f"Rad {idx}: Ogiltig Hyllplats '{row['Hyllplats']}'")
    if row.get("Språk") and row["Språk"] not in VALID_SPRAK:
        warnings.append(f"Rad {idx}: Ogiltigt Språk '{row['Språk']}'")
    if row.get("Format") and row["Format"] not in VALID_FORMAT:
        warnings.append(f"Rad {idx}: Ogiltigt Format '{row['Format']}'")
    if row.get("Hus") and row["Hus"] not in VALID_HUS:
        warnings.append(f"Rad {idx}: Ogiltigt Hus '{row['Hus']}'")
    return warnings


# ─── Notion API ─────────────────────────────────────────────────────────────────
def notion_request(method: str, path: str, token: str, body: dict = None) -> dict:
    import urllib.request
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


def get_all_notion_books(token: str) -> list[dict]:
    """Hämtar alla böcker från Notion för upsert-kontroll."""
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


def extract_notion_text(prop: dict) -> str:
    if not prop:
        return ""
    ptype = prop.get("type", "")
    if ptype == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
    return ""


def build_notion_index(pages: list) -> list[dict]:
    """Bygger index av befintliga Notion-böcker för fuzzy-match."""
    index = []
    for page in pages:
        props = page.get("properties", {})
        titel = extract_notion_text(props.get("Titel", {}))
        forfattare = extract_notion_text(props.get("Författare", {}))
        isbn = extract_notion_text(props.get("ISBN", {}))
        if titel:
            index.append({
                "page_id": page["id"],
                "titel": titel,
                "forfattare": forfattare,
                "isbn": isbn,
                "key": normalize_key(titel, forfattare),
            })
    return index


def patch_notion_page(page_id: str, row: dict, existing: dict, token: str) -> bool:
    """Uppdaterar tomma fält (Författare, ISBN) på en befintlig Notion-sida."""
    patch = {}
    if not existing.get("forfattare") and row.get("Författare"):
        patch["Författare"] = {"rich_text": [{"text": {"content": row["Författare"]}}]}
        if row.get("Författare_Enamn"):
            patch["Författare_Enamn"] = {"rich_text": [{"text": {"content": row["Författare_Enamn"]}}]}
        if row.get("Författare_Fnamn"):
            patch["Författare_Fnamn"] = {"rich_text": [{"text": {"content": row["Författare_Fnamn"]}}]}
    if not existing.get("isbn") and row.get("ISBN"):
        patch["ISBN"] = {"rich_text": [{"text": {"content": row["ISBN"]}}]}
    if patch:
        try:
            notion_request("PATCH", f"/pages/{page_id}", token, {"properties": patch})
            return True
        except Exception as e:
            logging.warning("PATCH misslyckades för %s: %s", page_id, e)
    return False


def find_existing(titel: str, forfattare: str, notion_index: list, threshold: int = 90):
    """Fuzzy-match mot befintliga böcker i Notion. Returnerar (page_id, score, entry) eller (None, 0, {})."""
    key = normalize_key(titel, forfattare)
    for entry in notion_index:
        if key == entry["key"]:
            return entry["page_id"], 100, entry

    best_score = 0
    best_id = None
    best_entry = {}
    for entry in notion_index:
        # Kombinerad titel+författare score
        t_score = fuzzy_ratio(titel, entry["titel"])
        a_score = fuzzy_ratio(forfattare, entry["forfattare"]) if forfattare and entry["forfattare"] else 0
        # Viktat: 70% titel, 30% författare
        combined = int(t_score * 0.7 + a_score * 0.3) if a_score else t_score
        if combined > best_score:
            best_score = combined
            best_id = entry["page_id"]
            best_entry = entry

    if best_score >= threshold:
        return best_id, best_score, best_entry
    return None, best_score, {}


def create_notion_page(row: dict, token: str) -> str:
    """Skapar en sida i Bokregistret. Returnerar page_id."""
    properties = {"Titel": row["Titel"]}

    for field in ["Författare", "Författare_Enamn", "Författare_Fnamn", "ISBN", "Förlag"]:
        if row.get(field):
            properties[field] = row[field]

    for field in ["Hyllplats", "Språk", "Format", "Hus"]:
        if row.get(field):
            properties[field] = row[field]

    if row.get("År"):
        try:
            properties["År"] = float(row["År"])
        except ValueError:
            pass

    result = notion_request("POST", "/pages", token, {
        "parent": {"database_id": BOKREGISTER_DB},
        "properties": _build_notion_properties(properties),
    })
    return result["id"]


def _build_notion_properties(props: dict) -> dict:
    """Konverterar platta properties till Notion API-format."""
    notion_props = {}
    for key, val in props.items():
        if key == "Titel":
            notion_props[key] = {"title": [{"text": {"content": val}}]}
        elif key in ("Författare", "Författare_Enamn", "Författare_Fnamn", "ISBN", "Förlag",
                      "Konceptuella begrepp", "Primärt tema"):
            notion_props[key] = {"rich_text": [{"text": {"content": val}}]}
        elif key in ("Hyllplats", "Språk", "Format", "Hus", "Funktion", "Skanningsprioritet"):
            notion_props[key] = {"select": {"name": val}}
        elif key == "År":
            notion_props[key] = {"number": val}
        elif key == "Världsbild":
            tags = json.loads(val) if isinstance(val, str) else val
            notion_props[key] = {"multi_select": [{"name": t} for t in tags]}
    return notion_props


# ─── Main ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Importera böcker till Notion (📚 Bokregister)")
    parser.add_argument("--dry-run", action="store_true", help="Validera utan Notion-anrop")
    parser.add_argument("--limit", type=int, default=0, help="Max antal rader (0 = alla)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay mellan API-anrop (s)")
    parser.add_argument("--threshold", type=int, default=90, help="Fuzzy-match tröskel (%%)")
    args = parser.parse_args()

    setup_logging()

    # Hitta CSV i queue
    csv_files = find_csv_files()
    if not csv_files:
        logging.error("Inga CSV-filer i %s", QUEUE_DIR)
        logging.error("Lägg din CSV-fil där och kör om scriptet.")
        return

    logging.info("Hittade %d fil(er) i queue: %s", len(csv_files),
                 ", ".join(f.name for f in csv_files))

    # Ladda cache
    cache = load_cache()
    logging.info("Cache: %d befintliga BOK-ID", len(cache))

    # Hämta Notion-index för upsert (om ej dry-run)
    token = os.environ.get("NOTION_TOKEN") or _load_token_from_env_file()
    notion_index = []

    if not args.dry_run:
        if not token:
            logging.error("Sätt NOTION_TOKEN i .env eller: export NOTION_TOKEN='secret_...'")
            return
        logging.info("Hämtar befintliga böcker från Notion...")
        existing_pages = get_all_notion_books(token)
        notion_index = build_notion_index(existing_pages)
        logging.info("  %d böcker i Notion", len(notion_index))

    # Processera varje CSV
    total_created = 0
    total_skipped = 0
    total_errors = 0
    total_warnings = 0

    for csv_file in csv_files:
        logging.info("\n── Processar %s ──", csv_file.name)
        rows = load_csv(csv_file)
        logging.info("  %d rader laddade", len(rows))

        created = skipped = errors = 0

        for i, row in enumerate(rows, 1):
            if args.limit and (created + skipped) >= args.limit:
                logging.info("  Limit nått: %d", args.limit)
                break

            # Validera
            warns = validate_row(row, i)
            if warns:
                for w in warns:
                    logging.warning("  %s", w)
                total_warnings += len(warns)
            if not row.get("Titel"):
                errors += 1
                continue

            titel = row["Titel"]
            forfattare = row.get("Författare", "")
            key = normalize_key(titel, forfattare)

            # BOK-ID: hämta från cache eller tilldela nytt
            if key in cache:
                bok_id = cache[key]
            else:
                bok_id = next_bok_id(cache)
                cache[key] = bok_id

            # Dry-run: logga och fortsätt
            if args.dry_run:
                logging.info("  [%d] DRY-RUN: %s | %s → %s", i, titel[:40], forfattare[:20], bok_id)
                created += 1
                continue

            # Upsert-check mot Notion
            if notion_index:
                existing_id, score, existing_entry = find_existing(titel, forfattare, notion_index, args.threshold)
                if existing_id:
                    patched = patch_notion_page(existing_id, row, existing_entry, token)
                    if patched:
                        logging.info("  [%d] PATCHad (score=%d%%): %s", i, score, titel[:40])
                        time.sleep(args.delay)
                    else:
                        logging.info("  [%d] Finns i Notion (score=%d%%): %s → %s",
                                     i, score, titel[:40], bok_id)
                    skipped += 1
                    continue

            # Skapa i Notion
            try:
                page_id = create_notion_page(row, token)
                # Lägg till i index för efterföljande upsert-check
                notion_index.append({
                    "page_id": page_id,
                    "titel": titel,
                    "forfattare": forfattare,
                    "key": key,
                })
                logging.info("  [%d] Skapad: %s → %s", i, titel[:40], bok_id)
                created += 1
                time.sleep(args.delay)
            except Exception as e:
                logging.error("  [%d] Fel vid skapande av '%s': %s", i, titel[:40], e)
                errors += 1

            # Checkpoint var 50:e rad
            if created % 50 == 0 and created > 0:
                save_cache(cache)
                logging.info("  Checkpoint: cache sparad (%d poster)", len(cache))

        logging.info("  %s: skapad=%d, hoppade=%d, fel=%d",
                     csv_file.name, created, skipped, errors)
        total_created += created
        total_skipped += skipped
        total_errors += errors

        # Flytta till imported (ej dry-run, ej limit-avbruten)
        if not args.dry_run and errors == 0 and not args.limit:
            ts = datetime.now().strftime("%Y%m%dT%H%M")
            dest = IMPORTED_DIR / f"{csv_file.stem}_{ts}{csv_file.suffix}"
            shutil.move(str(csv_file), str(dest))
            logging.info("  Flyttad → %s", dest.name)

    # Spara cache
    save_cache(cache)
    logging.info("\n── Sammanfattning ──")
    logging.info("  Skapade:   %d", total_created)
    logging.info("  Hoppade:   %d (redan i cache/Notion)", total_skipped)
    logging.info("  Fel:       %d", total_errors)
    logging.info("  Varningar: %d", total_warnings)
    logging.info("  Cache:     %d BOK-ID i %s", len(cache), CACHE_FILE.name)

    if args.dry_run:
        logging.info("\n  DRY-RUN — inget skrivet till Notion, fil ej flyttad.")


if __name__ == "__main__":
    main()
