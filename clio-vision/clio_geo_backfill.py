"""
clio_geo_backfill.py
Fetches all clio.location records and enriches them via Nominatim
reverse-geocoding (OpenStreetMap). Updates street, street_number, zip,
city, country_id, and display_name_geo in Odoo.

Rate limit: 1 request/second per OSM policy.

Usage:
    python clio_geo_backfill.py [--dry-run]
"""

import os
import sys
import time
import xmlrpc.client
from pathlib import Path

import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR.parent / ".env")

ODOO_URL = os.environ["ODOO_URL"].rstrip("/")
ODOO_DB = "aiab"
ODOO_USER = os.environ["ODOO_USER"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {
    "User-Agent": "clio_geo/1.0 (clio@arvas.international)",
    "Accept-Language": "sv,en;q=0.5",
}
RATE_LIMIT_S = 2.0
RETRY_WAIT_S = 60


def nominatim_reverse(lat, lon):
    """Return address dict from Nominatim or {}. Retries once on 429."""
    for attempt in range(2):
        try:
            r = requests.get(
                NOMINATIM_URL,
                params={"lat": lat, "lon": lon, "format": "json", "zoom": 18,
                        "addressdetails": 1},
                headers=HEADERS,
                timeout=10,
            )
            if r.status_code == 429:
                print(f"    Rate limit 429 — väntar {RETRY_WAIT_S}s...")
                time.sleep(RETRY_WAIT_S)
                continue
            r.raise_for_status()
            data = r.json()
            return data.get("address", {})
        except Exception as e:
            print(f"    Nominatim-fel {lat},{lon}: {e}")
            return {}
    return {}


def build_display_name(addr):
    """Build a human-readable location string from Nominatim address."""
    road = addr.get("road", "")
    number = addr.get("house_number", "")
    city = (addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("municipality")
            or addr.get("county", ""))
    country = addr.get("country", "")
    parts = []
    if road:
        parts.append(f"{road} {number}".strip())
    if city:
        parts.append(city)
    if country:
        parts.append(country)
    return ", ".join(parts) if parts else ""


def odoo_connect():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        raise RuntimeError("Odoo-autentisering misslyckades")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models


def lookup_country_id(models, uid, country_code, cache):
    """Return Odoo res.country id for a 2-letter ISO code, using cache."""
    if not country_code:
        return False
    code = country_code.upper()
    if code in cache:
        return cache[code]
    ids = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "res.country", "search",
        [[["code", "=", code]]],
    )
    result = ids[0] if ids else False
    cache[code] = result
    return result


def run(dry_run=False):
    uid, models = odoo_connect()
    records = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "clio.location", "search_read",
        [[["active", "=", True]]],
        {"fields": ["id", "name", "lat", "lon", "street", "display_name_geo"]},
    )
    print(f"{len(records)} poster hämtade från Odoo")
    if dry_run:
        print("(dry-run — inga uppdateringar skrivs)")

    country_cache = {}
    updated = 0
    skipped = 0
    for rec in records:
        if not rec["lat"] or not rec["lon"]:
            skipped += 1
            continue

        addr = nominatim_reverse(rec["lat"], rec["lon"])
        time.sleep(RATE_LIMIT_S)

        if not addr:
            skipped += 1
            continue

        road = addr.get("road", "")
        number = addr.get("house_number", "")
        zip_code = addr.get("postcode", "")
        city = (addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("municipality")
                or addr.get("county", ""))
        country_code = addr.get("country_code", "")
        country_id = lookup_country_id(models, uid, country_code, country_cache)
        display = build_display_name(addr)

        print(f"  [{rec['id']}] {rec['display_name_geo']} → {display or '(tom)'} [{country_code.upper() or '?'}]")

        if not dry_run and display:
            vals = {
                "street": road,
                "street_number": number,
                "zip": zip_code,
                "city": city,
                "display_name_geo": display,
                "name": display,
            }
            if country_id:
                vals["country_id"] = country_id
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                "clio.location", "write",
                [[rec["id"]], vals],
            )
            updated += 1

    print(f"\nKlart — {updated} poster uppdaterade, {skipped} hoppades över.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
