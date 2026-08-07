#!/usr/bin/env python3
"""
import_to_odoo.py — Importerar taggade podcastavsnitt till clio.vigil.item
==========================================================================

KRÄVER att clio_vigil-addonen är uppgraderad med nya fält INNAN detta körs:
  - clio.vigil.item: language (Selection), podcast_format, podcast_topic,
                     podcast_witness_score, podcast_keep,
                     podcast_geo_ids (M2M → clio.podcast.geo),
                     podcast_background_ids (M2M → clio.podcast.background)
  - clio.podcast.geo, clio.podcast.background: nya modeller

Uppgradera addonen först:
  docker exec odoo19-odoo-1 odoo -c /etc/odoo/odoo.conf \\
      -u clio_vigil -d uap --stop-after-init
  docker restart odoo19-odoo-1

Körning:
  cd ~/19.0/clio-tools
  python3 clio-vigil/research/import_to_odoo.py \\
      --input clio-vigil/research/multiverse5d_tagged.json \\
      [--dry-run]      # Validera utan att skriva till Odoo
      [--keep-only]    # Importera bara keep=true (107 avsnitt)
      [--batch 50]     # Avsnitt per transaktion (default 50)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from dotenv import load_dotenv

_here = Path(__file__).parent
load_dotenv(_here.parent.parent / ".env")        # ~/19.0/clio-tools/.env
load_dotenv(_here.parent / ".env", override=True)  # clio-vigil/.env

sys.path.insert(0, str(_here.parent.parent))     # clio-tools root för clio_odoo

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s %(levelname)s %(message)s",
    datefmt = "%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

SOURCE_NAME    = "Multiverse 5D"
SOURCE_URL     = "https://multiverse5d.com"        # kanonisk URL för källan
DOMAIN         = "ufo"
SOURCE_TYPE    = "rss"
SOURCE_LANG    = "pt"   # kanalens primärspråk (blandad kanal, pt är bas)

# Fördefinierade geo-taggar med svenska etiketter
GEO_TAGS = {
    "mars":          "Mars",
    "moon":          "Månen",
    "space":         "Rymden",
    "other_planet":  "Annan planet",
    "north_america": "Nordamerika",
    "south_america": "Sydamerika",
    "europe":        "Europa",
    "asia":          "Asien",
    "africa":        "Afrika",
    "australia":     "Australien",
    "antarctica":    "Antarktis",
    "ocean":         "Hav",
    "underwater":    "Under vatten",
    "underground":   "Under jord",
    "unknown":       "Okänd plats",
}

# Fördefinierade bakgrunds-taggar
BACKGROUND_TAGS = {
    "military":         "Militär",
    "military_program": "Militärt program (SSP/MILAB)",
    "intelligence":     "Underrättelsetjänst",
    "government":       "Myndighet / regering",
    "aerospace":        "Flyg / rymdindustri",
    "scientific":       "Forskning / vetenskap",
    "medical":          "Medicin / hälsa",
    "law_enforcement":  "Polis / rättsväsende",
    "civilian":         "Civilist",
    "experiencer":      "Upplevare / kontaktperson",
    "religious":        "Andlig / religiös",
    "other":            "Annan bakgrund",
}

# Language Selection-värden (matchar clio.vigil.item.language)
LANG_MAP = {
    "en":    "en",
    "pt":    "pt",
    "other": False,   # lämna tomt för okänt/övrigt
}


# ---------------------------------------------------------------------------
# Anslutning
# ---------------------------------------------------------------------------

def get_env():
    """Koppla upp mot uap-databasen via clio_odoo."""
    import os
    from clio_odoo import connect
    url = os.environ.get("VIGIL_ODOO_URL", "https://uap.arvas.international")
    db  = os.environ.get("VIGIL_ODOO_DB",  "uap")
    log.info("Ansluter till %s (db: %s) …", url, db)
    return connect(url=url, db=db)


# ---------------------------------------------------------------------------
# Tagg-cache (undviker upprepade search-anrop)
# ---------------------------------------------------------------------------

def _to_int(odoo_id) -> int:
    """Konverterar OdooRecordset eller int till plain int (pyodoo_connect-kompatibel)."""
    if isinstance(odoo_id, int):
        return odoo_id
    # OdooRecordset har .id-attribut eller stöder iteration
    if hasattr(odoo_id, "id"):
        return int(odoo_id.id)
    try:
        return int(list(odoo_id)[0])
    except Exception:
        return int(odoo_id)


def ensure_geo_tags(env) -> dict[str, int]:
    """Returnera {code: odoo_id} för alla geo-taggar, skapa om de saknas."""
    Geo = env["clio.podcast.geo"]
    cache = {}
    for code, label in GEO_TAGS.items():
        recs = Geo.search_read([("code", "=", code)], ["id"], limit=1)
        if recs:
            cache[code] = int(recs[0]["id"])
        else:
            cache[code] = _to_int(Geo.create({"code": code, "name": label}))
            log.info("  Skapade geo-tagg: %s (%s)", code, label)
    log.info("Geo-taggar: %d st", len(cache))
    return cache


def ensure_background_tags(env) -> dict[str, int]:
    """Returnera {code: odoo_id} för alla bakgrunds-taggar, skapa om de saknas."""
    Bg = env["clio.podcast.background"]
    cache = {}
    for code, label in BACKGROUND_TAGS.items():
        recs = Bg.search_read([("code", "=", code)], ["id"], limit=1)
        if recs:
            cache[code] = int(recs[0]["id"])
        else:
            cache[code] = _to_int(Bg.create({"code": code, "name": label}))
            log.info("  Skapade bakgrunds-tagg: %s (%s)", code, label)
    log.info("Bakgrunds-taggar: %d st", len(cache))
    return cache


def ensure_source(env) -> int:
    """Returnera Odoo-id för Multiverse 5D-källan, skapa om den saknas."""
    Src = env["clio.vigil.source"]
    recs = Src.search_read([("name", "=", SOURCE_NAME)], ["id"], limit=1)
    if recs:
        log.info("Källa hittad: %s (id %d)", SOURCE_NAME, recs[0]["id"])
        return recs[0]["id"]
    new_id = _to_int(Src.create({
        "name":        SOURCE_NAME,
        "source_type": SOURCE_TYPE,
        "domain":      DOMAIN,
        "language":    SOURCE_LANG,
        "url":         SOURCE_URL,
        "active":      False,   # inaktiv — Spotify-källan samlar inte automatiskt
        "weight":      1.0,
        "notes":       (
            "999 avsnitt importerade från podcast_tagger.py 2026-08-07. "
            "Kanal: ~55% engelska, ~45% portugisiska. "
            "Inaktiv källa — RSS-URL ej konfigurerad för automatisk insamling."
        ),
    }))
    log.info("Skapade källa: %s (id %d)", SOURCE_NAME, new_id)
    return new_id


# ---------------------------------------------------------------------------
# Datumkonvertering
# ---------------------------------------------------------------------------

def parse_pub_date(date_str: str) -> str | None:
    """
    Konverterar RSS-datumformat 'Mon, 03 Aug 2026' till Odoo-datetime-sträng.
    Returnerar None om parsning misslyckas.
    """
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            # Fallback: bara datum utan tid
            dt = datetime.strptime(date_str.strip(), "%a, %d %b %Y")
            return dt.strftime("%Y-%m-%d 00:00:00")
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Episod → Odoo-värden
# ---------------------------------------------------------------------------

def episode_to_vals(
    ep: dict,
    source_id: int,
    geo_cache: dict[str, int],
    bg_cache: dict[str, int],
) -> dict:
    """
    Konverterar ett taggat avsnitt till ett dict med Odoo-fältvärden
    för clio.vigil.item.
    """
    tags   = ep.get("tags", {})
    lang   = LANG_MAP.get(tags.get("lang", ""), False)
    keep   = tags.get("keep", False)
    state  = "filtered_in" if keep else "filtered_out"

    # Many2many: lista av (4, id) = länka befintlig post
    geo_ids = [
        (4, geo_cache[code])
        for code in tags.get("geo", [])
        if code in geo_cache
    ]
    bg_ids = [
        (4, bg_cache[code])
        for code in tags.get("witness_background", [])
        if code in bg_cache
    ]

    return {
        # ── Identifiering ────────────────────────────────────────────────
        "url":          ep.get("audio_url") or ep.get("guid") or "",
        "title":        ep.get("title", "")[:255],

        # ── Källmetadata ─────────────────────────────────────────────────
        "domain":       DOMAIN,
        "source_type":  SOURCE_TYPE,
        "source_name":  SOURCE_NAME,
        "published_at": parse_pub_date(ep.get("pub_date", "")),
        "duration_seconds": int(ep.get("duration_s") or 0),

        # ── Tillstånd ────────────────────────────────────────────────────
        "state":           state,
        "relevance_score": float(tags.get("witness_score", 0.0)),
        "priority_score":  float(tags.get("witness_score", 0.0)),

        # ── Podcast-taggar ───────────────────────────────────────────────
        "language":               lang or False,
        "podcast_format":         tags.get("format") or False,
        "podcast_topic":          tags.get("topic") or False,
        "podcast_witness_score":  float(tags.get("witness_score", 0.0)),
        "podcast_keep":           keep,
        "podcast_geo_ids":        geo_ids,
        "podcast_background_ids": bg_ids,
    }


# ---------------------------------------------------------------------------
# Upsert-logik
# ---------------------------------------------------------------------------

def upsert_episode(env, vals: dict, dry_run: bool) -> str:
    """
    Upsert ett avsnitt. Nyckel: url.
    Returnerar 'created' | 'updated' | 'skipped' | 'error'.
    """
    if not vals.get("url"):
        log.warning("  Hoppar episode utan URL: %s", vals.get("title", "?")[:60])
        return "skipped"

    if dry_run:
        return "dry_run"

    try:
        Item = env["clio.vigil.item"]
        existing = Item.search_read([("url", "=", vals["url"])], ["id"], limit=1)
        if existing:
            # Vid uppdatering: många2många-relationer måste hanteras separat
            # Rensa befintliga M2M-länkningar och lägg till nya
            rec_id = existing[0]["id"]
            vals_no_m2m = {k: v for k, v in vals.items()
                           if k not in ("podcast_geo_ids", "podcast_background_ids")}
            Item.write([rec_id], vals_no_m2m)
            if vals.get("podcast_geo_ids"):
                Item.write([rec_id], {"podcast_geo_ids": [(5,)] + vals["podcast_geo_ids"]})
            if vals.get("podcast_background_ids"):
                Item.write([rec_id], {"podcast_background_ids": [(5,)] + vals["podcast_background_ids"]})
            return "updated"
        else:
            Item.create(vals)
            return "created"
    except Exception as exc:
        log.error("  Fel vid upsert av '%s': %s", vals.get("url", "?")[:60], exc)
        return "error"


# ---------------------------------------------------------------------------
# Huvudlogik
# ---------------------------------------------------------------------------

def run(args) -> None:
    input_path = Path(args.input)
    if not input_path.exists():
        log.error("Input-fil saknas: %s", input_path)
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        episodes: list[dict] = json.load(f)

    log.info("Laddade %d avsnitt från %s", len(episodes), input_path)

    if args.keep_only:
        episodes = [e for e in episodes if e.get("tags", {}).get("keep")]
        log.info("--keep-only: %d avsnitt att importera", len(episodes))

    # Validera att alla nödvändiga taggar finns
    untagged = [e for e in episodes if not e.get("tags")]
    if untagged:
        log.warning("%d avsnitt saknar tags-fält — hoppas över", len(untagged))
        episodes = [e for e in episodes if e.get("tags")]

    if args.dry_run:
        log.info("=== DRY-RUN — inget skrivs till Odoo ===")
        kept = sum(1 for e in episodes if e.get("tags", {}).get("keep"))
        log.info("Statistik: %d avsnitt, %d keep=true, %d keep=false",
                 len(episodes), kept, len(episodes) - kept)
        # Visa ett sampel av vals
        sample = episode_to_vals(episodes[0], source_id=99,
                                 geo_cache={}, bg_cache={})
        log.info("Sampel vals: %s", json.dumps(sample, indent=2, ensure_ascii=False,
                                                default=str)[:500])
        return

    # Anslut
    env = get_env()

    # Förberedelser
    log.info("Skapar/verifierar geo- och bakgrunds-taggar …")
    geo_cache = ensure_geo_tags(env)
    bg_cache  = ensure_background_tags(env)

    log.info("Skapar/verifierar källa …")
    source_id = ensure_source(env)

    # Upsert i batchar
    batch_size = args.batch
    counts = {"created": 0, "updated": 0, "skipped": 0, "error": 0, "dry_run": 0}
    total  = len(episodes)

    for i in range(0, total, batch_size):
        batch   = episodes[i : i + batch_size]
        end_idx = min(i + batch_size, total)
        log.info("Batch %d–%d / %d …", i + 1, end_idx, total)

        for ep in batch:
            vals   = episode_to_vals(ep, source_id, geo_cache, bg_cache)
            result = upsert_episode(env, vals, dry_run=False)
            counts[result] = counts.get(result, 0) + 1

        log.info("  Delresultat: skapade=%d, uppdaterade=%d, fel=%d",
                 counts["created"], counts["updated"], counts["error"])

    # Sammanfattning
    print("\n" + "=" * 55)
    print(f"IMPORT KLAR — {total} avsnitt bearbetade")
    print("=" * 55)
    print(f"  Skapade:     {counts['created']:4d}")
    print(f"  Uppdaterade: {counts['updated']:4d}")
    print(f"  Hoppade:     {counts['skipped']:4d}")
    print(f"  Fel:         {counts['error']:4d}")
    print("=" * 55)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importera taggade podcastavsnitt till clio.vigil.item i Odoo."
    )
    parser.add_argument(
        "--input", required=True,
        help="Sökväg till tagged JSON-fil (t.ex. multiverse5d_tagged.json)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validera utan att skriva till Odoo",
    )
    parser.add_argument(
        "--keep-only", action="store_true",
        help="Importera bara avsnitt med keep=true (107 st)",
    )
    parser.add_argument(
        "--batch", type=int, default=50,
        help="Avsnitt per logg-checkpoint (default: 50)",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
