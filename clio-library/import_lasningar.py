#!/usr/bin/env python3
"""
Arvas Familjebibliotek — Sprint 3: Importera läsningar till Notion
Läser betyg*.csv från import/queue/, upsert mot ⭐ Betyg,
slår upp BOK-ID från bokid_cache.json via fuzzy-match.

CSV-format (sep=;, UTF-8 BOM):
  Variant A (BOK-ID redan satt):
    BOK-ID;Person;Betyg;Källa;Datum läst;Datum tillagt
  Variant B (titel+författare, lookup behövs):
    Titel;Författare;Person;Betyg;Källa;Datum läst;Datum tillagt

Användning:
  python import_lasningar.py --dry-run           # validera utan Notion-anrop
  python import_lasningar.py --dry-run --limit 5 # testa 5 rader
  python import_lasningar.py                     # kör mot Notion
"""

import argparse
import csv
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

# ─── Konfig ────────────────────────────────────────────────────────────────────
BETYG_DB       = "41009da8-a1e7-48e2-9ed9-7f3c9406ef93"
NOTION_API     = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

HERE           = Path(__file__).parent
QUEUE_DIR      = HERE / "import" / "queue"
IMPORTED_DIR   = HERE / "import" / "imported"
CACHE_FILE     = HERE / "bokid_cache.json"
LOG_FILE       = HERE / "import_lasningar.log"
NOMATCH_FILE   = HERE / "import_lasningar_nomatch.json"

VALID_PERSON = {"Ulrika", "Alice", "Johan", "Fredrik"}
VALID_KALLA  = {"Goodreads", "Storytel", "Manuellt"}


# ─── Token ──────────────────────────────────────────────────────────────────────
def _load_token_from_env_file() -> str:
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


# ─── Normalisering & fuzzy ──────────────────────────────────────────────────────
def normalize_key(titel: str, forfattare: str) -> str:
    t = re.sub(r'[^\w\s]', '', titel.lower()).strip()
    a = re.sub(r'[^\w\s]', '', forfattare.lower()).strip()
    t = re.sub(r'\s+', ' ', t)
    a = re.sub(r'\s+', ' ', a)
    return f"{t}||{a}"


def fuzzy_ratio(s1: str, s2: str) -> int:
    if not s1 or not s2:
        return 0
    tokens1 = sorted(s1.lower().split())
    tokens2 = sorted(s2.lower().split())
    return int(SequenceMatcher(None, " ".join(tokens1), " ".join(tokens2)).ratio() * 100)


def lookup_bokid(titel: str, forfattare: str, cache: dict, threshold: int = 90) -> tuple:
    """Slå upp BOK-ID från cache. Returnerar (bok_id, score) eller (None, best_score)."""
    key = normalize_key(titel, forfattare)
    if key in cache:
        return cache[key], 100

    best_score = 0
    best_id = None
    for cache_key, bok_id in cache.items():
        cache_titel, cache_forf = cache_key.split("||", 1) if "||" in cache_key else (cache_key, "")
        t_score = fuzzy_ratio(titel, cache_titel)
        a_score = fuzzy_ratio(forfattare, cache_forf) if forfattare and cache_forf else 0
        combined = int(t_score * 0.7 + a_score * 0.3) if a_score else t_score
        if combined > best_score:
            best_score = combined
            best_id = bok_id

    if best_score >= threshold:
        return best_id, best_score
    return None, best_score


# ─── Cache ──────────────────────────────────────────────────────────────────────
def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ─── CSV ────────────────────────────────────────────────────────────────────────
def find_csv_files() -> list:
    if not QUEUE_DIR.exists():
        return []
    return sorted(QUEUE_DIR.glob("betyg*.csv"))


def load_csv(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append({k.strip(): v.strip() if v else "" for k, v in row.items()})
    return rows


def validate_row(row: dict, idx: int) -> list[str]:
    warnings = []
    if row.get("Person") and row["Person"] not in VALID_PERSON:
        warnings.append(f"Rad {idx}: Ogiltig Person '{row['Person']}'")
    if row.get("Källa") and row["Källa"] not in VALID_KALLA:
        warnings.append(f"Rad {idx}: Ogiltig Källa '{row['Källa']}'")
    if row.get("Betyg"):
        try:
            b = float(row["Betyg"])
            if b < 1 or b > 5:
                warnings.append(f"Rad {idx}: Betyg utanför 1-5: {b}")
        except ValueError:
            warnings.append(f"Rad {idx}: Ogiltigt Betyg '{row['Betyg']}'")
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


def get_existing_betyg(token: str) -> set:
    """Hämtar alla befintliga Person+BOK-ID+Datum-kombinationer för upsert-check."""
    existing = set()
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        result = notion_request("POST", f"/databases/{BETYG_DB}/query", token, body)
        for page in result.get("results", []):
            props = page.get("properties", {})
            bok_id = _extract_title(props.get("BOK-ID", {}))
            person = _extract_select(props.get("Person", {}))
            datum = _extract_date(props.get("Datum tillagt", {}))
            if bok_id and person:
                existing.add(f"{person}|{bok_id}|{datum}")
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        time.sleep(0.2)
    return existing


def _extract_title(prop: dict) -> str:
    if not prop:
        return ""
    return "".join(t.get("plain_text", "") for t in prop.get("title", []))


def _extract_select(prop: dict) -> str:
    if not prop or not prop.get("select"):
        return ""
    return prop["select"].get("name", "")


def _extract_date(prop: dict) -> str:
    if not prop or not prop.get("date"):
        return ""
    return prop["date"].get("start", "") or ""


def create_betyg_page(bok_id: str, row: dict, token: str) -> str:
    """Skapar en sida i Betygstabellen."""
    properties = {
        "BOK-ID": {"title": [{"text": {"content": bok_id}}]},
    }

    if row.get("Person") and row["Person"] in VALID_PERSON:
        properties["Person"] = {"select": {"name": row["Person"]}}

    if row.get("Betyg"):
        try:
            properties["Betyg"] = {"number": float(row["Betyg"])}
        except ValueError:
            pass

    if row.get("Källa") and row["Källa"] in VALID_KALLA:
        properties["Källa"] = {"select": {"name": row["Källa"]}}

    if row.get("Datum läst"):
        properties["Datum läst"] = {"date": {"start": row["Datum läst"]}}

    if row.get("Datum tillagt"):
        properties["Datum tillagt"] = {"date": {"start": row["Datum tillagt"]}}

    result = notion_request("POST", "/pages", token, {
        "parent": {"database_id": BETYG_DB},
        "properties": properties,
    })
    return result["id"]


# ─── Main ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Importera läsningar till Notion (⭐ Betyg)")
    parser.add_argument("--dry-run", action="store_true", help="Validera utan Notion-anrop")
    parser.add_argument("--limit", type=int, default=0, help="Max antal rader (0 = alla)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay mellan API-anrop (s)")
    parser.add_argument("--threshold", type=int, default=90, help="Fuzzy-match tröskel (%%)")
    args = parser.parse_args()

    setup_logging()

    csv_files = find_csv_files()
    if not csv_files:
        logging.error("Inga betyg*.csv i %s", QUEUE_DIR)
        return

    logging.info("Hittade %d fil(er) i queue: %s", len(csv_files),
                 ", ".join(f.name for f in csv_files))

    cache = load_cache()
    if not cache:
        logging.warning("bokid_cache.json är tom! Kör import_books.py först.")
    logging.info("Cache: %d BOK-ID laddade", len(cache))

    token = os.environ.get("NOTION_TOKEN") or _load_token_from_env_file()
    existing_betyg = set()

    if not args.dry_run:
        if not token:
            logging.error("Sätt NOTION_TOKEN i .env eller: export NOTION_TOKEN='secret_...'")
            return
        logging.info("Hämtar befintliga betyg från Notion...")
        existing_betyg = get_existing_betyg(token)
        logging.info("  %d unika Person+BOK-ID+Datum i Notion", len(existing_betyg))

    total_created = 0
    total_skipped = 0
    total_nomatch = 0
    total_errors = 0
    nomatch_list = []

    for csv_file in csv_files:
        logging.info("\n── Processar %s ──", csv_file.name)
        rows = load_csv(csv_file)
        logging.info("  %d rader laddade", len(rows))

        # Detektera CSV-variant
        has_titel = "Titel" in rows[0] if rows else False
        has_bokid = "BOK-ID" in rows[0] if rows else False
        if has_titel:
            logging.info("  Variant B: Titel+Författare → BOK-ID lookup")
        elif has_bokid:
            logging.info("  Variant A: BOK-ID direkt i CSV")
        else:
            logging.error("  CSV saknar både Titel och BOK-ID kolumner!")
            continue

        created = skipped = nomatch = errors = 0

        for i, row in enumerate(rows, 1):
            if args.limit and (created + skipped + nomatch) >= args.limit:
                logging.info("  Limit nått: %d", args.limit)
                break

            warns = validate_row(row, i)
            for w in warns:
                logging.warning("  %s", w)

            # Bestäm BOK-ID
            bok_id = row.get("BOK-ID", "").strip()

            if not bok_id and has_titel:
                titel = row.get("Titel", "")
                forfattare = row.get("Författare", "")
                if not titel:
                    logging.warning("  [%d] Titel saknas — hoppar", i)
                    errors += 1
                    continue
                bok_id, score = lookup_bokid(titel, forfattare, cache, args.threshold)
                if not bok_id:
                    nomatch += 1
                    nomatch_list.append({
                        "rad": i,
                        "titel": titel,
                        "forfattare": forfattare,
                        "best_score": score,
                    })
                    logging.debug("  [%d] Ingen match: %s (bästa: %d%%)", i, titel[:40], score)
                    continue
                logging.debug("  [%d] Lookup: %s → %s (%d%%)", i, titel[:30], bok_id, score)

            if not bok_id:
                logging.warning("  [%d] BOK-ID saknas och kan inte slås upp", i)
                errors += 1
                continue

            person = row.get("Person", "")
            datum_tillagt = row.get("Datum tillagt", "")

            # Upsert-check
            upsert_key = f"{person}|{bok_id}|{datum_tillagt}"
            if upsert_key in existing_betyg:
                skipped += 1
                logging.debug("  [%d] Finns redan: %s", i, upsert_key)
                continue

            if args.dry_run:
                betyg_val = row.get("Betyg", "?")
                logging.info("  [%d] DRY-RUN: %s | %s | betyg=%s | %s",
                             i, bok_id, person, betyg_val,
                             row.get("Källa", ""))
                existing_betyg.add(upsert_key)
                created += 1
                continue

            # Skapa i Notion
            try:
                page_id = create_betyg_page(bok_id, row, token)
                existing_betyg.add(upsert_key)
                logging.info("  [%d] Skapad: %s | %s | betyg=%s",
                             i, bok_id, person, row.get("Betyg", ""))
                created += 1
                time.sleep(args.delay)
            except Exception as e:
                logging.error("  [%d] Fel: %s", i, e)
                errors += 1

        logging.info("  %s: skapad=%d, hoppade=%d, no-match=%d, fel=%d",
                     csv_file.name, created, skipped, nomatch, errors)
        total_created += created
        total_skipped += skipped
        total_nomatch += nomatch
        total_errors += errors

        if not args.dry_run and errors == 0 and not args.limit:
            ts = datetime.now().strftime("%Y%m%dT%H%M")
            dest = IMPORTED_DIR / f"{csv_file.stem}_{ts}{csv_file.suffix}"
            shutil.move(str(csv_file), str(dest))
            logging.info("  Flyttad → %s", dest.name)

    # Spara no-match-lista
    if nomatch_list:
        NOMATCH_FILE.write_text(
            json.dumps(nomatch_list, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    logging.info("\n── Sammanfattning ──")
    logging.info("  Skapade:   %d", total_created)
    logging.info("  Hoppade:   %d (upsert)", total_skipped)
    logging.info("  No-match:  %d (se %s)", total_nomatch, NOMATCH_FILE.name)
    logging.info("  Fel:       %d", total_errors)

    if nomatch_list:
        logging.info("\n  Titlar utan BOK-ID-match (granska manuellt):")
        for r in nomatch_list[:15]:
            logging.info("    Rad %d: %s av %s (bästa: %d%%)",
                         r["rad"], r["titel"][:40], r["forfattare"][:20], r["best_score"])
        if len(nomatch_list) > 15:
            logging.info("    ... och %d till", len(nomatch_list) - 15)

    if args.dry_run:
        logging.info("\n  DRY-RUN — inget skrivet till Notion, fil ej flyttad.")


if __name__ == "__main__":
    main()
