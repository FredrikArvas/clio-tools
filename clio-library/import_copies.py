#!/usr/bin/env python3
"""
Arvas Familjebibliotek — Sprint 4: Importera exemplar till Notion
Läser CSV från import/queue/, matchar BOK-ID via bokid_cache.json,
skapar poster i 📦 Exemplar-tabellen.

CSV-format (komma eller semikolon, UTF-8 BOM):
  Titel,Författare,Hyllplats,Språk,Hus,Format

Kräver att böckerna redan är importerade via import_books.py
(BOK-ID måste finnas i bokid_cache.json).

Användning:
  python import_copies.py --dry-run           # validera utan Notion-anrop
  python import_copies.py --dry-run --limit 5 # testa 5 rader
  python import_copies.py                     # kör mot Notion
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
from pathlib import Path

# ─── Konfig ─────────────────────────────────────────────────────────────────────
NOTION_API     = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
EXEMPLAR_DB    = "b57c75e9-4519-4a16-b2fb-60d29d2d7f53"

HERE           = Path(__file__).parent
QUEUE_DIR      = HERE / "import" / "queue"
IMPORTED_DIR   = HERE / "import" / "imported"
CACHE_FILE     = HERE / "bokid_cache.json"
LOG_FILE       = HERE / "import_copies.log"


# ─── Token ───────────────────────────────────────────────────────────────────────
def _load_token_from_env_file() -> str:
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
def normalize_key(titel: str, forfattare: str) -> str:
    t = re.sub(r'[^\w\s]', '', titel.lower()).strip()
    a = re.sub(r'[^\w\s]', '', forfattare.lower()).strip()
    t = re.sub(r'\s+', ' ', t)
    a = re.sub(r'\s+', ' ', a)
    return f"{t}||{a}"


# ─── Cache ────────────────────────────────────────────────────────────────────────
def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ─── CSV ─────────────────────────────────────────────────────────────────────────
def find_csv_files() -> list[Path]:
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


def get_all_exemplar(token: str) -> list[dict]:
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
    return pages


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


def build_exemplar_index(pages: list) -> tuple[dict, int]:
    """Bygger duplikat-index (bok_id||hus||hyllplats → page_id) och max EX-nummer."""
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


def create_exemplar(ex_id: str, bok_id: str, row: dict, token: str) -> str:
    props = {
        "EXEMPLAR-ID": {"title": [{"text": {"content": ex_id}}]},
        "BOK-ID": {"rich_text": [{"text": {"content": bok_id}}]},
    }
    if row.get("Hus"):
        props["Hus"] = {"select": {"name": row["Hus"]}}
    if row.get("Hyllplats"):
        props["Hyllplats"] = {"select": {"name": row["Hyllplats"]}}
    if row.get("Format"):
        props["Format"] = {"select": {"name": row["Format"]}}

    tillgång = row.get("Tillgång") or ("äger" if row.get("Format") == "physical" else "")
    if tillgång:
        props["Tillgång"] = {"select": {"name": tillgång}}

    if row.get("Tjänst"):
        props["Tjänst"] = {"select": {"name": row["Tjänst"]}}

    result = notion_request("POST", "/pages", token, {
        "parent": {"database_id": EXEMPLAR_DB},
        "properties": props,
    })
    return result["id"]


# ─── Main ─────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Importera exemplar till Notion (📦 Exemplar)")
    parser.add_argument("--dry-run", action="store_true", help="Validera utan Notion-anrop")
    parser.add_argument("--limit", type=int, default=0, help="Max antal rader (0 = alla)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay mellan API-anrop (s)")
    args = parser.parse_args()

    setup_logging()

    csv_files = find_csv_files()
    if not csv_files:
        logging.error("Inga CSV-filer i %s", QUEUE_DIR)
        logging.error("Lägg din CSV-fil där och kör om scriptet.")
        return

    logging.info("Hittade %d fil(er) i queue: %s", len(csv_files),
                 ", ".join(f.name for f in csv_files))

    cache = load_cache()
    logging.info("Cache: %d BOK-ID laddade", len(cache))

    token = os.environ.get("NOTION_TOKEN") or _load_token_from_env_file()
    seen = {}
    max_ex_num = 0

    if not args.dry_run:
        if not token:
            logging.error("Sätt NOTION_TOKEN i .env eller: export NOTION_TOKEN='secret_...'")
            return
        logging.info("Hämtar befintliga exemplar från Notion...")
        existing = get_all_exemplar(token)
        seen, max_ex_num = build_exemplar_index(existing)
        logging.info("  %d exemplar i Notion (max EX-nr: %d)", len(existing), max_ex_num)
    else:
        logging.info("DRY-RUN: ingen data skrivs till Notion")

    total_created = total_skipped = total_errors = total_no_bok_id = 0

    for csv_file in csv_files:
        logging.info("\n── Processar %s ──", csv_file.name)
        rows = load_csv(csv_file)
        logging.info("  %d rader laddade", len(rows))

        created = skipped = errors = no_bok_id = 0

        for i, row in enumerate(rows, 1):
            if args.limit and (created + skipped) >= args.limit:
                logging.info("  Limit nått: %d", args.limit)
                break

            titel = row.get("Titel", "").strip()
            forfattare = row.get("Författare", "").strip()

            if not titel:
                logging.warning("  Rad %d: Titel saknas — hoppar", i)
                errors += 1
                continue

            key = normalize_key(titel, forfattare)
            bok_id = cache.get(key)

            if not bok_id:
                logging.warning("  Rad %d: Inget BOK-ID för '%s' — importera boken först",
                                i, titel[:40])
                no_bok_id += 1
                continue

            hus = row.get("Hus", "")
            hyllplats = row.get("Hyllplats", "")

            if args.dry_run:
                logging.info("  [%d] DRY-RUN: %s → %s | %s %s",
                             i, bok_id, titel[:35], hus, hyllplats)
                created += 1
                continue

            dup_key = f"{bok_id}||{hus}||{hyllplats}"
            if dup_key in seen:
                logging.info("  [%d] Finns redan: %s @ %s %s", i, bok_id, hus, hyllplats)
                skipped += 1
                continue

            max_ex_num += 1
            ex_id = f"EX-{max_ex_num:04d}"
            try:
                create_exemplar(ex_id, bok_id, row, token)
                seen[dup_key] = ex_id
                logging.info("  [%d] Skapad: %s → %s (%s %s)", i, ex_id, bok_id, hus, hyllplats)
                created += 1
                time.sleep(args.delay)
            except Exception as e:
                logging.error("  [%d] Fel vid skapande av exemplar för '%s': %s",
                              i, titel[:40], e)
                errors += 1

        logging.info("  %s: skapad=%d, hoppade=%d, saknar BOK-ID=%d, fel=%d",
                     csv_file.name, created, skipped, no_bok_id, errors)
        total_created += created
        total_skipped += skipped
        total_errors += errors
        total_no_bok_id += no_bok_id

        if not args.dry_run and errors == 0 and not args.limit:
            IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%dT%H%M")
            dest = IMPORTED_DIR / f"{csv_file.stem}_{ts}{csv_file.suffix}"
            shutil.move(str(csv_file), str(dest))
            logging.info("  Flyttad → %s", dest.name)

    logging.info("\n── Sammanfattning ──")
    logging.info("  Skapade:       %d", total_created)
    logging.info("  Hoppade:       %d (duplikat)", total_skipped)
    logging.info("  Saknar BOK-ID: %d (importera boken först)", total_no_bok_id)
    logging.info("  Fel:           %d", total_errors)

    if args.dry_run:
        logging.info("\n  DRY-RUN — inget skrivet till Notion, fil ej flyttad.")


if __name__ == "__main__":
    main()
