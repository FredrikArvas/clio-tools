"""
uap_import_nuforc.py — Importera NUFORC-rapporter → uap.report

Källa: github.com/planetsig/ufo-reports (80 332 rader, 5 länder)
Väljer max --max-per-country rapporter per land, prioriterar poster med koordinater.

Kör: python3 uap_import_nuforc.py [--dry-run] [--max-per-country 100] [--country gb]
"""
from __future__ import annotations
import argparse, csv, hashlib, html, os, re, sys, time, urllib.request, xmlrpc.client
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = "uapdb"
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

NUFORC_CSV_URL = (
    "https://raw.githubusercontent.com/planetsig/ufo-reports/master/"
    "csv-data/ufo-scrubbed-geocoded-time-standardized.csv"
)
CACHE_PATH = Path("/tmp/nuforc_cache.csv")
CACHE_MAX_AGE_DAYS = 7

# Kolumnindex (ingen headerrad)
COL_DATETIME  = 0
COL_CITY      = 1
COL_STATE     = 2
COL_COUNTRY   = 3
COL_SHAPE     = 4
COL_DUR_S     = 5
COL_DUR_TEXT  = 6
COL_COMMENTS  = 7
COL_POSTED    = 8
COL_LAT       = 9
COL_LON       = 10

# ---------------------------------------------------------------------------
# Odoo-anslutning
# ---------------------------------------------------------------------------
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
UID    = common.authenticate(DB, USER, PWD, {})
if not UID:
    sys.exit("Odoo-autentisering misslyckades")
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, kwargs=None):
    return M.execute_kw(DB, UID, PWD, model, method, args, kwargs or {})


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def download_csv() -> Path:
    """Laddar ned NUFORC-CSV om cache saknas eller är för gammal."""
    if CACHE_PATH.exists():
        age_days = (time.time() - CACHE_PATH.stat().st_mtime) / 86400
        if age_days < CACHE_MAX_AGE_DAYS:
            print(f"  Använder cachad CSV ({CACHE_PATH}, {age_days:.1f} dagar gammal)")
            return CACHE_PATH
    print(f"  Laddar ned NUFORC CSV från GitHub...")
    urllib.request.urlretrieve(NUFORC_CSV_URL, CACHE_PATH)
    size_mb = CACHE_PATH.stat().st_size / 1_048_576
    print(f"  Klar ({size_mb:.1f} MB)")
    return CACHE_PATH


def parse_nuforc_date(dt_str: str) -> str | None:
    """'10/10/1949 20:30' → '1949-10-10 20:30:00'"""
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(dt_str.strip(), fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


def row_external_id(row: list) -> str:
    """Stabilt externt ID baserat på datum + plats + kommentarsinledning."""
    key = "|".join([row[COL_DATETIME], row[COL_CITY], row[COL_STATE],
                    row[COL_COMMENTS][:80]])
    return "nuforc_" + hashlib.md5(key.encode()).hexdigest()[:16]


def build_title(row: list) -> str:
    shape = (row[COL_SHAPE] or "").capitalize() or "UFO"

    # Rensa city: ta bort parentetiska tillägg som "(uk/england)"
    city_raw = row[COL_CITY] or ""
    city = re.sub(r"\s*\([^)]*\)", "", city_raw).strip().title()

    state   = (row[COL_STATE] or "").upper()
    country = (row[COL_COUNTRY] or "").upper()

    # Extrahera år ur "MM/DD/YYYY HH:MM"
    try:
        year = row[COL_DATETIME].split("/")[2].split(" ")[0]
    except (IndexError, AttributeError):
        year = ""

    if state and country == "US":
        location = f"{city}, {state}" if city else state
    else:
        location = city

    return f"{shape} sighting — {location} ({year})" if location else f"{shape} sighting ({year})"


def get_or_create_nuforc_db() -> int:
    """Hämtar NUFORC uap.database ID, skapar om det saknas."""
    res = kw("uap.database", "search_read",
             [[["name", "like", "NUFORC"]]],
             {"fields": ["id", "name"], "limit": 1})
    if res:
        print(f"  Använder uap.database: {res[0]['name']} (ID {res[0]['id']})")
        return res[0]["id"]
    # Skapa ny
    did = kw("uap.database", "create", [{
        "name":        "NUFORC — National UFO Reporting Center",
        "db_type":     "reporting",
        "db_url":      "https://nuforc.org",
        "description": "Nordamerikansk rapporteringscentral för UAP/UFO-observationer. "
                       "Tar emot rapporter från allmänheten sedan 1974.",
        "language":    "en",
    }])
    print(f"  Skapade uap.database NUFORC (ID {did})")
    return did


def get_country_map() -> dict[str, int]:
    """Hämtar alla länder från Odoo: {'US': 233, 'GB': 75, ...}"""
    countries = kw("res.country", "search_read", [[]], {"fields": ["id", "code"]})
    return {c["code"].upper(): c["id"] for c in countries}


def get_existing_external_ids() -> set[str]:
    """Hämtar alla nuforc_*-external_ids som redan finns i uap.report."""
    res = kw("uap.report", "search_read",
             [[["external_id", "like", "nuforc_"]]],
             {"fields": ["external_id"], "limit": 100_000})
    return {r["external_id"] for r in res}


# ---------------------------------------------------------------------------
# Huvud-pipeline
# ---------------------------------------------------------------------------

def load_and_filter(csv_path: Path, max_per_country: int,
                    only_country: str | None) -> dict[str, list]:
    """
    Läser CSV, grupperar per land, väljer max_per_country per land.
    Prioriterar rader MED koordinater.
    Returnerar {country_code: [row, ...]}
    """
    by_country: dict[str, list] = {}

    with open(csv_path, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 10:
                continue
            cc = row[COL_COUNTRY].strip().lower()
            if not cc:
                continue
            if only_country and cc != only_country.lower():
                continue
            by_country.setdefault(cc, []).append(row)

    # Sortera per land: koordinater först, sedan datum (nyast sist = vi tar slutet)
    result: dict[str, list] = {}
    for cc, rows in by_country.items():
        has_coords = [r for r in rows if r[COL_LAT].strip() and r[COL_LON].strip()]
        no_coords  = [r for r in rows if not r[COL_LAT].strip() or not r[COL_LON].strip()]
        # Kombinera: koordinater först, fyll upp med resten till max
        chosen = (has_coords + no_coords)[:max_per_country]
        result[cc] = chosen

    return result


def run(max_per_country: int, only_country: str | None, dry_run: bool,
        import_batch: str):
    print(f"\n{'='*60}")
    print(f"  NUFORC Import  {'[DRY RUN] ' if dry_run else ''}")
    print(f"  Batch: {import_batch}")
    print(f"{'='*60}")

    # Steg 1: ladda data
    csv_path = download_csv()
    grouped  = load_and_filter(csv_path, max_per_country, only_country)

    total_rows = sum(len(v) for v in grouped.values())
    print(f"\n  Länder: {len(grouped)} | Rapporter att bearbeta: {total_rows}")
    for cc, rows in sorted(grouped.items()):
        print(f"    {cc.upper()}: {len(rows)}")

    # Steg 2: Odoo-uppslag
    nuforc_db_id  = get_or_create_nuforc_db()
    country_map   = get_country_map()
    existing_ids  = get_existing_external_ids()
    print(f"\n  Redan importerade NUFORC-poster: {len(existing_ids)}")

    # Steg 3: importera
    created = skipped = errors = 0
    t0 = time.time()

    for cc, rows in sorted(grouped.items()):
        odoo_country_id = country_map.get(cc.upper(), False)
        if not odoo_country_id:
            print(f"  VARNING: land '{cc}' hittades inte i Odoo — hoppar över")
            continue

        for row in rows:
            ext_id = row_external_id(row)
            if ext_id in existing_ids:
                skipped += 1
                continue

            report_date = parse_nuforc_date(row[COL_DATETIME])
            if not report_date:
                errors += 1
                continue

            try:
                lat = float(row[COL_LAT]) if row[COL_LAT].strip() else 0.0
                lon = float(row[COL_LON]) if row[COL_LON].strip() else 0.0
            except ValueError:
                lat = lon = 0.0

            description = html.unescape(row[COL_COMMENTS]).strip()
            title       = build_title(row)
            state_city  = f"{row[COL_CITY].strip()}, {row[COL_STATE].strip()}".strip(", ")
            duration    = row[COL_DUR_TEXT].strip() or False

            vals = {
                "database_id":    nuforc_db_id,
                "import_batch":   import_batch,
                "external_id":    ext_id,
                "raw_title":      title,
                "raw_description":description[:4000] if description else False,
                "report_date":    report_date,
                "country_id":     odoo_country_id,
                "location_text":  state_city or False,
                "geo_lat":        lat,
                "geo_lng":        lon,
                "shape":          row[COL_SHAPE].strip() or False,
                "duration_text":  duration,
                "reporter_type":  "civilian",
                "status":         "unlinked",
            }

            if dry_run:
                if created < 5:
                    print(f"  [DRY] {cc.upper()} | {title[:60]}")
                    print(f"         lat={lat:.4f} lon={lon:.4f} date={report_date[:10]}")
                created += 1
            else:
                try:
                    kw("uap.report", "create", [vals])
                    existing_ids.add(ext_id)
                    created += 1
                except Exception as e:
                    print(f"  FEL {ext_id}: {e}")
                    errors += 1

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Skapade  : {created}")
    print(f"  Skippade : {skipped} (redan importerade)")
    print(f"  Fel      : {errors}")
    print(f"  Tid      : {elapsed:.1f}s")
    if not dry_run and created:
        total = kw("uap.report", "search_count", [[]])
        print(f"  Totalt uap.report i Odoo: {total}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run",          action="store_true")
    ap.add_argument("--max-per-country",  type=int, default=100)
    ap.add_argument("--country",          default=None,
                    help="Importera bara ett land, t.ex. 'gb'")
    args = ap.parse_args()

    batch = f"nuforc_{datetime.now().strftime('%Y_%m_%d')}"

    if args.dry_run:
        print("*** DRY RUN — inga poster skapas ***")

    run(args.max_per_country, args.country, args.dry_run, batch)
