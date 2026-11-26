"""
uap_import_cuap.py — Importerar Canadian UFO Survey (UFOlogy Research of Canada)
                     till uap.report

Källa: https://canadianuforeport.ca/survey-data
Data:  1989–2025, ~26 000 rapporter, Modified Hynek Classification System, 16 fält per rad
Format: PDF (ursprungligen Excel) — en rad per fall

Kolumner i källdata:
  YEAR MONTH DAY TIME LOCATION PROV TYPE DUR COLOUR #WIT SHAPE STR RELIA SOURCE eVAL COMMENTS

Kör:
  python3 uap_import_cuap.py [--dry-run] [--pdf /sökväg/til/fil.pdf] [--limit N]
  python3 uap_import_cuap.py --download-only   (laddar ned PDFs, kör ej import)

PDFs sparas i: ~/19.0/clio-tools/clio-uap/cuap_pdfs/
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Ladda .env — clio-uap/.env har ODOO_URL mot uap.arvas.international
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent / ".env", override=True)

import xmlrpc.client

URL  = os.getenv("ODOO_URL", "http://localhost:8079")
DB   = os.getenv("ODOO_DB",  "uap")
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

PDF_DIR = Path(__file__).parent / "cuap_pdfs"
PDF_DIR.mkdir(exist_ok=True)

UA = "clio-uap/1.0 (Canadian UFO Survey importer)"

# PDF-URLs — CDN på wsimg.com
PDF_URLS = {
    "1989-2025": "https://img1.wsimg.com/blobby/go/c23c8b29-268f-4742-a45e-2dba156b0e52/downloads/908b1b66-e225-4d7c-afe0-f0f102620919/1989%20to%202025%20excel%20data.pdf?ver=1778298790504",
    "2025": "https://img1.wsimg.com/blobby/go/c23c8b29-268f-4742-a45e-2dba156b0e52/downloads/09c7cd11-ac37-4049-b675-539a33144d5b/2025%20Canadian%20UFO%20Survey%20FINAL%20FINAL%202%20%281%29.pdf?ver=1778298790504",
    "2024": "https://img1.wsimg.com/blobby/go/c23c8b29-268f-4742-a45e-2dba156b0e52/downloads/2f86784a-80d2-4eab-ab35-8ad6c8279ea7/2024%20Data.pdf?ver=1778298790504",
    "2023": "https://img1.wsimg.com/blobby/go/c23c8b29-268f-4742-a45e-2dba156b0e52/downloads/1f8ab4dc-bcdb-491b-bf9d-f7fb94247302/2023%20Data.pdf?ver=1778298790504",
    "2022": "https://img1.wsimg.com/blobby/go/c23c8b29-268f-4742-a45e-2dba156b0e52/downloads/1b07cfce-a7d0-4d98-a9e4-3f69d345b002/2022%20Data.pdf?ver=1778298790504",
    "2021": "https://img1.wsimg.com/blobby/go/c23c8b29-268f-4742-a45e-2dba156b0e52/downloads/485a8b64-12e2-4d16-a59f-23e37450eadb/2021%20Data.pdf?ver=1778298790505",
}

# Kanadensiska provinskoder (längre koder måste komma först i alternativet)
PROVS = sorted([
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE",
    "QC", "PQ", "SK", "YT", "YK"
], key=len, reverse=True)
PROV_PAT = "|".join(PROVS)

# Hynek-klassificering → visningsnamn
HYNEK_NAMES = {
    "nl": "Nocturnal Light",
    "nd": "Nocturnal Disc",
    "dd": "Daylight Disc",
    "ph": "Photograph",
    "ce1": "Close Encounter 1st Kind", "c1": "Close Encounter 1st Kind",
    "ce2": "Close Encounter 2nd Kind", "c2": "Close Encounter 2nd Kind",
    "ce3": "Close Encounter 3rd Kind", "c3": "Close Encounter 3rd Kind",
    "an":  "Anomaly",
    "ra":  "Radar",
    "so":  "Starlike Object",
    "un":  "Unknown",
    "sv":  "Structured Vehicle",
    "ma":  "Multiple Anomalies",
}

# Huvudregex — TIME direkt ihopklistrat med LOCATION (PDF-artefakt)
# Grupper: year, month, day, time, location, province, type, rest
ROW_RE = re.compile(
    r"^(\d{4})\s+"           # 1: year
    r"(\d{1,2})\s+"          # 2: month
    r"(\d{1,2})\s+"          # 3: day
    r"(\d{0,4})\s*"          # 4: time (0-4 siffror, ibland med avslutande space)
    r"(.+?)\s+"              # 5: location (non-greedy)
    r"(" + PROV_PAT + r")\s+"  # 6: province
    r"([a-zA-Z0-9]+)"        # 7: Hynek type
    r"(.*)$"                 # 8: rest (dur, colour, wit, shape, str, relia, source, eval, comments)
)

# Rest-regex — parsar resten efter TYPE
# Grupper: dur+colour, witnesses+shape, strangeness, reliability, rest (source eval comments)
REST_RE = re.compile(
    r"^\s+"
    r"(\S+)\s*"              # 1: DUR (kan inkludera COLOUR utan mellanslag)
    r"(\d+)"                 # 2: #WIT (kan inkludera SHAPE utan mellanslag)
    r"(\S*)\s+"              # 3: SHAPE-del (direkt efter #WIT, kan vara tom)
    r"(\d)\s+"               # 4: STR (strangeness 1-9)
    r"(\d+)"                 # 5: RELIA (reliability 1-9, ibland 2 siffror)
    r"(.+)$"                 # 6: SOURCE eVAL COMMENTS
)


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def split_dur_colour(dur_raw: str) -> tuple[str, str]:
    """Delar upp '15black' → ('15', 'black'), '120' → ('120', '')."""
    m = re.match(r"^(\d+)([a-zA-Z].*)$", dur_raw)
    if m:
        return m.group(1), m.group(2)
    return dur_raw, ""


def split_wit_shape(wit_raw: str, shape_extra: str) -> tuple[str, str]:
    """Delar upp '3ps' → ('3', 'ps'), '1' → ('1', '')."""
    m = re.match(r"^(\d+)([a-zA-Z].*)$", wit_raw)
    if m:
        return m.group(1), m.group(2) + shape_extra
    return wit_raw, shape_extra.strip()


def parse_time(time_str: str) -> str:
    """'2130' → '21:30', '6' → '06:00', '' → '12:00'."""
    t = time_str.strip().zfill(4) if time_str.strip() else "1200"
    if len(t) >= 4:
        h, m = int(t[-4:-2] or 0), int(t[-2:] or 0)
        h = min(h, 23)
        m = min(m, 59)
        return f"{h:02d}:{m:02d}"
    return "12:00"


def make_report_date(year: str, month: str, day: str, time_str: str) -> str | None:
    hm = parse_time(time_str)
    hh, mm = hm.split(":")
    try:
        d = int(day)
        mo = int(month)
        yr = int(year)
        d = min(d, 28) if mo == 2 else min(d, 30) if mo in (4, 6, 9, 11) else min(d, 31)
        return f"{yr:04d}-{mo:02d}-{d:02d} {hh}:{mm}:00"
    except (ValueError, TypeError):
        return None


def make_external_id(year: str, month: str, day: str, time_str: str,
                     location: str, hynek_type: str) -> str:
    key = f"{year}|{month}|{day}|{time_str}|{location.lower().strip()}|{hynek_type}"
    return "CUAP-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def make_title(hynek_type: str, location: str, province: str, year: str) -> str:
    type_name = HYNEK_NAMES.get(hynek_type.lower(), hynek_type.upper())
    city = location.strip()
    return f"{type_name} — {city}, {province} ({year})"


def make_description(raw_line: str, parsed: dict | None) -> str:
    """Bygger strukturerad beskrivning av observationen."""
    parts = [f"[CUAP] {raw_line}"]
    if parsed:
        parts.append("")
        parts.append("Fält:")
        for k, v in parsed.items():
            if v:
                parts.append(f"  {k}: {v}")
    return "\n".join(parts)


def parse_row(line: str) -> dict | None:
    """Parsar en rad ur CUAP-data. Returnerar dict eller None vid fel."""
    m = ROW_RE.match(line)
    if not m:
        return None

    year, month, day, time_raw, location, province, hynek_raw, rest = m.groups()
    location = location.strip()
    hynek_type = hynek_raw.lower()

    result = {
        "year": year, "month": month, "day": day,
        "time": time_raw.strip(), "location": location,
        "province": province, "hynek_type": hynek_type,
        "dur": "", "colour": "", "witnesses": "", "shape": "",
        "strangeness": "", "reliability": "", "source": "", "eval": "",
        "comments": "", "rest_raw": rest.strip(),
    }

    rm = REST_RE.match(rest)
    if rm:
        dur_raw, wit_raw, shape_extra, strangeness, reliability, tail = rm.groups()
        dur, colour = split_dur_colour(dur_raw)
        witnesses, shape = split_wit_shape(wit_raw, shape_extra)
        result["dur"] = dur
        result["colour"] = colour
        result["witnesses"] = witnesses
        result["shape"] = shape.strip()
        result["strangeness"] = strangeness
        result["reliability"] = reliability

        # Tail: SOURCE eVAL COMMENTS
        tail = tail.strip()
        # Källa är typiskt ett ord utan mellanslag
        tail_parts = tail.split(None, 2)
        if len(tail_parts) >= 1:
            result["source"] = tail_parts[0]
        if len(tail_parts) >= 2:
            result["eval"] = tail_parts[1]
        if len(tail_parts) >= 3:
            result["comments"] = tail_parts[2]

    return result


# ---------------------------------------------------------------------------
# PDF-hantering
# ---------------------------------------------------------------------------

def download_pdf(key: str, url: str) -> Path | None:
    dest = PDF_DIR / f"cuap_{key.replace('-', '_')}.pdf"
    if dest.exists():
        size_mb = dest.stat().st_size / 1_048_576
        print(f"  Använder cachad PDF: {dest.name} ({size_mb:.1f} MB)")
        return dest
    print(f"  Laddar ned {key}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
        size_mb = dest.stat().st_size / 1_048_576
        print(f"  Klar: {dest.name} ({size_mb:.1f} MB)")
        return dest
    except Exception as e:
        print(f"  FEL vid nedladdning {key}: {e}")
        return None


def extract_data_lines(pdf_path: Path) -> list[str]:
    """Extraherar alla datarader (börjar med 4-siffrigt år) ur PDF.
    Processar sida-för-sida för att hålla minnesfotavtrycket lågt.
    Cachar resultatet i en .txt-fil bredvid PDF:en."""
    import pdfplumber
    cache_path = pdf_path.with_suffix(".txt")
    if cache_path.exists():
        print(f"  Använder cachad textfil: {cache_path.name}")
        return [l.rstrip("\n") for l in cache_path.open(encoding="utf-8") if l.strip()]

    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            t = page.extract_text()
            if t:
                for line in t.splitlines():
                    if re.match(r"^\d{4}\s+\d", line):
                        lines.append(line)
            if i % 50 == 0:
                print(f"  Extraherar sida {i}/{total}...", flush=True)
    cache_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Sparat {len(lines)} rader till {cache_path.name}")
    return lines


# ---------------------------------------------------------------------------
# Odoo-anslutning
# ---------------------------------------------------------------------------

def connect_odoo():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = common.authenticate(DB, USER, PWD, {})
    if not uid:
        sys.exit("Odoo-autentisering misslyckades")
    M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

    def kw(model, method, args, kwargs=None):
        return M.execute_kw(DB, uid, PWD, model, method, args, kwargs or {})

    return kw


def get_or_create_db(kw, dry_run: bool) -> int:
    name = "CUAP — Canadian UFO Survey (UFOlogy Research of Canada)"
    res = kw("uap.database", "search_read", [[["name", "=", name]]], {"fields": ["id"]})
    if res:
        db_id = res[0]["id"]
        print(f"  uap.database: {name!r} (ID {db_id})")
        return db_id
    if dry_run:
        print(f"  [DRY] Skulle skapa uap.database: {name!r}")
        return 0
    db_id = kw("uap.database", "create", [{
        "name":        name,
        "db_type":     "reporting",
        "db_url":      "https://canadianuforeport.ca",
        "description": (
            "Kanadensisk UFO-observationsdatabas grundad av UFOlogy Research of Canada. "
            "Samlar in rapporter sedan 1989 från frivilligforskare över hela landet. "
            "Använder Modified Hynek Classification System med 16 datafält per rapport."
        ),
        "language": "en",
    }])
    print(f"  Skapade uap.database: {name!r} (ID {db_id})")
    return db_id


def get_canada_id(kw) -> int:
    res = kw("res.country", "search_read", [[["code", "=", "CA"]]], {"fields": ["id"]})
    if not res:
        sys.exit("Canada (CA) saknas i res.country!")
    return res[0]["id"]


def get_existing_ids(kw) -> set[str]:
    res = kw("uap.report", "search_read",
             [[["external_id", "=like", "CUAP-%"]]],
             {"fields": ["external_id"], "limit": 100_000})
    return {r["external_id"] for r in res}


# ---------------------------------------------------------------------------
# Import-pipeline
# ---------------------------------------------------------------------------

def run_from_lines(data_lines: list[str], dry_run: bool, limit: int | None):
    """Importerar från förbehandlad lista av datarader."""
    print(f"\n{'─' * 60}")
    print("  Canadian UFO Survey (CUAP) importer")
    print(f"{'─' * 60}")
    if dry_run:
        print("  *** DRY RUN ***")
    print(f"  Rader totalt: {len(data_lines)}")
    if limit:
        data_lines = data_lines[:limit]
        print(f"  Begränsat till: {limit}")

    kw = connect_odoo()
    db_id = get_or_create_db(kw, dry_run)
    ca_id = get_canada_id(kw)
    existing = get_existing_ids(kw)
    print(f"  Redan importerade CUAP-poster: {len(existing)}")

    _import_lines(data_lines, kw, db_id, ca_id, existing, dry_run)


def _import_lines(data_lines: list[str], kw, db_id: int, ca_id: int,
                  existing: set[str], dry_run: bool):
    """Parsar och importerar rader till uap.report."""
    created = skipped = parse_errors = odoo_errors = 0
    eval_labels = {
        "p": "Photo/video evidence", "i": "Insufficient evidence",
        "u": "Uncertain", "v": "Video", "r": "Radar"
    }

    for line in data_lines:
        parsed = parse_row(line)

        if parsed is None:
            yr_m = re.match(r"^(\d{4})\s+(\d{1,2})\s+(\d{1,2})", line)
            year = yr_m.group(1) if yr_m else "0000"
            ext_id = "CUAP-" + hashlib.md5(line.encode("utf-8")).hexdigest()[:16]
            if ext_id in existing:
                skipped += 1
                continue
            vals = {
                "external_id":     ext_id,
                "raw_title":       f"CUAP rapport ({year}) — (ej parsad)",
                "raw_description": f"[CUAP] {line}",
                "country_id":      ca_id,
                "database_id":     db_id or False,
                "reporter_type":   "unknown",
                "status":          "unlinked",
            }
            parse_errors += 1
        else:
            ext_id = make_external_id(
                parsed["year"], parsed["month"], parsed["day"],
                parsed["time"], parsed["location"], parsed["hynek_type"]
            )
            if ext_id in existing:
                skipped += 1
                continue

            report_date = make_report_date(
                parsed["year"], parsed["month"], parsed["day"], parsed["time"]
            )
            title = make_title(
                parsed["hynek_type"], parsed["location"],
                parsed["province"], parsed["year"]
            )

            desc_parts = [line, ""]
            if parsed["source"]:
                desc_parts.append(f"Source: {parsed['source']}")
            if parsed["eval"]:
                desc_parts.append(f"Evidence: {eval_labels.get(parsed['eval'], parsed['eval'])}")
            if parsed["colour"]:
                desc_parts.append(f"Colour: {parsed['colour']}")
            if parsed["dur"]:
                desc_parts.append(f"Duration: {parsed['dur']} seconds")
            if parsed["witnesses"]:
                desc_parts.append(f"Witnesses: {parsed['witnesses']}")
            if parsed["strangeness"]:
                desc_parts.append(f"Strangeness (1-9): {parsed['strangeness']}")
            if parsed["reliability"]:
                desc_parts.append(f"Reliability (1-9): {parsed['reliability']}")
            if parsed["comments"]:
                desc_parts.append(f"\n{parsed['comments']}")

            vals = {
                "external_id":     ext_id,
                "raw_title":       title,
                "raw_description": "\n".join(desc_parts),
                "report_date":     report_date or False,
                "country_id":      ca_id,
                "location_text":   f"{parsed['location']}, {parsed['province']}, Canada",
                "shape":           parsed["shape"] or False,
                "duration_text":   parsed["dur"] or False,
                "database_id":     db_id or False,
                "reporter_type":   "unknown",
                "status":          "unlinked",
            }

        if dry_run:
            if created < 8:
                print(f"  [DRY] {ext_id} | {vals.get('report_date', '?')} | {vals['raw_title'][:60]}")
            created += 1
            existing.add(ext_id)
            continue

        try:
            kw("uap.report", "create", [vals])
            created += 1
            existing.add(ext_id)
            if created % 500 == 0:
                print(f"  ... {created} skapade ({skipped} hoppade, {parse_errors} parsfel)", flush=True)
        except Exception as e:
            odoo_errors += 1
            if odoo_errors <= 5:
                print(f"  FEL {ext_id}: {str(e)[:120]}")
            if odoo_errors > 50:
                print("  För många Odoo-fel — avbryter")
                break

    print(f"\n  Skapade    : {created}")
    print(f"  Hoppade    : {skipped} (redan importerade)")
    print(f"  Parsfel    : {parse_errors} (lagrade som råtext)")
    print(f"  Odoo-fel   : {odoo_errors}")


def run(pdf_path: Path, dry_run: bool, limit: int | None):
    print(f"\n{'─' * 60}")
    print("  Canadian UFO Survey (CUAP) importer")
    print(f"{'─' * 60}")
    if dry_run:
        print("  *** DRY RUN ***")
    print(f"  PDF: {pdf_path}")

    data_lines = extract_data_lines(pdf_path)
    print(f"  Rader totalt: {len(data_lines)}")
    if limit:
        data_lines = data_lines[:limit]
        print(f"  Begränsat till: {limit}")

    kw = connect_odoo()
    db_id = get_or_create_db(kw, dry_run)
    ca_id = get_canada_id(kw)
    existing = get_existing_ids(kw)
    print(f"  Redan importerade CUAP-poster: {len(existing)}")
    _import_lines(data_lines, kw, db_id, ca_id, existing, dry_run)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Importerar Canadian UFO Survey → uap.report")
    ap.add_argument("--dry-run", action="store_true", help="Kör utan att skriva till Odoo")
    ap.add_argument("--pdf", type=str, default=None,
                    help="Sökväg till lokal PDF (annars laddas 1989-2025 ned automatiskt)")
    ap.add_argument("--txt", type=str, default=None,
                    help="Sökväg till förextraherad textfil (skippar PDF-parsning)")
    ap.add_argument("--year", type=str, default="1989-2025",
                    choices=list(PDF_URLS.keys()),
                    help="Välj vilken PDF som hämtas (standard: 1989-2025)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Begränsa antal rader att importera (för testning)")
    ap.add_argument("--download-only", action="store_true",
                    help="Ladda ned PDFs och avsluta")
    args = ap.parse_args()

    if args.download_only:
        for key, url in PDF_URLS.items():
            download_pdf(key, url)
        sys.exit(0)

    if args.txt:
        txt_path = Path(args.txt)
        if not txt_path.exists():
            sys.exit(f"Textfil saknas: {txt_path}")
        # Injicera textrader direkt utan PDF-parsning
        data_lines = [l.rstrip("\n") for l in txt_path.open(encoding="utf-8") if l.strip()]
        run_from_lines(data_lines, args.dry_run, args.limit)
    else:
        if args.pdf:
            pdf_path = Path(args.pdf)
            if not pdf_path.exists():
                sys.exit(f"PDF saknas: {pdf_path}")
        else:
            url = PDF_URLS[args.year]
            pdf_path = download_pdf(args.year, url)
            if not pdf_path:
                sys.exit("Kunde inte ladda ned PDF")
        run(pdf_path, args.dry_run, args.limit)
