"""
import_ufotilluap.py
====================
Importerar podden "Från UFO till UAP" till vigil_sources + vigil_items.

- Lägger till källpost i vigil_sources (om den saknas)
- Importerar episoder från RSS med deduplicering på episode-ankar-ID
  (t.ex. "e3g7ben" ur URL-sluggen) — robust mot omnumrering
- Sätter state='queued' (ej 'transcribed') — transkription görs lokalt

Körning:
  python import_ufotilluap.py [--dry-run]
"""

import argparse
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

BASE_DIR       = Path(__file__).parent
DB_PATH        = BASE_DIR / "data" / "vigil.db"
RSS_URL        = "https://anchor.fm/s/e8906f58/podcast/rss"
SOURCE_NAME    = "Från UFO till UAP (En verklighet i förändring)"
SOURCE_DOMAIN  = "ufo"
SOURCE_TYPE    = "rss"
SOURCE_MATURITY = "etablerad"
SOURCE_WEIGHT  = 1.1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("import_ufotilluap")

# ── Hjälpare ──────────────────────────────────────────────────────────────────

def episode_anchor_id(url: str) -> str | None:
    """Extrahera Spotify/Anchor episode-ID ur URL-slug, t.ex. 'e3g7ben'."""
    m = re.search(r"-([a-z0-9]{5,10})(?:/|$)", url)
    return m.group(1) if m else None


def parse_duration(itunes_ns: str, item: ET.Element) -> int | None:
    """Returnera duration i sekunder från itunes:duration-taggen."""
    tag = f"{{{itunes_ns}}}duration"
    val = item.findtext(tag, "")
    if not val:
        return None
    try:
        parts = val.strip().split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(parts[0])
    except ValueError:
        return None


def fetch_rss() -> list[dict]:
    """Hämta RSS och returnera lista av parsade avsnitt."""
    log.info(f"Hämtar RSS: {RSS_URL}")
    req = Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0 (clio-vigil)"})
    with urlopen(req, timeout=30) as f:
        tree = ET.parse(f)
    root   = tree.getroot()
    channel = root.find("channel")

    # Namespaces
    itunes_ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"

    episodes = []
    for item in channel.findall("item"):
        link  = (item.findtext("link") or "").strip()
        guid  = (item.findtext("guid") or "").strip()
        enc   = item.find("enclosure")
        enc_url  = enc.get("url", "") if enc is not None else ""
        enc_type = enc.get("type", "") if enc is not None else ""

        pub_raw = item.findtext("pubDate", "")
        try:
            pub_dt = parsedate_to_datetime(pub_raw).astimezone(timezone.utc)
            published_at = pub_dt.isoformat()
        except Exception:
            published_at = None

        episodes.append({
            "title":        (item.findtext("title") or "").strip(),
            "url":          link or enc_url,          # Spotify-slug som primär URL
            "guid":         guid,
            "enclosure_url": enc_url,
            "enclosure_type": enc_type,
            "published_at": published_at,
            "description":  (item.findtext("description") or
                              item.findtext(f"{{{itunes_ns}}}summary") or "").strip()[:2000],
            "duration_sec": parse_duration(itunes_ns, item),
            "anchor_id":    episode_anchor_id(link) or episode_anchor_id(guid) or guid[:20],
        })
    log.info(f"  {len(episodes)} avsnitt i flödet")
    return episodes


def ensure_source(conn: sqlite3.Connection, dry_run: bool) -> int | None:
    """Lägg till källpost i vigil_sources om den saknas. Returnerar id."""
    row = conn.execute(
        "SELECT id FROM vigil_sources WHERE url=?", (RSS_URL,)
    ).fetchone()
    if row:
        log.info(f"vigil_sources: källpost finns redan (id={row['id']})")
        return row["id"]

    if dry_run:
        log.info("[DRY-RUN] vigil_sources: skulle lägga till källpost")
        return None

    conn.execute(
        """INSERT INTO vigil_sources (domain, source_type, url, name, maturity, weight, active, added_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'), ?)""",
        (
            SOURCE_DOMAIN, SOURCE_TYPE, RSS_URL, SOURCE_NAME,
            SOURCE_MATURITY, SOURCE_WEIGHT,
            "iTunes-id: 1706683453 | Karl Hemborg | Svenska | Importerad av import_ufotilluap.py",
        ),
    )
    conn.commit()
    src_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log.info(f"vigil_sources: källpost skapad (id={src_id})")
    return src_id


def import_episodes(conn: sqlite3.Connection, episodes: list[dict], dry_run: bool) -> dict:
    """Importera episoder med deduplicering på anchor_id. Returnerar stats."""
    # Bygg upp set av befintliga anchor-IDs
    existing_anchors: set[str] = set()
    for row in conn.execute(
        "SELECT url FROM vigil_items WHERE source_name=?", (SOURCE_NAME,)
    ).fetchall():
        aid = episode_anchor_id(row["url"])
        if aid:
            existing_anchors.add(aid)

    log.info(f"Befintliga poster: {len(existing_anchors)} unika anchor-ID:n")

    stats = {"inserted": 0, "skipped": 0, "no_anchor": 0}

    for ep in episodes:
        aid = ep["anchor_id"]
        if not aid or len(aid) < 3:
            log.warning(f"  Inget anchor-ID för: {ep['title'][:50]}")
            stats["no_anchor"] += 1
            continue

        if aid in existing_anchors:
            stats["skipped"] += 1
            continue

        log.info(f"  NYTT: {ep['published_at'] or '?'[:10]} | {ep['title'][:60]}")

        if dry_run:
            stats["inserted"] += 1
            continue

        raw_meta = json.dumps({
            "feed_url":    RSS_URL,
            "feed_title":  SOURCE_NAME,
            "guid":        ep["guid"],
            "enclosure_url": ep["enclosure_url"],
        }, ensure_ascii=False)

        conn.execute(
            """INSERT OR IGNORE INTO vigil_items
               (url, domain, source_type, source_name, source_maturity,
                title, description, published_at, duration_seconds,
                relevance_score, priority_score, source_weight,
                state, state_updated_at, whisper_model, created_at, raw_metadata)
               VALUES (?, ?, ?, ?, ?,  ?, ?, ?, ?,  ?, ?, ?,  ?, datetime('now'), ?, datetime('now'), ?)""",
            (
                ep["url"] or ep["enclosure_url"],
                SOURCE_DOMAIN, SOURCE_TYPE, SOURCE_NAME, SOURCE_MATURITY,
                ep["title"], ep["description"], ep["published_at"], ep["duration_sec"],
                0.9,          # relevance_score — svensk ufo-podd med hög relevans
                0.9 * SOURCE_WEIGHT,
                SOURCE_WEIGHT,
                "queued",     # INTE transcribed — lokal pipeline transkriberar
                "medium",     # whisper_model default
                raw_meta,
            ),
        )
        conn.commit()
        existing_anchors.add(aid)
        stats["inserted"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Import ufotilluap → vigil DB")
    parser.add_argument("--dry-run", action="store_true", help="Simulera, ändra inget")
    args = parser.parse_args()

    if not DB_PATH.exists():
        log.error(f"DB saknas: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    ensure_source(conn, args.dry_run)
    episodes = fetch_rss()
    stats    = import_episodes(conn, episodes, args.dry_run)
    conn.close()

    log.info("=" * 50)
    if args.dry_run:
        log.info(f"[DRY-RUN] Klart: {stats}")
    else:
        log.info(f"Klart: {stats}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
