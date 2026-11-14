"""
uap_import_geipan.py — Importera GEIPAN-fall till uap.report (Odoo 19)

Kalla:
  python3 uap_import_geipan.py [--dry-run] [--limit N] [--class A B C D]

GEIPAN klassificering:
  A = Cas non identifie (oidentifierat)
  B = Cas probablement identifiable
  C = Cas vraisemblablement identifiable
  D = Cas identifie (fullt forklarat)

Standard importerar alla klasser.
"""
from __future__ import annotations
import argparse, os, re, sys, time, urllib.request, xmlrpc.client
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
_BASE = Path(__file__).parent
_ROOT = _BASE.parent
load_dotenv(_ROOT / ".env", override=True)
load_dotenv(_BASE / ".env", override=True)

URL  = os.getenv("ODOO_URL", "https://uap.arvas.international")
DB   = os.getenv("ODOO_DB", "uap")
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

GEIPAN_EXPORT_URL = "https://www.geipan.fr/fr/cnes/export/cas"
CACHE_PATH = Path("/tmp/geipan_cas.xlsx")
CACHE_MAX_DAYS = 7
UA = "clio-uap-research/1.0 (contact: research@arvas.international)"

# GEIPAN klassificering -> encounter_class-notering i beskrivning
CLASS_LABELS = {
    "A": "GEIPAN A (Non identifie)",
    "B": "GEIPAN B (Probablement identifiable)",
    "C": "GEIPAN C (Vraisemblablement identifiable)",
    "D": "GEIPAN D (Identifie)",
}

# Kolumnindex i Excel-filen
COL_ID      = 0   # ID Etude de Cas
COL_TITRE   = 1   # Titre du Cas
COL_DETAILS = 2   # Details
COL_ANNEE   = 3   # Annee
COL_IDENT   = 4   # Identification
COL_CLASS   = 5   # Classification (A/B/C/D)
COL_DEPT_C  = 6   # Code departement
COL_DATE    = 7   # Date d'observation
COL_DEPT    = 8   # Departement
COL_DOC     = 9   # Document pour cas
COL_HAS_DOC = 10  # Cas contenant des documents
COL_NEW     = 11  # Nouveau cas
COL_REVISIT = 12  # Cas revisite
COL_LAT     = 13  # Latitude
COL_LON     = 14  # Longitude
COL_PHENOM  = 15  # Phenomene
COL_REGION  = 16  # Region
COL_TEMOIG  = 17  # Temoignage associe
COL_TYPE    = 18  # Type de cas

# ---------------------------------------------------------------------------
# Odoo
# ---------------------------------------------------------------------------
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
UID    = common.authenticate(DB, USER, PWD, {})
if not UID:
    sys.exit("Odoo-autentisering misslyckades")
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, kwargs=None):
    return M.execute_kw(DB, UID, PWD, model, method, args, kwargs or {})

# ---------------------------------------------------------------------------
# Hjalp
# ---------------------------------------------------------------------------

def download_xlsx() -> Path:
    if CACHE_PATH.exists():
        age = (time.time() - CACHE_PATH.stat().st_mtime) / 86400
        if age < CACHE_MAX_DAYS:
            print(f"  Anvaender cachad XLSX ({age:.1f} dagar gammal)")
            return CACHE_PATH
    print("  Laddar ned GEIPAN-export ...")
    req = urllib.request.Request(GEIPAN_EXPORT_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        CACHE_PATH.write_bytes(r.read())
    print(f"  Klar ({CACHE_PATH.stat().st_size // 1024} kB)")
    return CACHE_PATH


def parse_geipan_date(date_str: str, year_int) -> str | None:
    """Omvandlar '--/--/1937' -> '1937-01-01', '--/08/1947' -> '1947-08-01'."""
    if not date_str:
        return f"{int(year_int)}-01-01" if year_int else None
    date_str = str(date_str).strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", date_str)
    if m:
        d, mo, y = m.groups()
        try:
            return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d 00:00:00")
        except ValueError:
            pass
    m2 = re.match(r"--/(\d{2})/(\d{4})", date_str)
    if m2:
        mo, y = m2.groups()
        return f"{y}-{mo}-01 00:00:00"
    m3 = re.match(r"--/--/(\d{4})", date_str)
    if m3:
        return f"{m3.group(1)}-01-01 00:00:00"
    if year_int:
        return f"{int(year_int)}-01-01 00:00:00"
    return None


def get_or_create_geipan_db() -> int:
    res = kw("uap.database", "search_read",
             [[["name", "like", "GEIPAN"]]],
             {"fields": ["id", "name"], "limit": 1})
    if res:
        print(f"  Anvaender uap.database: {res[0]['name']} (ID {res[0]['id']})")
        return res[0]["id"]
    did = kw("uap.database", "create", [{
        "name":        "GEIPAN — Groupe d'Etudes et d'Informations sur les PAN",
        "db_type":     "reporting",
        "db_url":      "https://www.geipan.fr",
        "description": (
            "Officiell fransk UAP-utredningsgrupp under CNES. "
            "Grundad 1977 som GEPAN, ombildad 2005. "
            "Klassificering A (oidentifierat) till D (fullt forklarat)."
        ),
        "language":    "fr",
    }])
    print(f"  Skapade uap.database GEIPAN (ID {did})")
    return did


def get_existing_geipan_ids() -> set[str]:
    res = kw("uap.report", "search_read",
             [[["external_id", "like", "GEIPAN-"]]],
             {"fields": ["external_id"], "limit": 10_000})
    return {r["external_id"] for r in res}


def get_france_country_id() -> int:
    res = kw("res.country", "search_read",
             [[["code", "=", "FR"]]],
             {"fields": ["id"], "limit": 1})
    if not res:
        sys.exit("Hittade inte Frankrike (FR) i Odoo")
    return res[0]["id"]

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool, limit: int | None, classes: list[str]):
    import openpyxl

    print(f"\n{'='*60}")
    print(f"  GEIPAN Import  {'[DRY RUN] ' if dry_run else ''}")
    print(f"  Klasser: {', '.join(classes)}")
    print(f"{'='*60}")

    xlsx_path = download_xlsx()
    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    ws = wb.active

    geipan_db_id = get_or_create_geipan_db()
    france_id    = get_france_country_id()
    existing_ids = get_existing_geipan_ids()
    batch        = f"geipan_{datetime.now().strftime('%Y_%m_%d')}"

    print(f"  Redan importerade GEIPAN-poster: {len(existing_ids)}")

    created = skipped = errors = 0
    first_row = True

    for row in ws.iter_rows(values_only=True):
        if first_row:
            first_row = False
            continue  # Hoppa over header

        case_id = str(row[COL_ID] or "").strip()
        if not case_id:
            continue

        cls = str(row[COL_CLASS] or "").strip().upper()
        if cls not in classes:
            continue

        ext_id = f"GEIPAN-{case_id}"
        if ext_id in existing_ids:
            skipped += 1
            continue

        if limit and (created + errors) >= limit:
            break

        date_str = parse_geipan_date(str(row[COL_DATE] or ""), row[COL_ANNEE])
        titre    = str(row[COL_TITRE] or "").strip()
        details  = str(row[COL_DETAILS] or "").strip()
        ident    = str(row[COL_IDENT] or "").strip()
        dept     = str(row[COL_DEPT] or "").strip()
        region   = str(row[COL_REGION] or "").strip()
        phenom   = str(row[COL_PHENOM] or "").strip()
        type_cas = str(row[COL_TYPE] or "").strip()

        try:
            lat = float(row[COL_LAT]) if row[COL_LAT] not in (None, "", "None") else 0.0
            lon = float(row[COL_LON]) if row[COL_LON] not in (None, "", "None") else 0.0
        except (ValueError, TypeError):
            lat = lon = 0.0

        location_parts = [p for p in [dept, region] if p]
        location_text  = ", ".join(location_parts) or None

        description = f"[{CLASS_LABELS.get(cls, cls)}]\n"
        if ident:
            description += f"Identification: {ident}\n"
        if phenom:
            description += f"Phenomene: {phenom}\n"
        if type_cas:
            description += f"Type: {type_cas}\n"
        if details:
            description += f"\n{details}"

        vals = {
            "database_id":     geipan_db_id,
            "import_batch":    batch,
            "external_id":     ext_id,
            "raw_title":       titre or f"GEIPAN {case_id}",
            "raw_description": description[:4000],
            "report_date":     date_str or False,
            "country_id":      france_id,
            "location_text":   location_text or False,
            "geo_lat":         lat,
            "geo_lng":         lon,
            "reporter_type":   "civilian",
            "status":          "unlinked",
        }

        if dry_run:
            if created < 5:
                print(f"  [DRY] {cls} | {titre[:60]}")
                print(f"         date={date_str} lat={lat:.4f} lon={lon:.4f}")
            created += 1
        else:
            try:
                kw("uap.report", "create", [vals])
                existing_ids.add(ext_id)
                created += 1
                if created % 200 == 0:
                    print(f"  ... {created} skapade")
            except Exception as e:
                print(f"  FEL {ext_id}: {e}")
                errors += 1

    print(f"\n{'='*60}")
    print(f"  Skapade   : {created}")
    print(f"  Skippade  : {skipped}")
    print(f"  Fel       : {errors}")
    if not dry_run and created:
        total = kw("uap.report", "search_count", [[]])
        print(f"  Totalt uap.report i Odoo: {total}")
    print(f"{'='*60}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run",  action="store_true")
    ap.add_argument("--limit",    type=int, default=None)
    ap.add_argument("--class",    dest="classes", nargs="+",
                    default=["A", "B", "C", "D"],
                    help="Importera bara dessa klasser, t.ex. --class A B")
    args = ap.parse_args()
    run(args.dry_run, args.limit, [c.upper() for c in args.classes])
