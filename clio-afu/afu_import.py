#!/usr/bin/env python3
"""
afu_import.py — Generisk importpipeline för strukturerade UAP-listor

Steg:
  1. Läs fil (PDF/CSV/TSV/TXT) och extrahera text
  2. Detektera format och parse:a till lista av raw dicts
  3. Mappa fält → Odoo UAP-modell (encounter + report)
  4. Deduplicera mot befintliga records (import_batch + external_id)
  5. Importera till Odoo via XML-RPC

Inbyggda parsers:
  - larry_hatch    data/downloads/Databases/Larry Hatch/derivations/Larry Hatch - full text.pdf

Usage:
    python3 afu_import.py --parser larry_hatch [--dry-run] [--max 500]
    python3 afu_import.py --parser larry_hatch --file /path/to/custom.pdf
    python3 afu_import.py --parser larry_hatch --cleanup   # tar bort orphaned records
"""

import argparse
import json
import os
import re
import sys
import xmlrpc.client
from datetime import datetime
from pathlib import Path

try:
    import fitz          # pymupdf
except ImportError:
    fitz = None

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass

# ─── Odoo-koppling ────────────────────────────────────────────────────────────

def odoo_connect():
    url  = os.environ.get("VIGIL_ODOO_URL", "http://100.107.127.104:8079")
    db   = os.environ.get("VIGIL_ODOO_DB",  "uap")
    user = os.environ.get("VIGIL_ODOO_USER", "admin")
    pwd  = (os.environ.get("VIGIL_ODOO_PASSWORD")
            or os.environ.get("ODOO_ADMIN_PASSWORD")
            or os.environ.get("ODOO_PASSWORD"))
    if not pwd:
        sys.exit("Sätt VIGIL_ODOO_PASSWORD i .env")

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid    = common.authenticate(db, user, pwd, {})
    if not uid:
        sys.exit("Odoo-inloggning misslyckades")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return models, db, uid, pwd


def odoo_get_or_create_database(models, db, uid, pwd, name: str) -> int:
    recs = models.execute_kw(db, uid, pwd, "uap.database", "search_read",
        [[["name", "=", name]]], {"fields": ["id"], "limit": 1})
    if recs:
        return recs[0]["id"]
    new_id = models.execute_kw(db, uid, pwd, "uap.database", "create", [{"name": name}])
    print(f"  Skapade uap.database: '{name}' (id={new_id})")
    return new_id


def odoo_country_map(models, db, uid, pwd) -> dict:
    recs = models.execute_kw(db, uid, pwd, "res.country", "search_read",
        [[]], {"fields": ["id", "code"], "limit": 0})
    return {r["code"]: r["id"] for r in recs}


def odoo_existing_external_ids(models, db, uid, pwd, import_batch: str) -> set:
    """Hämtar external_id för befintliga uap.report med denna import_batch."""
    recs = models.execute_kw(db, uid, pwd, "uap.report", "search_read",
        [[["import_batch", "=", import_batch]]],
        {"fields": ["external_id"], "limit": 0})
    return {r["external_id"] for r in recs if r.get("external_id")}


def odoo_cleanup_batch(models, db, uid, pwd, import_batch: str):
    """Tar bort alla orphaned uap.report med denna import_batch (encounter_id = False)."""
    ids = models.execute_kw(db, uid, pwd, "uap.report", "search",
        [[["import_batch", "=", import_batch], ["encounter_id", "=", False]]])
    if not ids:
        print(f"  Inga orphaned reports hittades för batch '{import_batch}'")
        return 0
    print(f"  Tar bort {len(ids)} orphaned uap.report-poster...")
    models.execute_kw(db, uid, pwd, "uap.report", "unlink", [ids])
    print(f"  Borttagna: {len(ids)} poster")
    return len(ids)


def odoo_create_encounter_report_pairs(models, db, uid, pwd, records: list,
                                        database_id: int, country_map: dict,
                                        batch_size=100) -> int:
    """
    Skapar encounter+report-par i Odoo.
    Strategi: skapa encounters i batchar, hämta tillbaka ID:n, skapa reports med encounter_id.
    """
    created = 0
    total = len(records)

    for i in range(0, total, batch_size):
        batch = records[i:i+batch_size]
        batch_num = i // batch_size + 1

        # Steg A: skapa encounters
        enc_vals = [r["encounter"] for r in batch]
        enc_ids  = models.execute_kw(db, uid, pwd, "uap.encounter", "create", [enc_vals])
        if isinstance(enc_ids, int):
            enc_ids = [enc_ids]

        # Steg B: skapa reports länkade till encounters
        rep_vals = []
        for j, rep in enumerate(r["report"] for r in batch):
            rep["encounter_id"] = enc_ids[j]
            rep_vals.append(rep)
        models.execute_kw(db, uid, pwd, "uap.report", "create", [rep_vals])

        created += len(batch)
        pct = round(created / total * 100)
        print(f"  Batch {batch_num}: {len(batch)} par skapade ({created}/{total}, {pct}%)")

    return created

# ─── PDF-textextraktion ───────────────────────────────────────────────────────

def extract_pdf_text(path: Path) -> str:
    if fitz:
        doc  = fitz.open(str(path))
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    try:
        from pdfminer.high_level import extract_text as pm_extract
        return pm_extract(str(path))
    except ImportError:
        sys.exit("Installera pymupdf: pip install pymupdf  (eller pdfminer.six)")

# ─── Larry Hatch parser ───────────────────────────────────────────────────────

LARRY_HATCH_COUNTRY_CODES = {
    "USA": "US", "CAN": "CA", "GBI": "GB", "GBR": "GB", "UK": "GB", "ENGL": "GB",
    "FRN": "FR", "FRA": "FR", "SWE": "SE", "SWD": "SE", "NOR": "NO", "NORW": "NO",
    "DNK": "DK", "DK": "DK", "FIN": "FI", "FINL": "FI",
    "DEU": "DE", "GER": "DE", "RUS": "RU", "USS": "RU", "USSR": "RU",
    "AUS": "AU", "NZL": "NZ", "NZ": "NZ",
    "BRA": "BR", "BRZ": "BR", "BRZL": "BR",
    "ARG": "AR", "MEX": "MX",
    "VEN": "VE", "VNZ": "VE", "VNZL": "VE",
    "ITL": "IT", "ITA": "IT", "ESP": "ES", "SPN": "ES", "PRT": "PT",
    "NLD": "NL", "NETH": "NL", "NETHL": "NL",
    "BEL": "BE", "BELG": "BE",
    "CHE": "CH", "SWI": "CH", "CH": "CH", "SWITZ": "CH", "SWZ": "CH",
    "AUT": "AT", "POL": "PL", "CZE": "CZ", "CSK": "CZ", "CZK": "CZ",
    "HUN": "HU", "ROM": "RO", "BGR": "BG", "SRB": "RS", "HRV": "HR",
    "GRC": "GR", "TUR": "TR", "ISR": "IL", "IRQ": "IQ",
    "IRN": "IR", "LEB": "LB", "SYR": "SY", "EGY": "EG",
    "ZAF": "ZA", "RSA": "ZA", "ZWE": "ZW", "RHOD": "ZW",
    "JPN": "JP", "CHN": "CN", "CHINA": "CN",
    "IND": "IN", "BRM": "MM", "KOR": "KR", "TWN": "TW",
    "PHL": "PH", "IDN": "ID", "MYS": "MY", "PNG": "PG",
    "ARB": "AE", "UAE": "AE",
    "PER": "PE", "PERU": "PE", "COL": "CO", "CHL": "CL",
    "URG": "UY", "URUG": "UY",
    "CUBA": "CU", "GUAT": "GT",
    "UKR": "UA", "ICL": "IS", "ISL": "IS",
    "ALG": "DZ", "MAROC": "MA", "LIBYA": "LY",
    "KENYA": "KE", "IVORY": "CI",
    "YUGO": "RS", "YUG": "RS",
    "NEPAL": "NP",
}

# Larry Hatch type-kod första siffra → encounter_class (string som Odoo selection)
LH_TYPE_TO_CLASS = {"1": "1", "2": "1", "3": "2", "4": "3", "5": "4", "6": "4", "7": "1", "8": "3", "9": "1"}

DATA_LINE_RE = re.compile(
    r"^\s+(\d+):\s+(-?\d{1,4})/(\d{2})/(\d{2})\s+(\d{2}:\d{2})"
    r"\s+(\d+)"
    r"\s+(\d+):(\d+):(\d+)\s+(E|W)"
    r"\s+(\d+):(\d+):(\d+)\s+(N|S)"
    r"\s+(\d{4})\s+([A-Z]{3})\s+([A-Z]{3})"
)


def _dms_to_dec(d, m, s, direction):
    val = int(d) + int(m) / 60 + int(s) / 3600
    return -round(val, 5) if direction in ("W", "S") else round(val, 5)


def parse_larry_hatch(path: Path) -> list:
    print(f"Extraherar text från {path.name} ...")
    text = extract_pdf_text(path)
    print(f"  {len(text):,} tecken extraherade")

    lines   = text.splitlines()
    records = []
    seen    = set()

    i = 0
    while i < len(lines):
        m = DATA_LINE_RE.match(lines[i])
        if not m:
            i += 1
            continue

        year, month, day = int(m.group(2)), int(m.group(3)), int(m.group(4))
        time_str = m.group(5)

        if year < 1000 or not (1 <= month <= 12) or not (1 <= day <= 31):
            i += 1
            continue

        try:
            from datetime import date as _date
            _date(year, month, day)
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
        except (ValueError, Exception):
            i += 1
            continue

        lon = _dms_to_dec(m.group(7), m.group(8), m.group(9), m.group(10))
        lat = _dms_to_dec(m.group(11), m.group(12), m.group(13), m.group(14))
        type_code    = m.group(15)
        country_code = m.group(17)
        country      = LARRY_HATCH_COUNTRY_CODES.get(country_code, country_code)
        encounter_class = LH_TYPE_TO_CLASS.get(type_code[0], "1")

        desc = ""
        location_raw = ""
        j = i + 1
        while j < len(lines):
            stripped = lines[j].strip()
            if stripped and not stripped.startswith("Ref#"):
                full_desc = re.sub(r"\s{2,}", " ", stripped)
                if ":" in full_desc:
                    location_raw = full_desc.split(":")[0].strip()[:80]
                    desc = full_desc[len(location_raw)+1:].strip()[:500]
                else:
                    desc = full_desc[:500]
                break
            if stripped.startswith("Ref#"):
                break
            j += 1

        key = (date_str, round(lat, 3), round(lon, 3))
        if key not in seen:
            seen.add(key)
            records.append({
                "date_event":             date_str,
                "time_event":             time_str,
                "latitude":               lat,
                "longitude":              lon,
                "country":                country,
                "location_raw":           location_raw,
                "description_en":         desc,
                "encounter_class":        encounter_class,
                "source":                 "larry_hatch",
                "discourse_level":        2,
                "eth_origin":             "0",
                "intelligence_indicator": "0",
            })
        i += 1

    print(f"  {len(records)} giltiga records parsade")
    return records

# ─── Parser-register ──────────────────────────────────────────────────────────

DEFAULT_PATHS = {
    "larry_hatch": Path(__file__).parent / "data/downloads/Databases/Larry Hatch/derivations/Larry Hatch - full text.pdf",
}

PARSERS = {
    "larry_hatch": parse_larry_hatch,
}

# ─── Mapping → Odoo encounter + report ───────────────────────────────────────

IMPORT_BATCH = "larry_hatch_afu_20260925"

def map_to_odoo_pair(rec: dict, database_id: int, country_map: dict) -> dict:
    """Konverterar en parsad record till ett dict med 'encounter' och 'report'."""
    date       = rec.get("date_event", "")
    time_val   = rec.get("time_event", "00:00")
    lat        = rec.get("latitude")
    lon        = rec.get("longitude")
    location   = rec.get("location_raw", "")
    year       = date[:4] if date else "?"
    country    = rec.get("country", "")

    ext_id     = f"lh_{date}_{round(lat or 0, 3)}_{round(lon or 0, 3)}"
    title      = f"UAP sighting — {location or country} {year}".strip()
    dt_str     = f"{date} {time_val}:00" if date else False
    country_id = country_map.get(country) if country else False

    encounter = {
        "database_id":            database_id,
        "title_en":               title,
        "date_observed":          dt_str,
        "description_en":         rec.get("description_en", "") or "",
        "discourse_level":        rec.get("discourse_level", 2),
        "eth_origin":             rec.get("eth_origin", "0"),
        "intelligence_indicator": rec.get("intelligence_indicator", "0"),
        "encounter_class":        rec.get("encounter_class", "1"),
        "status":                 "pending",
    }
    if country_id:
        encounter["country_id"] = country_id
    if location:
        encounter["location"] = location

    report = {
        "database_id":     database_id,
        "import_batch":    IMPORT_BATCH,
        "external_id":     ext_id,
        "report_date":     dt_str,
        "raw_description": rec.get("description_en", "") or "",
        "raw_title":       title,
    }
    if lat is not None:
        report["geo_lat"] = lat
    if lon is not None:
        report["geo_lng"] = lon
    if country_id:
        report["country_id"] = country_id

    return {"encounter": encounter, "report": report, "external_id": ext_id}

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Importera strukturerade UAP-listor till Odoo")
    parser.add_argument("--parser",  required=True, choices=list(PARSERS.keys()))
    parser.add_argument("--file",    help="Sökväg till fil (överstyr standard)")
    parser.add_argument("--dry-run", action="store_true", help="Parsa men importera inte")
    parser.add_argument("--max",     type=int, default=0, help="Max antal records att importera")
    parser.add_argument("--save-json", action="store_true")
    parser.add_argument("--cleanup",  action="store_true",
                        help="Ta bort orphaned uap.report (encounter_id=False) för denna batch")
    args = parser.parse_args()

    file_path = Path(args.file) if args.file else DEFAULT_PATHS.get(args.parser)
    if not file_path or not file_path.exists():
        sys.exit(f"Fil hittades inte: {file_path}\nKör afu_files_crawl.py --mode fetch först.")

    # Cleanup-läge: ta bort orphaned records
    if args.cleanup:
        models, db, uid, pwd = odoo_connect()
        print(f"Cleanup: tar bort orphaned uap.report med import_batch='{IMPORT_BATCH}'...")
        n = odoo_cleanup_batch(models, db, uid, pwd, IMPORT_BATCH)
        print(f"Cleanup klar: {n} poster borttagna")
        return

    # Parsa
    parse_fn = PARSERS[args.parser]
    records  = parse_fn(file_path)

    if args.save_json or args.dry_run:
        out = Path(__file__).parent / "data" / f"afu_{args.parser}.json"
        out.write_text(json.dumps(records[:500], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Exempeldata (500 rec) → {out}")

    if args.max:
        records = records[:args.max]

    print(f"\n{len(records)} records redo för import")

    if args.dry_run:
        print("(dry-run — importerar inte)")
        countries = {}
        for r in records:
            c = r.get("country", "?")
            countries[c] = countries.get(c, 0) + 1
        print("\nTop 15 länder:")
        for c, n in sorted(countries.items(), key=lambda x: -x[1])[:15]:
            print(f"  {c:5s}: {n}")
        return

    # Koppla Odoo
    models, db, uid, pwd = odoo_connect()
    print("Ansluten till Odoo UAP-databas")

    database_id = odoo_get_or_create_database(
        models, db, uid, pwd,
        "Larry Hatch *U* Database — AFU derivation"
    )
    print(f"  database_id = {database_id}")

    country_map = odoo_country_map(models, db, uid, pwd)
    print(f"  {len(country_map)} länder laddade")

    print("Hämtar befintliga records för deduplicering...")
    existing = odoo_existing_external_ids(models, db, uid, pwd, IMPORT_BATCH)
    print(f"  {len(existing)} befintliga records med import_batch={IMPORT_BATCH}")

    # Bygg par och filtrera bort dubbletter
    to_create = []
    for rec in records:
        pair = map_to_odoo_pair(rec, database_id, country_map)
        if pair["external_id"] not in existing:
            to_create.append(pair)

    print(f"  {len(records) - len(to_create)} dubbletter borttagna")
    print(f"  {len(to_create)} nya encounter+report-par att skapa")

    if not to_create:
        print("Inget nytt att importera.")
        return

    # Importera i batchar
    created = odoo_create_encounter_report_pairs(
        models, db, uid, pwd, to_create, database_id, country_map
    )
    print(f"\nKlart! {created} encounter+report-par skapade (import_batch={IMPORT_BATCH})")
    print("Källa: https://files.afu.se/Downloads/./Databases/Larry%20Hatch/derivations/Larry%20Hatch%20-%20full%20text.pdf")


if __name__ == "__main__":
    main()
