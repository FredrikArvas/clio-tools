#!/usr/bin/env python3
"""
import_pursue_encounters.py — Importerar PURSUE-dokument (war.gov/UFO) som uap.encounter.

Källdata: pursue_tagged.json (375 poster från war.gov PURSUE-release)
Mål: uap.encounter i Odoo (db=uap), ~359 poster efter filter

Filter (hoppar över):
  - "Email Correspondence" i title
  - "Organizational Chart" i title
  - "Declassification Review" i title
  - "Administrative" i title
  - type=IMG + "Digital Rendering" i title (parad med PDF-dokument)

Fältmappning:
  encounter_class: baserat på title-nyckelord
  discourse_level: 5 (Confirmed/Declassified)
  official_response: E (Confirmation)
  eth_origin: 0 (initial — enrichas med uap_enrich.py efteråt)
  intelligence_indicator: 0 (initial)
  obs_*: False (initial)

Körning:
  cd ~/19.0/clio-tools
  python3 clio-vigil/research/import_pursue_encounters.py --dry-run
  python3 clio-vigil/research/import_pursue_encounters.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ladda .env-filer (samma mönster som import_to_odoo.py)
_here = Path(__file__).parent
load_dotenv(_here.parent.parent / ".env")           # ~/19.0/clio-tools/.env
load_dotenv(_here.parent / ".env", override=True)   # clio-vigil/.env

sys.path.insert(0, str(_here.parent.parent))        # clio-tools root för clio_odoo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konstanter
# ---------------------------------------------------------------------------

JSON_PATH = _here / "pursue_tagged.json"

SOURCE_DB_NAME = "PURSUE — US Government UAP Initiative (war.gov)"
SOURCE_DB_URL  = "https://www.war.gov/UFO/"
LANGUAGE       = "en"

# Titelnyckelord → encounter_class
CLASS_RULES: list[tuple[list[str], str]] = [
    (["FD-302", "Unresolved UAP Report"],                        "2"),  # Close Encounter
    (["Physical Evidence", "Film Analysis", "Photo", "Film,",
      "Photographic", "Footage"],                                "3"),  # Physical Evidence
    (["Digital Rendering", "Debriefing", "Analysis", "Report",
      "Organizational", "Administrative", "Email"],              "5"),  # Media
]

# Filtrera bort dessa poster helt
SKIP_TITLE_FRAGMENTS = [
    "Email Correspondence",
    "Organizational Chart",
    "Declassification Review",
    "Administrative",
]


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def should_skip(ep: dict) -> bool:
    """Returnerar True om posten ska hoppas över."""
    title = ep.get("title", "")
    # Admin/org-dokument
    if any(f in title for f in SKIP_TITLE_FRAGMENTS):
        return True
    # IMG-renderingar (parade med PDF-dokument)
    if ep.get("type", "").upper() == "IMG" and "Digital Rendering" in title:
        return True
    return False


def classify(ep: dict) -> str:
    """Bestäm encounter_class (1–5) baserat på title och fält."""
    title = ep.get("title", "")
    for keywords, cls in CLASS_RULES:
        if any(kw in title for kw in keywords):
            return cls
    # Fallback: Sighting om incident_date + location, annars Media
    if ep.get("incident_date") and ep.get("incident_location"):
        return "1"
    return "5"


def extract_year(text: str | None) -> str | None:
    """Extraherar första 4-siffriga år ur en sträng (t.ex. '1950, 1952' → '1950')."""
    if not text:
        return None
    m = re.search(r"\b(1[89]\d{2}|20[012]\d)\b", text)
    return m.group(1) if m else None


def parse_incident_date(text: str | None) -> str | None:
    """
    Konverterar incident_date till Odoo datetime-sträng.
    Hanterar: '2002', '1950, 1952', 'June 2002', etc.
    Tar alltid första år som hittas. Månaden sätts till 1 om okänd.
    """
    if not text:
        return None

    # Månadsnamn → nummer
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    text_lower = text.lower()
    year = extract_year(text)
    if not year:
        return None

    month = 1
    for name, num in months.items():
        if name in text_lower:
            month = num
            break

    return f"{year}-{month:02d}-01 00:00:00"


def parse_pub_date(date_str: str | None) -> str | None:
    """Konverterar '8/7/26' → '2026-08-07 00:00:00'"""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
            year = 2000 + y if y < 100 else y
            return f"{year:04d}-{m:02d}-{d:02d} 00:00:00"
    except Exception:
        pass
    return None


def make_encounter_id(ep: dict) -> str:
    """
    Genererar ett unikt encounter_id på formatet PURSUE_<år>_<hash8>.
    Hashnyckeln är VIRIN (om det finns) eller title.
    """
    virin = ep.get("virin") or ""
    key   = virin if virin else ep.get("title", "unknown")
    short = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    year  = extract_year(ep.get("incident_date")) or \
            extract_year(ep.get("pub_date")) or "XXXX"
    return f"PURSUE_{year}_{short}"


def ep_to_vals(ep: dict, database_id: int | None) -> dict:
    """Konverterar en PURSUE-post till Odoo encounter-värden."""
    encounter_class = classify(ep)
    incident_dt     = parse_incident_date(ep.get("incident_date"))
    pub_dt          = parse_pub_date(ep.get("pub_date"))

    # research_notes: samla referensdata som inte har eget fält
    notes_parts = []
    if ep.get("file_url"):
        notes_parts.append(f"URL: {ep['file_url']}")
    if ep.get("agency"):
        notes_parts.append(f"Agency: {ep['agency']}")
    if ep.get("virin"):
        notes_parts.append(f"VIRIN: {ep['virin']}")
    if pub_dt:
        notes_parts.append(f"Release date: {pub_dt[:10]}")
    if ep.get("type"):
        notes_parts.append(f"Format: {ep['type']}")
    research_notes = "\n".join(notes_parts)

    vals: dict = {
        "encounter_id":           make_encounter_id(ep),
        "title_en":               (ep.get("title") or "")[:255],
        "title_original":         (ep.get("title") or "")[:255],
        "language_original":      LANGUAGE,
        "description_en":         (ep.get("description") or "")[:4000],
        "description_original":   (ep.get("description") or "")[:4000],
        "location":               (ep.get("incident_location") or "")[:500],
        "encounter_class":        encounter_class,
        "discourse_level":        "5",
        "official_response":      "E",
        "status":                 "pending",
        "eth_origin":             "0",
        "intelligence_indicator": "0",
        "obs_antigravity":        False,
        "obs_instant_accel":      False,
        "obs_hypersonic":         False,
        "obs_low_observability":  False,
        "obs_transmedium":        False,
        "observables_count":      0,
        "research_notes":         research_notes,
    }

    if incident_dt:
        vals["date_observed"] = incident_dt

    if database_id:
        vals["database_id"] = database_id

    return vals


# ---------------------------------------------------------------------------
# Odoo-anslutning
# ---------------------------------------------------------------------------

def get_env():
    import os
    from clio_odoo import connect
    url = os.environ.get("VIGIL_ODOO_URL", "https://uap.arvas.international")
    db  = os.environ.get("VIGIL_ODOO_DB", "uap")
    log.info("Ansluter till %s (db=%s) …", url, db)
    return connect(url=url, db=db)


def _to_int(odoo_id) -> int:
    if isinstance(odoo_id, int):
        return odoo_id
    if hasattr(odoo_id, "id"):
        return int(odoo_id.id)
    try:
        return int(list(odoo_id)[0])
    except Exception:
        return int(odoo_id)


def ensure_database(env) -> int:
    """Hitta eller skapa uap_database-post för PURSUE."""
    Db = env["uap.database"]
    recs = Db.search_read([("name", "=", SOURCE_DB_NAME)], ["id"], limit=1)
    if recs:
        db_id = int(recs[0]["id"])
        log.info("Databas hittad: %s (id=%d)", SOURCE_DB_NAME, db_id)
        return db_id

    db_id = _to_int(Db.create({
        "name":        SOURCE_DB_NAME,
        "db_type":     "archive",
        "db_url":      SOURCE_DB_URL,
        "language":    LANGUAGE,
        "description": (
            "US Government PURSUE initiative — officiella UAP-dokument "
            "releesade via war.gov/UFO/. Inkluderar FD-302-rapporter, "
            "filmanalyser, bildmaterial och debriefings från FBI, DOW, NASA "
            "och andra myndigheter. Discourse level 5 — declassified/official."
        ),
    }))
    log.info("Skapade databas: %s (id=%d)", SOURCE_DB_NAME, db_id)
    return db_id


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

def upsert_encounter(env, vals: dict, dry_run: bool) -> str:
    """
    Upsert ett encounter. Nyckel: encounter_id.
    Returnerar 'created' | 'updated' | 'skipped' | 'error'.
    """
    if dry_run:
        return "dry_run"

    try:
        Enc = env["uap.encounter"]
        existing = Enc.search_read(
            [("encounter_id", "=", vals["encounter_id"])], ["id"], limit=1
        )
        if existing:
            rec_id = int(existing[0]["id"])
            # Uppdatera allt utom encounter_id
            update_vals = {k: v for k, v in vals.items() if k != "encounter_id"}
            Enc.write([rec_id], update_vals)
            return "updated"
        else:
            Enc.create(vals)
            return "created"
    except Exception as exc:
        log.error("  Fel vid upsert av '%s': %s", vals.get("encounter_id"), exc)
        return "error"


# ---------------------------------------------------------------------------
# Huvudlogik
# ---------------------------------------------------------------------------

def run(args) -> None:
    if not JSON_PATH.exists():
        log.error("JSON saknas: %s", JSON_PATH)
        sys.exit(1)

    episodes: list[dict] = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    log.info("Laddade %d poster från %s", len(episodes), JSON_PATH)

    # Filtrera
    to_import = [ep for ep in episodes if not should_skip(ep)]
    skipped_filter = len(episodes) - len(to_import)
    log.info(
        "Filter: %d hoppar (admin/renderings) → %d kvar att importera",
        skipped_filter, len(to_import),
    )

    if args.dry_run:
        log.info("=== DRY-RUN — inget skrivs till Odoo ===")
        # Visa klassfördelning
        from collections import Counter
        class_dist = Counter(classify(ep) for ep in to_import)
        log.info("Klassfördelning: %s", dict(sorted(class_dist.items())))
        # Visa sampel per klass
        for cls in sorted(class_dist):
            sample = next(ep for ep in to_import if classify(ep) == cls)
            log.info(
                "  Klass %s — exempel: %s | %s | date=%s",
                cls,
                sample["title"][:70],
                sample.get("incident_location", "—"),
                sample.get("incident_date", "—"),
            )
        # Visa ett komplett vals-objekt
        sample_vals = ep_to_vals(to_import[0], database_id=None)
        log.info("\nSampel vals (post 0):\n%s",
                 json.dumps(sample_vals, indent=2, ensure_ascii=False, default=str))
        # Kontrollera encounter_id-unikhet
        eids = [make_encounter_id(ep) for ep in to_import]
        if len(eids) != len(set(eids)):
            from collections import Counter
            dupes = [eid for eid, cnt in Counter(eids).items() if cnt > 1]
            log.warning("OBS: %d duplikata encounter_id: %s", len(dupes), dupes[:5])
        else:
            log.info("encounter_id: alla %d unika ✓", len(eids))
        return

    # Anslut till Odoo
    env = get_env()

    # Hämta/skapa databas-post
    log.info("Verifierar PURSUE-databas …")
    database_id = ensure_database(env)

    # Importera
    counts: dict[str, int] = {"created": 0, "updated": 0, "skipped": 0, "error": 0}
    total = len(to_import)

    for i, ep in enumerate(to_import, 1):
        vals   = ep_to_vals(ep, database_id)
        result = upsert_encounter(env, vals, dry_run=False)
        counts[result] = counts.get(result, 0) + 1

        if i <= 5 or i % 50 == 0 or result == "error":
            log.info(
                "[%3d/%d] %s — %s: %s",
                i, total, result.upper(),
                vals["encounter_id"],
                vals["title_en"][:55],
            )

    # Sammanfattning
    print("\n" + "=" * 60)
    print(f"PURSUE encounter-import klar")
    print("=" * 60)
    print(f"  Totalt i JSON:      {len(episodes)}")
    print(f"  Hoppades (filter):  {skipped_filter}")
    print(f"  Bearbetade:         {total}")
    print(f"  Skapade:            {counts['created']}")
    print(f"  Uppdaterade:        {counts['updated']}")
    print(f"  Fel:                {counts['error']}")
    print(f"  Databas-id:         {database_id}")
    print("=" * 60)
    if counts["error"] == 0:
        print("✅ Alla poster importerade utan fel!")
    else:
        print(f"⚠️  {counts['error']} fel — granska loggarna ovan")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importera PURSUE-dokument som uap.encounter i Odoo."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validera och visa statistik utan att skriva till Odoo",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
