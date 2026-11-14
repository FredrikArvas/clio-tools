"""
uap_import_eufo.py — Importerar EuroUFO Index (uapcheck.org) till uap.report

Källa: https://www.uapcheck.org/services/tables/index.php?id=UAP-251922&type=uaps
Data: 2024-fall från ~20 europeiska org. Kolumner: year, month, day, time,
      nation, province, city, type, subtype, org, ref, lat, lng

Kör: python3 uap_import_eufo.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
import urllib.request
import xmlrpc.client
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
# Modulens .env pekar på uap-databasen och ska vinna över rotens ODOO_URL (aiab)
load_dotenv(Path(__file__).parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = os.getenv("ODOO_DB", "uap")
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

EUFO_URL = "https://www.uapcheck.org/services/tables/index.php?id=UAP-251922&type=uaps"
UA = "clio-uap/1.0 (EuroUFO Index importer)"

# Mappning org-kod → läsbart namn
ORG_NAMES: dict[str, str] = {
    "CISU":   "CISU — Centro Italiano Studi Ufologici",
    "SUFOI":  "SUFOI — Skandinavisk UFO Information",
    "GEP":    "GEP — Gesellschaft zur Erforschung von Phänomenen",
    "CENAP":  "CENAP — Centrales Erforschungsnetz außergewöhnlicher Phänomene",
    "NL-UFOM":"NL-UFOM — Dutch UFO Meldpunt",
    "BE-UFOM":"BE-UFOM — Belgian UFO Meldpunt",
    "CUCO":   "CUCO — Club Ufológico Canario",
    "NUFORC": "NUFORC — National UFO Reporting Center",
    "MUFON":  "MUFON Case Management System",
    "GEIPAN": "GEIPAN",
}

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
# Ladda referensdata
# ---------------------------------------------------------------------------

def load_countries() -> dict[str, int]:
    """ISO-2 kod → Odoo country id."""
    rows = kw("res.country", "search_read", [[]], {"fields": ["id", "code"]})
    return {r["code"]: r["id"] for r in rows}


def get_or_create_db(name: str, db_cache: dict[str, int]) -> int:
    if name in db_cache:
        return db_cache[name]
    existing = kw("uap.database", "search_read",
                  [[["name", "=", name]]], {"fields": ["id"]})
    if existing:
        db_cache[name] = existing[0]["id"]
        return existing[0]["id"]
    new_id = kw("uap.database", "create", [{"name": name}])
    db_cache[name] = new_id
    print(f"  [NY DB] {name} → id={new_id}")
    return new_id


# ---------------------------------------------------------------------------
# Parsning
# ---------------------------------------------------------------------------

def parse_date(year: str, month: str, day: str, time_s: str) -> str | None:
    try:
        y = int(year)
    except ValueError:
        return None
    # Månadsnamn → nummer
    month_map = {
        "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
        "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
        "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
        "sep":9,"oct":10,"nov":11,"dec":12,
        "spring":4,"summer":7,"autumn":10,"fall":10,"winter":1,
    }
    m = month_map.get(month.lower().strip(), None)
    if m is None:
        try:
            m = int(month)
        except ValueError:
            m = 1
    try:
        d = int(re.sub(r'\D', '', day) or "1") or 1
    except ValueError:
        d = 1
    # Klocka
    t_match = re.match(r"(\d{1,2}):(\d{2})", (time_s or "").strip())
    if t_match:
        hh, mm = int(t_match.group(1)), int(t_match.group(2))
    else:
        hh, mm = 12, 0
    try:
        dt = datetime(y, m, min(d, 28), hh, mm)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime(y, m, 1, 12, 0).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def parse_row(cells: list[str]) -> dict | None:
    # Header har 13 kolumner (year+month+day+time+nation+province+city+type+subtype+org+ref+lat+lng)
    # men datarader har 12 — year är alltid implicit 2024 och saknas i raderna
    if len(cells) == 13:
        year, month, day, time_s, nation, province, city, typ, subtype, org, ref = cells[:11]
        lat = cells[11]
        lng = cells[12]
    elif len(cells) == 12:
        year = "2024"
        month, day, time_s, nation, province, city, typ, subtype, org, ref = cells[:10]
        lat = cells[10]
        lng = cells[11]
    else:
        return None

    return {
        "year": year, "month": month, "day": day, "time": time_s,
        "nation": nation.strip().upper(),
        "province": province.strip(),
        "city": city.strip(),
        "type": typ.strip(),
        "subtype": subtype.strip(),
        "org": org.strip(),
        "ref": ref.strip(),
        "lat": lat.strip(),
        "lng": lng.strip(),
    }


def extract_rows(html: str) -> list[dict]:
    rows = []
    # Extrahera <tr><td>...</td></tr>-block
    for m in re.finditer(r'<tr><td>(.*?)</tr>', html, re.DOTALL):
        cells_raw = re.findall(r'<td>(.*?)</td>', m.group(1), re.DOTALL)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells_raw]
        parsed = parse_row(cells)
        if parsed:
            rows.append(parsed)
    return rows


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def run(dry_run: bool, limit: int | None):
    print(f"\n{'─'*60}")
    print("  EuroUFO Index importer")
    print(f"{'─'*60}")
    if dry_run:
        print("  *** DRY RUN ***")

    # Hämta HTML
    print(f"  Hämtar {EUFO_URL} ...")
    req = urllib.request.Request(EUFO_URL, headers={"User-Agent": UA, "Referer": "https://www.euroufo.net/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    print(f"  HTML: {len(html):,} bytes")

    rows = extract_rows(html)
    print(f"  Rader parsade: {len(rows)}")
    if limit:
        rows = rows[:limit]
        print(f"  (Begränsat till {limit})")

    countries   = load_countries()
    db_cache    = {r["name"]: r["id"] for r in kw("uap.database", "search_read", [[]], {"fields": ["id", "name"]})}

    # Befintliga external_ids — sök på EUFO-prefix direkt
    existing = {r["external_id"] for r in kw("uap.report", "search_read",
        [[["external_id", "like", "EUFO-"]]], {"fields": ["external_id"]})
        if r.get("external_id")}

    print(f"  Redan importerade: {len(existing)}")

    created = skipped = errors = 0
    t0 = time.time()

    for i, row in enumerate(rows):
        # Bygg external_id
        ext_id = f"EUFO-{row['year']}-{row['nation']}-{row['org']}-{row['ref'] or hashlib.md5(str(row).encode()).hexdigest()[:8]}"

        if ext_id in existing:
            skipped += 1
            continue

        # Datum
        report_date = parse_date(row["year"], row["month"], row["day"], row["time"])

        # Land
        country_id = countries.get(row["nation"], False)

        # Plats
        location_parts = [p for p in [row["city"], row["province"]] if p and p not in ("?", "??", "")]
        location = ", ".join(location_parts) or False

        # Databas
        org_code = row["org"] or "EUFO"
        db_name  = ORG_NAMES.get(org_code, f"EuroUFO — {org_code}")
        db_id    = get_or_create_db(db_name, db_cache) if not dry_run else 0

        # Koordinater
        try:
            geo_lat = float(row["lat"]) if row["lat"] else 0.0
            geo_lng = float(row["lng"]) if row["lng"] else 0.0
        except ValueError:
            geo_lat = geo_lng = 0.0

        vals = {
            "external_id":   ext_id,
            "raw_title":     f"{row['type'] or 'UAP'} sighting — {row['city'] or row['nation']} {row['year']}",
            "report_date":   report_date or False,
            "country_id":    country_id or False,
            "location_text": location or False,
            "geo_lat":       geo_lat,
            "geo_lng":       geo_lng,
            "shape":         row["type"][:10] if row["type"] else False,
            "status":        "unlinked",
            "database_id":   db_id or False,
            "reporter_type": "civilian",
        }
        if row["ref"]:
            vals["raw_description"] = f"Ref: {row['ref']} | Subtype: {row['subtype']}"

        if dry_run:
            if created < 5:
                print(f"  [DRY] {ext_id} | {vals['raw_title'][:50]}")
            created += 1
            existing.add(ext_id)
            continue

        try:
            kw("uap.report", "create", [vals])
            created += 1
            existing.add(ext_id)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  FEL {ext_id}: {str(e)[:120]}")

        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(rows)}] skapade={created} hoppade={skipped} fel={errors} ({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\n  Skapade  : {created}")
    print(f"  Hoppade  : {skipped}")
    print(f"  Fel      : {errors}")
    print(f"  Tid      : {elapsed:.1f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    run(args.dry_run, args.limit)
