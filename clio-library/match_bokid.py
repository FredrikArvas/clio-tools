#!/usr/bin/env python3
"""
Arvas Familjebibliotek — BOK-ID Matchningsskript
Fuzzy-matchar titlar i Betygstabellen (⭐ Betyg) mot Bokregistret (📚 Bokregister)
och skriver BOK-ID på träffar ≥ 90%.

Förutsättningar:
  pip install thefuzz python-Levenshtein requests

Konfiguration:
  export NOTION_TOKEN="secret_xxxx"

Användning:
  python match_bokid.py                  # kör mot Notion (live)
  python match_bokid.py --dry-run        # visa matchningar utan att skriva
  python match_bokid.py --threshold 85   # lägre tröskel (default: 90)
  python match_bokid.py --limit 20       # testa på 20 rader
  python match_bokid.py --csv-mode       # matcha lokala CSV-filer istället
"""

import argparse
import json
import logging
import os
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path

# ─── Konfig ────────────────────────────────────────────────────────────────────
BOKREGISTER_DB  = "94906f71-ee0f-4ff8-8c4b-28e822f6e670"
BETYG_DB        = "41009da8-a1e7-48e2-9ed9-7f3c9406ef93"
NOTION_API      = "https://api.notion.com/v1"
NOTION_VERSION  = "2022-06-28"

LOG_FILE        = Path(__file__).parent / "match_bokid.log"
PROGRESS_FILE   = Path(__file__).parent / "match_progress.json"
RESULT_FILE     = Path(__file__).parent / "match_results.json"


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
def normalize(text: str) -> str:
    """Normalisera titel för jämförelse: lowercase, ta bort skiljetecken och extra mellanslag."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'\s*[:\-–—]\s*', ' ', text)     # kolon/streck → mellanslag
    text = re.sub(r'[^\w\s]', '', text)              # ta bort skiljetecken
    text = re.sub(r'\s+', ' ', text).strip()
    # Svenska ersättningar (för bättre match mot engelska titlar)
    replacements = {
        'å': 'a', 'ä': 'a', 'ö': 'o',
        'é': 'e', 'è': 'e', 'ü': 'u',
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


# ─── Notion API ─────────────────────────────────────────────────────────────────
def notion_request(method: str, path: str, token: str, body: dict = None) -> dict:
    url  = f"{NOTION_API}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req  = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_all_pages(db_id: str, token: str) -> list:
    """Hämtar alla sidor från en Notion-databas (hanterar pagination)."""
    pages, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        result = notion_request("POST", f"/databases/{db_id}/query", token, body)
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        time.sleep(0.2)
    return pages


def extract_text(prop: dict) -> str:
    """Extraherar text ur en Notion-property oavsett typ."""
    if not prop:
        return ""
    ptype = prop.get("type", "")
    if ptype == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
    if ptype == "number":
        v = prop.get("number")
        return str(v) if v is not None else ""
    return ""


def update_bokid(page_id: str, bok_id: str, token: str) -> bool:
    """Skriver BOK-ID på en rad i Betygstabellen."""
    try:
        notion_request("PATCH", f"/pages/{page_id}", token, {
            "properties": {
                "BOK-ID": {"rich_text": [{"text": {"content": bok_id}}]}
            }
        })
        return True
    except Exception as e:
        logging.warning("Kunde inte uppdatera %s: %s", page_id, e)
        return False


# ─── CSV-läge ────────────────────────────────────────────────────────────────────
def load_csv(path: str, sep=';') -> list:
    import csv
    rows = []
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter=sep)
        for row in reader:
            rows.append(dict(row))
    return rows


# ─── Matchning ──────────────────────────────────────────────────────────────────
def build_bokregister_index(bokregister: list) -> list:
    """
    Returnerar en lista med dicts:
      { bok_id, titel, titel_norm, forfattare }
    """
    index = []
    for i, entry in enumerate(bokregister):
        if isinstance(entry, dict) and "properties" in entry:
            # Notion-format
            props = entry["properties"]
            titel = extract_text(props.get("Titel", {}))
            bok_id = extract_text(props.get("BOK-ID", {}))
            forfattare = extract_text(props.get("Författare", {}))
        else:
            # CSV-format
            titel = entry.get("Titel", "")
            bok_id = entry.get("BOK-ID", f"BOK-{i+1:04d}")
            forfattare = entry.get("Författare", "")
        
        if titel:
            index.append({
                "bok_id": bok_id,
                "titel": titel,
                "titel_norm": normalize(titel),
                "forfattare": forfattare,
            })
    return index


def fuzzy_match(query_title: str, query_author: str, index: list, threshold: int = 90):
    """
    Returnerar bästa matchning eller None.
    Prioriterar:
      1. Exakt match (normaliserad)
      2. Fuzzy token_sort_ratio ≥ threshold
    """
    from thefuzz import fuzz

    query_norm = normalize(query_title)

    best_score = 0
    best_entry = None

    for entry in index:
        # Exakt match
        if query_norm == entry["titel_norm"]:
            return entry, 100

        # Fuzzy
        score = fuzz.token_sort_ratio(query_norm, entry["titel_norm"])

        # Bonus om författare matchar
        if query_author and entry["forfattare"]:
            author_score = fuzz.token_sort_ratio(
                normalize(query_author), normalize(entry["forfattare"])
            )
            if author_score >= 80:
                score = min(100, score + 5)

        if score > best_score:
            best_score = score
            best_entry = entry

    if best_score >= threshold:
        return best_entry, best_score
    return None, best_score


# ─── Progress ────────────────────────────────────────────────────────────────────
def load_progress() -> set:
    if PROGRESS_FILE.exists():
        try:
            return set(json.loads(PROGRESS_FILE.read_text(encoding="utf-8")).get("done", []))
        except Exception:
            pass
    return set()


def save_progress(done: set):
    PROGRESS_FILE.write_text(
        json.dumps({"done": sorted(done)}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ─── Main ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Matcha BOK-ID i Betygstabellen")
    parser.add_argument("--dry-run",   action="store_true", help="Visa utan att skriva")
    parser.add_argument("--threshold", type=int, default=90, help="Matchningströskel (default: 90)")
    parser.add_argument("--limit",     type=int, default=0,  help="Max antal rader (0 = alla)")
    parser.add_argument("--csv-mode",  action="store_true",  help="Använd lokala CSV-filer")
    parser.add_argument("--bokregister-csv", default="bokregister_fysiska_v1.csv")
    parser.add_argument("--betyg-csv",       default="clio_reco_goodreads_betyg_v2.csv")
    args = parser.parse_args()

    setup_logging()

    # Importera thefuzz här så felmeddelandet är tydligt
    try:
        from thefuzz import fuzz
    except ImportError:
        logging.error("Kör: pip install thefuzz python-Levenshtein")
        return

    token = os.environ.get("NOTION_TOKEN")
    if not token and not args.csv_mode and not args.dry_run:
        logging.error("Sätt NOTION_TOKEN: export NOTION_TOKEN='secret_...'")
        return

    # ── Hämta data ──────────────────────────────────────────────────────────────
    if args.csv_mode:
        logging.info("CSV-läge: läser lokala filer")
        bokregister_raw = load_csv(args.bokregister_csv)
        betyg_raw       = load_csv(args.betyg_csv)
    else:
        logging.info("Hämtar Bokregistret från Notion...")
        bokregister_raw = get_all_pages(BOKREGISTER_DB, token)
        logging.info("  %d böcker hämtade", len(bokregister_raw))
        logging.info("Hämtar Betygstabellen från Notion...")
        betyg_raw = get_all_pages(BETYG_DB, token)
        logging.info("  %d betygsposter hämtade", len(betyg_raw))

    # ── Bygg index ──────────────────────────────────────────────────────────────
    bok_index = build_bokregister_index(bokregister_raw)
    logging.info("Bokregister-index: %d poster", len(bok_index))

    # ── Matcha ──────────────────────────────────────────────────────────────────
    done_ids = load_progress()
    results  = []
    matched = skipped = no_match = updated = failed = 0

    for i, entry in enumerate(betyg_raw):
        if args.limit and (matched + no_match) >= args.limit:
            logging.info("Limit nått.")
            break

        if isinstance(entry, dict) and "properties" in entry:
            page_id  = entry["id"]
            props    = entry["properties"]
            titel    = extract_text(props.get("Titel", {}))
            forfattare = extract_text(props.get("Författare", {}))
            befintligt_bokid = extract_text(props.get("BOK-ID", {}))
        else:
            page_id  = f"csv-{i}"
            titel    = entry.get("Titel", "")
            forfattare = entry.get("Författare", "")
            befintligt_bokid = entry.get("BOK-ID", "")

        if not titel:
            skipped += 1
            continue

        if befintligt_bokid:
            skipped += 1
            continue

        if page_id in done_ids:
            skipped += 1
            continue

        match_entry, score = fuzzy_match(titel, forfattare, bok_index, args.threshold)

        result = {
            "page_id": page_id,
            "titel": titel,
            "forfattare": forfattare,
            "match_titel": match_entry["titel"] if match_entry else None,
            "match_bok_id": match_entry["bok_id"] if match_entry else None,
            "score": score,
            "status": "matched" if match_entry else "no_match",
        }
        results.append(result)

        if match_entry:
            matched += 1
            logging.info(
                "[%d] ✓ %s → %s (%s%%)",
                i+1, titel[:40], match_entry["bok_id"], score
            )
            if not args.dry_run and token:
                ok = update_bokid(page_id, match_entry["bok_id"], token)
                if ok:
                    updated += 1
                    time.sleep(0.25)
                else:
                    failed += 1
        else:
            no_match += 1
            logging.debug("[%d] ✗ Ingen match: %s (bästa: %s%%)", i+1, titel[:40], score)

        done_ids.add(page_id)

        if (i + 1) % 50 == 0 and not args.dry_run:
            save_progress(done_ids)
            logging.info("  Checkpoint: %d/%d", i+1, len(betyg_raw))

    # ── Spara resultat ──────────────────────────────────────────────────────────
    RESULT_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    if not args.dry_run:
        save_progress(done_ids)

    # ── Sammanfattning ──────────────────────────────────────────────────────────
    logging.info("\n─── Sammanfattning ───────────────────────────")
    logging.info("  Matchade:        %d", matched)
    logging.info("  Ingen match:     %d", no_match)
    logging.info("  Hoppade (redan): %d", skipped)
    if not args.dry_run:
        logging.info("  Uppdaterade:     %d", updated)
        logging.info("  Misslyckade:     %d", failed)
    logging.info("  Resultat sparat: %s", RESULT_FILE)

    # Visa NO-MATCH-lista (värdefull för manuell granskning)
    no_match_list = [r for r in results if r["status"] == "no_match"]
    if no_match_list:
        logging.info("\n  Titlar utan match (granska manuellt):")
        for r in no_match_list[:20]:
            logging.info("    - %s av %s (bästa: %s%%)", r["titel"][:45], r["forfattare"][:20], r["score"])
        if len(no_match_list) > 20:
            logging.info("    ... och %d till. Se %s", len(no_match_list)-20, RESULT_FILE)


if __name__ == "__main__":
    main()
