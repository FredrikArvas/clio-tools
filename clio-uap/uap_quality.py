"""
uap_quality.py — Datakvalitet för clio_uap

Steg 1: Skapa uap.database-poster för nyckelorganisationer
Steg 2: Koppla database_id på befintliga encounters via URL/textheuristik
Steg 3: Backfill date_observed från title_en (år-extraktion)

Kör: python3 uap_quality.py [--dry-run] [--step 1|2|3|all]
"""
from __future__ import annotations
import argparse, os, re, sys, xmlrpc.client
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = "uapdb"
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
UID    = common.authenticate(DB, USER, PWD, {})
if not UID:
    sys.exit("Odoo-autentisering misslyckades")
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, kwargs=None):
    return M.execute_kw(DB, UID, PWD, model, method, args, kwargs or {})


# ---------------------------------------------------------------------------
# Steg 1 — Skapa uap.database-poster
# ---------------------------------------------------------------------------

KEY_DATABASES = [
    # --- Rapportdatabaser ---
    {
        "org_uap_id":   "USA_1974_NUFORC",
        "name":         "NUFORC — National UFO Reporting Center",
        "db_type":      "reporting",
        "db_url":       "https://nuforc.org/subndx/?id=all",
        "language":     "en",
        "record_count": 170000,
        "description":  "Världens största civila UFO-rapportdatabas. Samlar anonyma rapporter från allmänheten via webb och telefon sedan 1974.",
    },
    {
        "org_uap_id":   "USA_1952_MUFON",
        "name":         "MUFON Case Management System",
        "db_type":      "reporting",
        "db_url":       "https://www.mufon.com/ufo-reports.html",
        "language":     "en",
        "record_count": 80000,
        "description":  "MUFON:s interna ärendehanteringssystem för fältundersökta UAP-rapporter.",
    },
    {
        "org_uap_id":   "INT_2023_ENIGMA",
        "name":         "Enigma Labs UAP Database",
        "db_type":      "reporting",
        "db_url":       "https://enigmalabs.io",
        "language":     "en",
        "record_count": 15000,
        "description":  "Mobilapp och databas för UAP-rapportering med AI-klassificering. Grundad 2022.",
    },
    {
        "org_uap_id":   "INT_2015_UAP_DATA",
        "name":         "UpDB — UAP Database Project",
        "db_type":      "reporting",
        "db_url":       "https://uapdb.com",
        "language":     "en",
        "record_count": 5000,
        "description":  "Crowdsourcad UAP-databas med strukturerat klassificeringssystem.",
    },
    # --- Officiella arkiv ---
    {
        "org_uap_id":   "FRA_1977_GEIPAN",
        "name":         "GEIPAN Public Archive (CNES)",
        "db_type":      "archive",
        "db_url":       "https://www.cnes-geipan.fr/en/recherche",
        "language":     "fr",
        "record_count": 3000,
        "description":  "Officiellt franskt UAP-arkiv hos CNES. Öppet tillgängligt med utredningsrapporter sedan 1977.",
    },
    {
        "org_uap_id":   "SWE_1973_AFU",
        "name":         "AFU Digital Archive",
        "db_type":      "archive",
        "db_url":       "https://www.afu.se/afu-archive/",
        "language":     "sv",
        "record_count": 20000,
        "description":  "Världens största specialiserade UFO-forskningsbibliotek. ~20 000 svenska observationsrapporter + militärfiler (spökraketer 1946–).",
    },
    {
        "org_uap_id":   "USA_1952_BBARCH",
        "name":         "Project Blue Book Archive",
        "db_type":      "archive",
        "db_url":       "https://bluebookarchive.org",
        "language":     "en",
        "record_count": 12618,
        "description":  "Digitaliserade USAF Project Blue Book-filer 1947–1969. 12 618 ärenden.",
    },
    {
        "org_uap_id":   "USA_1947_CIA_RR",
        "name":         "CIA FOIA Electronic Reading Room — UAP",
        "db_type":      "archive",
        "db_url":       "https://www.cia.gov/readingroom/collection/ufos-fact-or-fiction",
        "language":     "en",
        "record_count": 2700,
        "description":  "CIA:s avhemligade UFO-dokument via FOIA, tillgängliga i CIA:s elektroniska läserum.",
    },
    {
        "org_uap_id":   "GBR_2008_UKNATAR",
        "name":         "UK National Archives — UFO Files",
        "db_type":      "archive",
        "db_url":       "https://www.nationalarchives.gov.uk/ufos/",
        "language":     "en",
        "record_count": 52000,
        "description":  "Brittiska försvarsministeriets avhemligade UFO-filer 1950–2009, totalt ~52 000 sidor.",
    },
    {
        "org_uap_id":   "AUS_2012_NAA_UFO",
        "name":         "National Archives of Australia — UFO Files",
        "db_type":      "archive",
        "db_url":       "https://www.naa.gov.au/explore-collection/defence-and-security/unexplained-aerial-sightings",
        "language":     "en",
        "record_count": 1000,
        "description":  "Australiensiska försvarsministeriets avhemligade UAP-filer.",
    },
    {
        "org_uap_id":   "NOR_1981_HESS_ARC",
        "name":         "Project Hessdalen Database",
        "db_type":      "archive",
        "db_url":       "http://www.hessdalen.org/reports/",
        "language":     "en",
        "record_count": 500,
        "description":  "Långtidsdatabas över observerade ljusfenomen i Hessdalens dal, Norge. Aktiv sedan 1983.",
    },
    # --- Officiella rapportdatabaser ---
    {
        "org_uap_id":   "USA_2022_AARO",
        "name":         "AARO Historical Record Archive",
        "db_type":      "registry",
        "db_url":       "https://aaro.mil/Portals/136/PDFs/AARO_Historical_Record_Report_Vol1_2024.pdf",
        "language":     "en",
        "record_count": 800,
        "description":  "All-domain Anomaly Resolution Office:s officiella ärendehistorik. Startade insamling 2022.",
    },
    {
        "org_uap_id":   "USA_1999_NARCAP",
        "name":         "NARCAP Technical Archive",
        "db_type":      "archive",
        "db_url":       "https://narcap.org/technical-reports",
        "language":     "en",
        "record_count": 300,
        "description":  "National Aviation Reporting Center on Anomalous Phenomena — luftfartspilotrapporter med teknisk analys.",
    },
    {
        "org_uap_id":   "USA_1996_BLKVALT",
        "name":         "The Black Vault FOIA Archive",
        "db_type":      "library",
        "db_url":       "https://www.theblackvault.com/documentarchive/ufos/",
        "language":     "en",
        "record_count": 10000,
        "description":  "FOIA-begärda myndighetshandlingar om UAP samlade av John Greenewald Jr.",
    },
    {
        "org_uap_id":   "INT_2000_USO_ARCH",
        "name":         "WaterUFO — USO Archive",
        "db_type":      "archive",
        "db_url":       "http://www.waterufo.net",
        "language":     "en",
        "record_count": 400,
        "description":  "Specialiserat arkiv för Unidentified Submerged Objects (USO) — UAP-fenomen nära/under vatten.",
    },
]

# Nyckelord → databas-uap-ID (för encounter-koppling i steg 2)
DB_URL_PATTERNS = [
    (r"nuforc\.org",                    "USA_1974_NUFORC"),
    (r"mufon\.com",                     "USA_1952_MUFON"),
    (r"cnes-geipan\.fr|geipan\.fr",     "FRA_1977_GEIPAN"),
    (r"afu\.se|afu-archive",            "SWE_1973_AFU"),
    (r"bluebookarchive\.org",           "USA_1952_BBARCH"),
    (r"cia\.gov.*readingroom",          "USA_1947_CIA_RR"),
    (r"nationalarchives\.gov\.uk.*ufo", "GBR_2008_UKNATAR"),
    (r"naa\.gov\.au",                   "AUS_2012_NAA_UFO"),
    (r"hessdalen\.org",                 "NOR_1981_HESS_ARC"),
    (r"aaro\.mil",                      "USA_2022_AARO"),
    (r"narcap\.org",                    "USA_1999_NARCAP"),
    (r"theblackvault\.com",             "USA_1996_BLKVALT"),
    (r"waterufo\.net",                  "INT_2000_USO_ARCH"),
    (r"enigmalabs\.io",                 "INT_2023_ENIGMA"),
]


def step1_create_databases(dry_run: bool):
    print("\n[STEG 1] Skapar uap.database-poster")

    # Bygg cache: uap_encounter_id → partner_id
    partners = kw("res.partner", "search_read",
                  [[["uap_encounter_id", "!=", False]]],
                  {"fields": ["id", "uap_encounter_id"], "limit": 500})
    partner_map = {p["uap_encounter_id"]: p["id"] for p in partners}

    created = skipped = 0
    db_id_cache: dict[str, int] = {}

    for db in KEY_DATABASES:
        org_uap_id = db["org_uap_id"]
        partner_id = partner_map.get(org_uap_id)
        if not partner_id:
            print(f"  VARNING: Hittade ingen partner för {org_uap_id} — hoppar")
            skipped += 1
            continue

        # Kolla om databasen redan finns
        existing = kw("uap.database", "search_count",
                      [[["name", "=", db["name"]], ["partner_id", "=", partner_id]]])
        if existing:
            # Hämta ID för steg 2
            res = kw("uap.database", "search_read",
                     [[["name", "=", db["name"]], ["partner_id", "=", partner_id]]],
                     {"fields": ["id"], "limit": 1})
            if res:
                db_id_cache[org_uap_id] = res[0]["id"]
            print(f"  Finns redan: {db['name']}")
            skipped += 1
            continue

        vals = {
            "name":         db["name"],
            "partner_id":   partner_id,
            "db_type":      db["db_type"],
            "db_url":       db.get("db_url", False),
            "language":     db.get("language", False),
            "record_count": db.get("record_count", 0),
            "description":  db.get("description", False),
        }
        if dry_run:
            print(f"  [DRY] {db['name']} → partner {org_uap_id}")
        else:
            did = kw("uap.database", "create", [vals])
            db_id_cache[org_uap_id] = did
            print(f"  Skapad: {db['name']} → ID {did}")
            created += 1

    if not dry_run:
        print(f"\n  Skapade: {created} | Redan finns: {skipped}")
    print("  Steg 1 klart.")
    return db_id_cache


# ---------------------------------------------------------------------------
# Steg 2 — Koppla database_id på encounters via URL-heuristik
# ---------------------------------------------------------------------------

def step2_link_encounters(db_id_cache: dict[str, int], dry_run: bool):
    print("\n[STEG 2] Kopplar database_id på encounters via URL/text-heuristik")

    if not db_id_cache:
        # Hämta befintliga databaser från Odoo
        dbs = kw("uap.database", "search_read", [[]], {"fields": ["id", "partner_id"], "limit": 200})
        partners = kw("res.partner", "search_read",
                      [[["uap_encounter_id", "!=", False]]],
                      {"fields": ["id", "uap_encounter_id"], "limit": 500})
        pid_to_uapid = {p["id"]: p["uap_encounter_id"] for p in partners}
        for db in dbs:
            pid = db["partner_id"][0] if db["partner_id"] else None
            if pid and pid in pid_to_uapid:
                db_id_cache[pid_to_uapid[pid]] = db["id"]

    if not db_id_cache:
        print("  Inga databaser att koppla till — kör steg 1 först")
        return

    # Hämta encounters utan database_id
    encounters = kw("uap.encounter", "search_read",
                    [[["database_id", "=", False]]],
                    {"fields": ["id", "research_notes", "title_en"], "limit": 2000})
    print(f"  {len(encounters)} encounters utan database_id")

    linked = unmatched = 0
    for enc in encounters:
        text = " ".join(filter(None, [
            enc.get("research_notes") or "",
            enc.get("title_en") or "",
        ])).lower()

        matched_db_id = None
        for pattern, org_uap_id in DB_URL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                matched_db_id = db_id_cache.get(org_uap_id)
                break

        if matched_db_id:
            if dry_run:
                linked += 1
            else:
                kw("uap.encounter", "write", [[enc["id"]], {"database_id": matched_db_id}])
                linked += 1
        else:
            unmatched += 1

    action = "[DRY] Skulle länka" if dry_run else "Länkade"
    print(f"  {action}: {linked} | Ingen matchning: {unmatched}")
    print("  Steg 2 klart.")


# ---------------------------------------------------------------------------
# Steg 3 — Backfill date_observed från title_en
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r'\b(1[5-9]\d{2}|20[0-2]\d)\b')


def extract_year_from_title(title: str) -> int | None:
    for m in _YEAR_RE.finditer(title or ""):
        y = int(m.group(1))
        if y < 2025:
            return y
    return None


def step3_backfill_dates(dry_run: bool):
    print("\n[STEG 3] Backfill date_observed från title_en")

    # Encounters som saknar datum ELLER har datum >= 2025 (import-artefakt)
    all_enc = kw("uap.encounter", "search_read",
                 [[["title_en", "!=", False]]],
                 {"fields": ["id", "title_en", "date_observed"], "limit": 2000})

    candidates = []
    for enc in all_enc:
        d = enc.get("date_observed")
        if d:
            try:
                y = datetime.fromisoformat(str(d)).year
                if y < 2025:
                    continue   # Redan ett historiskt datum — hoppa
            except Exception:
                pass
        candidates.append(enc)

    print(f"  {len(candidates)} encounters utan historiskt datum")

    updated = no_year = 0
    for enc in candidates:
        year = extract_year_from_title(enc.get("title_en") or "")
        if not year:
            no_year += 1
            continue
        date_str = f"{year}-01-01 00:00:00"
        if dry_run:
            updated += 1
        else:
            kw("uap.encounter", "write",
               [[enc["id"]], {"date_observed": date_str}])
            updated += 1

    action = "[DRY] Skulle uppdatera" if dry_run else "Uppdaterade"
    print(f"  {action}: {updated} | Inget år i titel: {no_year}")
    print("  Steg 3 klart.")


# ---------------------------------------------------------------------------
# Sammanfattning
# ---------------------------------------------------------------------------

def print_summary():
    orgs    = kw("res.partner", "search_count", [[["uap_org_type", "!=", False]]])
    dbs     = kw("uap.database", "search_count", [[]])
    enc     = kw("uap.encounter", "search_count", [[]])
    with_db = kw("uap.encounter", "search_count", [[["database_id", "!=", False]]])
    dated   = kw("uap.encounter", "search_count", [[["date_observed", "!=", False]]])
    wit     = kw("uap.encounter.witness", "search_count", [[]])
    print(f"\n{'='*62}")
    print(f"  UAP-databas status efter kvalitetskörning:")
    print(f"  res.partner (org)             : {orgs}")
    print(f"  uap.database                  : {dbs}")
    print(f"  uap.encounter (total)         : {enc}")
    print(f"  uap.encounter med database_id : {with_db} ({with_db*100//enc if enc else 0}%)")
    print(f"  uap.encounter med datum       : {dated} ({dated*100//enc if enc else 0}%)")
    print(f"  uap.encounter.witness         : {wit}")
    print(f"{'='*62}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--step", choices=["1", "2", "3", "all"], default="all")
    args = ap.parse_args()

    dry = args.dry_run
    if dry:
        print("*** DRY RUN — inga ändringar sparas ***")

    db_cache: dict[str, int] = {}

    if args.step in ("1", "all"):
        db_cache = step1_create_databases(dry)
    if args.step in ("2", "all"):
        step2_link_encounters(db_cache, dry)
    if args.step in ("3", "all"):
        step3_backfill_dates(dry)

    if not dry:
        print_summary()
