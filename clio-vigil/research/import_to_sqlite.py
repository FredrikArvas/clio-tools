#!/usr/bin/env python3
"""
import_to_sqlite.py
Infogar podcast-avsnitt (testimony + militär, eller alla keep=true) från
tagged JSON till vigil.db, sedan kör Odoo-synk.

Körning:
  cd ~/19.0/clio-tools
  python3 clio-vigil/research/import_to_sqlite.py \
      --json clio-vigil/research/exopolitics_tagged.json \
      --source-name "Exopolitics Today" \
      --source-maturity etablerad \
      [--all-keep] [--dry-run]

  --json         : sökväg till tagged JSON (krävs)
  --source-name  : källnamn i vigil (default: Multiverse 5D)
  --source-maturity : tidig | etablerad | akademisk (default: tidig)
  --all-keep     : importera alla keep=true, inte bara testimony+militär
  --dry-run      : visa vad som skulle infogas utan att skriva
"""
import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

DB_PATH = Path("clio-vigil/data/vigil.db")

MIL_CODES = {"military", "military_program", "intelligence"}

FORMAT_WHITELIST = {"testimony"}   # vittnesmål

def parse_pub_date(date_str):
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            dt = datetime.strptime(date_str.strip(), "%a, %d %b %Y")
            return dt.strftime("%Y-%m-%d 00:00:00")
        except Exception:
            return None

def is_military(tags):
    return bool(MIL_CODES & set(tags.get("witness_background", [])))

def is_testimony(tags):
    return tags.get("format") in FORMAT_WHITELIST

def ep_to_row(ep, source_name, source_maturity):
    tags = ep.get("tags", {})
    lang = tags.get("lang", "en")
    if lang not in ("en", "sv", "pt"):
        lang = "en"
    witness_score = float(tags.get("witness_score") or 0.0)
    # Prioritet: vittnespoäng * 10 + 500 → 500–600-intervall
    priority = 500.0 + witness_score * 10
    return {
        "url":              ep.get("audio_url") or ep.get("guid") or "",
        "domain":           "ufo",
        "source_type":      "rss",
        "source_name":      source_name,
        "source_maturity":  source_maturity,
        "title":            (ep.get("title") or "")[:255],
        "published_at":     parse_pub_date(ep.get("pub_date", "")),
        "duration_seconds": int(ep.get("duration_s") or 0),
        "relevance_score":  witness_score,
        "priority_score":   priority,
        "state":            "queued",
        "language":         lang,
    }

def run(args):
    json_path = Path(args.json)
    source_name = args.source_name
    source_maturity = args.source_maturity

    if not json_path.exists():
        log.error("JSON saknas: %s", json_path)
        sys.exit(1)
    if not DB_PATH.exists():
        log.error("vigil.db saknas: %s", DB_PATH)
        sys.exit(1)

    episodes = json.loads(json_path.read_text(encoding="utf-8"))
    log.info("Laddade %d avsnitt från JSON (källa: %s)", len(episodes), source_name)

    if args.all_keep:
        candidates = [e for e in episodes if e.get("tags", {}).get("keep")]
        log.info("--all-keep: %d avsnitt (keep=true)", len(candidates))
    else:
        candidates = [
            e for e in episodes
            if e.get("tags")
            and is_testimony(e["tags"])
            and is_military(e["tags"])
        ]
        log.info("testimony + militär: %d avsnitt", len(candidates))

    if not candidates:
        log.warning("Inga avsnitt matchar kriterierna.")
        return

    for ep in candidates:
        tags = ep.get("tags", {})
        log.info("  [%.1f] %s | format=%s bg=%s",
                 float(tags.get("witness_score") or 0),
                 (ep.get("title") or "")[:60],
                 tags.get("format"),
                 tags.get("witness_background"))

    if args.dry_run:
        log.info("=== DRY-RUN — inget skrivs till SQLite ===")
        log.info("Totalt kandidater: %d", len(candidates))
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    created = updated = skipped = 0

    for ep in candidates:
        row = ep_to_row(ep, source_name, source_maturity)
        if not row["url"]:
            log.warning("Hoppar ep utan URL: %s", row.get("title","?")[:50])
            skipped += 1
            continue
        existing = conn.execute(
            "SELECT id, state FROM vigil_items WHERE url = ?", (row["url"],)
        ).fetchone()

        if existing:
            # Uppdatera bara state och prioritet — rör inte transkript etc.
            conn.execute(
                "UPDATE vigil_items SET state=?, priority_score=?, language=? WHERE id=?",
                (row["state"], row["priority_score"], row["language"], existing["id"]),
            )
            log.info("  Uppdaterade id=%d (state %s→queued): %s",
                     existing["id"], existing["state"], row["title"][:55])
            updated += 1
        else:
            conn.execute("""
                INSERT INTO vigil_items
                  (url, domain, source_type, source_name, source_maturity,
                   title, published_at, duration_seconds,
                   relevance_score, priority_score, state, language,
                   created_at)
                VALUES
                  (:url,:domain,:source_type,:source_name,:source_maturity,
                   :title,:published_at,:duration_seconds,
                   :relevance_score,:priority_score,:state,:language,
                   datetime('now'))
            """, row)
            log.info("  Skapade: %s", row["title"][:60])
            created += 1

    conn.commit()
    conn.close()

    print("\n" + "=" * 50)
    print(f"SQLite-import klar  [{source_name}]")
    print(f"  Skapade:     {created}")
    print(f"  Uppdaterade: {updated}")
    print(f"  Hoppade:     {skipped}")
    print("=" * 50)

    # Kör Odoo-synk
    log.info("Kör Odoo-synk ...")
    import os
    from dotenv import load_dotenv
    load_dotenv(Path("clio-vigil/.env"))
    sys.path.insert(0, ".")
    sys.path.insert(0, str(Path("clio-vigil")))
    from clio_odoo import connect
    from odoo_writer import sync_items_from_conn

    odoo_env = connect(
        url=os.environ.get("VIGIL_ODOO_URL", "https://uap.arvas.international"),
        db=os.environ.get("VIGIL_ODOO_DB", "uap"),
    )
    conn2 = sqlite3.connect(DB_PATH)
    conn2.row_factory = sqlite3.Row
    n = sync_items_from_conn(odoo_env, conn2)
    conn2.close()
    log.info("Odoo-synk klar: %d poster synkade", n)

def main():
    p = argparse.ArgumentParser(description="Importera taggade podcast-avsnitt till vigil.db och Odoo.")
    p.add_argument("--json",            required=True,
                   help="Sökväg till <slug>_tagged.json")
    p.add_argument("--source-name",     default="Multiverse 5D",
                   help="Källnamn i vigil_items (default: Multiverse 5D)")
    p.add_argument("--source-maturity", default="tidig",
                   choices=["tidig", "etablerad", "akademisk"],
                   help="Källmognad (default: tidig)")
    p.add_argument("--all-keep",        action="store_true",
                   help="Importera alla keep=true, inte bara testimony+militär")
    p.add_argument("--dry-run",         action="store_true",
                   help="Visa kandidater utan att skriva till SQLite/Odoo")
    run(p.parse_args())

if __name__ == "__main__":
    main()
