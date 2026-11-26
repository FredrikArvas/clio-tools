#!/usr/bin/env python3
"""
import_pursue.py — Importerar PURSUE-dokument (war.gov/UFO) till vigil.db.

Alla 375 poster importeras med state='discovered'.
source_type='web', source_name='PURSUE (war.gov)', maturity='akademisk', weight=2.0
"""
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

DB_PATH   = Path("clio-vigil/data/vigil.db")
JSON_PATH = Path("clio-vigil/research/pursue_tagged.json")

SOURCE_NAME     = "PURSUE (war.gov)"
SOURCE_TYPE     = "web"
SOURCE_MATURITY = "akademisk"
DOMAIN          = "ufo"
LANGUAGE        = "en"
WEIGHT          = 2.0


def parse_release_date(date_str):
    """Konverterar '8/7/26' → '2026-08-07 00:00:00'"""
    if not date_str:
        return None
    try:
        # Format M/D/YY
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
            year = 2000 + y if y < 100 else y
            return f"{year:04d}-{m:02d}-{d:02d} 00:00:00"
    except Exception:
        pass
    return None


def ep_to_row(ep):
    tags = ep.get("tags") or {}
    witness_score = float(tags.get("witness_score") or 0.0)
    # Prioritet: keep=true → 600, annars 500 + witness_score*10
    keep = bool(tags.get("keep"))
    priority = (600.0 if keep else 500.0) + witness_score * 10

    # URL: file_url om det finns, annars konstruera från title
    url = ep.get("file_url") or ""
    if not url:
        # VID/AUD utan direkt URL — konstruera placeholder från VIRIN
        virin = ep.get("virin") or ""
        url = f"https://www.war.gov/UFO/#dvids-{virin}" if virin else f"https://www.war.gov/UFO/#{ep.get('title','')[:60]}"

    file_type = (ep.get("type") or "").upper()  # PDF / IMG / VID / AUD

    return {
        "url":              url,
        "domain":           DOMAIN,
        "source_type":      SOURCE_TYPE,
        "source_name":      SOURCE_NAME,
        "source_maturity":  SOURCE_MATURITY,
        "title":            (ep.get("title") or "")[:255],
        "published_at":     parse_release_date(ep.get("pub_date") or ""),
        "duration_seconds": 0,
        "relevance_score":  witness_score * WEIGHT,
        "priority_score":   priority,
        "state":            "discovered",
        "language":         LANGUAGE,
        # Extra-fält sparas i en description-kolumn om den finns
        "description":      (ep.get("description") or "")[:1000],
        "agency":           (ep.get("agency") or "")[:100],
        "file_type":        file_type,
        "incident_date":    (ep.get("incident_date") or "")[:100],
        "incident_location":(ep.get("incident_location") or "")[:200],
        "virin":            (ep.get("virin") or "")[:50],
    }


def run(dry_run=False):
    if not JSON_PATH.exists():
        log.error("JSON saknas: %s", JSON_PATH)
        sys.exit(1)

    episodes = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    log.info("Laddade %d poster från %s", len(episodes), JSON_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Kontrollera vilka kolumner vigil_items har
    pragma = conn.execute("PRAGMA table_info(vigil_items)").fetchall()
    existing_cols = {row[1] for row in pragma}
    log.info("vigil_items kolumner: %s", sorted(existing_cols))

    created = updated = skipped = 0

    for ep in episodes:
        row = ep_to_row(ep)

        # Filtrera bort kolumner som inte finns i tabellen
        filtered_row = {k: v for k, v in row.items() if k in existing_cols}

        url = row["url"]
        if not url:
            log.warning("  Hoppar över (ingen URL): %s", row["title"][:60])
            skipped += 1
            continue

        existing = cur.execute("SELECT id, state FROM vigil_items WHERE url=?", (url,)).fetchone()

        if existing:
            if existing["state"] == "discovered":
                skipped += 1
                continue
            # Uppdatera bara om state inte är längre hunnen
            advanced_states = {"queued", "downloaded", "transcribing", "transcribed",
                               "summarized", "indexed", "notified", "filtered_out", "failed"}
            if existing["state"] in advanced_states:
                skipped += 1
                continue
            if not dry_run:
                cur.execute("UPDATE vigil_items SET state='discovered', title=:title, published_at=:published_at WHERE url=:url",
                            {"title": filtered_row.get("title",""), "published_at": filtered_row.get("published_at"), "url": url})
            updated += 1
            log.info("  Uppdaterade: %s", row["title"][:60])
        else:
            if not dry_run:
                placeholders = ", ".join(f":{k}" for k in filtered_row)
                cols = ", ".join(filtered_row.keys())
                cur.execute(
                    f"INSERT INTO vigil_items ({cols}, created_at) VALUES ({placeholders}, datetime('now'))",
                    filtered_row,
                )
            created += 1
            if created <= 5 or created % 50 == 0:
                log.info("  Skapade (%d): %s", created, row["title"][:60])

    if not dry_run:
        conn.commit()
    conn.close()

    print("\n" + "=" * 60)
    print(f"PURSUE-import klar  [{SOURCE_NAME}]")
    print(f"  Skapade:    {created}")
    print(f"  Uppdaterade:{updated}")
    print(f"  Hoppade:    {skipped}")
    if dry_run:
        print("  ** DRY RUN — inget skrevs till databasen **")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        log.info("DRY RUN läge — inget skrivs till databasen")
    run(dry_run=dry)
