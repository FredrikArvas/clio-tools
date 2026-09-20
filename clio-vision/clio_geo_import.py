"""
clio_geo_import.py
Extracts GPS coordinates from images, clusters them, and imports unique
locations into the clio.location Odoo model.

Usage:
    python clio_geo_import.py <image-folder>

Requires: Pillow, reverse_geocoder, python-dotenv
Odoo credentials: loaded from clio-tools/.env (ODOO_URL, ODOO_DB,
                  ODOO_USER, ODOO_PASSWORD for aiab)
"""

import math
import os
import sys
import xmlrpc.client
from pathlib import Path

import time

import requests
from dotenv import load_dotenv
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

SCRIPT_DIR = Path(__file__).parent
ENV_PATH = SCRIPT_DIR.parent / ".env"
load_dotenv(ENV_PATH)

ODOO_URL = os.environ["ODOO_URL"].rstrip("/")
ODOO_DB = "aiab"
ODOO_USER = os.environ["ODOO_USER"]
ODOO_PASSWORD = "AIABOdoo2026"

CLUSTER_RADIUS_M = 100
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {
    "User-Agent": "clio_geo/1.0 (clio@arvas.international)",
    "Accept-Language": "sv,en;q=0.5",
}


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

def _nominatim_display(lat, lon):
    """Return (display_name_geo, city) using Nominatim with Swedish names."""
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "json",
                    "zoom": 18, "addressdetails": 1},
            headers=NOMINATIM_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        addr = r.json().get("address", {})
        road = addr.get("road", "")
        number = addr.get("house_number", "")
        city = (addr.get("city") or addr.get("town") or addr.get("village")
                or addr.get("municipality") or addr.get("county", ""))
        country = addr.get("country", "")
        parts = []
        if road:
            parts.append(f"{road} {number}".strip())
        if city:
            parts.append(city)
        if country:
            parts.append(country)
        display = ", ".join(parts) if parts else f"{lat:.5f}, {lon:.5f}"
        time.sleep(1.1)
        return display, city
    except Exception:
        time.sleep(1.1)
        return f"{lat:.5f}, {lon:.5f}", ""



def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _dms_to_decimal(dms, ref):
    d, m, s = (float(x) for x in dms)
    result = d + m / 60 + s / 3600
    if ref in ("S", "W"):
        result = -result
    return round(result, 7)


def extract_gps(filepath):
    """Return (lat, lon) or None."""
    try:
        img = Image.open(filepath)
        exif = img._getexif()
        if not exif:
            return None
        gps_raw = None
        for tag_id, val in exif.items():
            if TAGS.get(tag_id) == "GPSInfo":
                gps_raw = {GPSTAGS.get(t, t): val[t] for t in val}
                break
        if not gps_raw or "GPSLatitude" not in gps_raw:
            return None
        lat = _dms_to_decimal(gps_raw["GPSLatitude"], gps_raw.get("GPSLatitudeRef", "N"))
        lon = _dms_to_decimal(gps_raw["GPSLongitude"], gps_raw.get("GPSLongitudeRef", "E"))
        return lat, lon
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Odoo connection
# ---------------------------------------------------------------------------

def odoo_connect():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        raise RuntimeError("Odoo-autentisering misslyckades")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models


def fetch_existing_locations(uid, models):
    """Return list of {lat, lon, radius_m} for all active clio.location."""
    records = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "clio.location", "search_read",
        [[["active", "=", True]]],
        {"fields": ["lat", "lon", "radius_m"]},
    )
    return records


def create_location(uid, models, lat, lon, display_name_geo, city=""):
    vals = {
        "name": display_name_geo,
        "display_name_geo": display_name_geo,
        "lat": lat,
        "lon": lon,
        "radius_m": CLUSTER_RADIUS_M,
        "category": "other",
        "city": city,
    }
    rec_id = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "clio.location", "create",
        [vals],
    )
    return rec_id


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def find_nearest_cluster(lat, lon, clusters):
    """Return the nearest cluster dict if within its radius, else None."""
    best = None
    best_dist = float("inf")
    for c in clusters:
        d = haversine_m(lat, lon, c["lat"], c["lon"])
        if d <= c["radius_m"] and d < best_dist:
            best = c
            best_dist = d
    return best


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(image_folder):
    folder = Path(image_folder)
    if not folder.exists():
        print(f"Mappen finns inte: {folder}")
        sys.exit(1)

    print(f"Skannar {folder} …")
    uid, models = odoo_connect()
    print("Ansluten till Odoo aiab")

    clusters = fetch_existing_locations(uid, models)
    print(f"  {len(clusters)} befintliga platser i Odoo")

    all_coords = []
    skipped = 0
    for fp in folder.rglob("*"):
        if fp.suffix.lower() not in IMAGE_EXTS:
            continue
        coords = extract_gps(fp)
        if coords:
            all_coords.append(coords)
        else:
            skipped += 1

    print(f"  {len(all_coords)} bilder med GPS, {skipped} utan")

    new_clusters = []
    duplicates = 0
    for lat, lon in all_coords:
        if find_nearest_cluster(lat, lon, clusters) or find_nearest_cluster(lat, lon, new_clusters):
            duplicates += 1
            continue
        display, city = _nominatim_display(lat, lon)
        new_clusters.append({"lat": lat, "lon": lon, "radius_m": CLUSTER_RADIUS_M,
                              "display": display, "city": city})

    print(f"  {duplicates} koordinater inom befintliga platser (hoppas över)")
    print(f"  {len(new_clusters)} nya kluster att importera")

    imported = 0
    for c in new_clusters:
        rec_id = create_location(uid, models, c["lat"], c["lon"], c["display"], c["city"])
        print(f"  + [{rec_id}] {c['display']}  ({c['lat']:.5f}, {c['lon']:.5f})")
        clusters.append({"lat": c["lat"], "lon": c["lon"], "radius_m": CLUSTER_RADIUS_M})
        imported += 1

    print(f"\nKlart — {imported} platser importerade till Odoo.")


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\fredr\Dropbox\bilder\Camera uploads 2026"
    run(folder)
