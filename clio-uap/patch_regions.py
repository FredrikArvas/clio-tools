"""
patch_regions.py — Sätter region på encounters som saknar det

1. Encounters med country_id → mappa ISO-kod till region
2. Encounters utan country_id men med title/location som antyder USA → north_america + US
3. Encounters utan country_id alls → sätt north_america (NUFORC-default)

Kör: python3 patch_regions.py [--dry-run] [--no-default]
"""
from __future__ import annotations
import argparse, os, sys, xmlrpc.client
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
# ISO-kod → region
# ---------------------------------------------------------------------------

COUNTRY_REGION: dict[str, str] = {
    # Europa
    "AD": "europe", "AL": "europe", "AT": "europe", "BA": "europe",
    "BE": "europe", "BG": "europe", "BY": "europe", "CH": "europe",
    "CY": "europe", "CZ": "europe", "DE": "europe", "DK": "europe",
    "EE": "europe", "ES": "europe", "FI": "europe", "FR": "europe",
    "GB": "europe", "GR": "europe", "HR": "europe", "HU": "europe",
    "IE": "europe", "IS": "europe", "IT": "europe", "LI": "europe",
    "LT": "europe", "LU": "europe", "LV": "europe", "MC": "europe",
    "MD": "europe", "ME": "europe", "MK": "europe", "MT": "europe",
    "NL": "europe", "NO": "europe", "PL": "europe", "PT": "europe",
    "RO": "europe", "RS": "europe", "RU": "europe", "SE": "europe",
    "SI": "europe", "SK": "europe", "SM": "europe", "TR": "europe",
    "UA": "europe", "VA": "europe", "XK": "europe",

    # Nordamerika
    "CA": "north_america", "US": "north_america", "MX": "north_america",
    "GT": "north_america", "BZ": "north_america", "HN": "north_america",
    "SV": "north_america", "NI": "north_america", "CR": "north_america",
    "PA": "north_america", "CU": "north_america", "JM": "north_america",
    "HT": "north_america", "DO": "north_america", "PR": "north_america",
    "TT": "north_america", "BB": "north_america",

    # Sydamerika
    "AR": "south_america", "BO": "south_america", "BR": "south_america",
    "CL": "south_america", "CO": "south_america", "EC": "south_america",
    "GY": "south_america", "PY": "south_america", "PE": "south_america",
    "SR": "south_america", "UY": "south_america", "VE": "south_america",
    "GF": "south_america", "FK": "south_america",

    # Asien
    "AF": "asia", "AM": "asia", "AZ": "asia", "BD": "asia",
    "BT": "asia", "BN": "asia", "CN": "asia", "GE": "asia",
    "HK": "asia", "ID": "asia", "IN": "asia", "JP": "asia",
    "KG": "asia", "KH": "asia", "KP": "asia", "KR": "asia",
    "KZ": "asia", "LA": "asia", "LK": "asia", "MM": "asia",
    "MN": "asia", "MO": "asia", "MV": "asia", "MY": "asia",
    "NP": "asia", "PH": "asia", "PK": "asia", "SG": "asia",
    "TH": "asia", "TJ": "asia", "TL": "asia", "TM": "asia",
    "TW": "asia", "UZ": "asia", "VN": "asia",

    # Mellanöstern
    "AE": "middle_east", "BH": "middle_east", "CY": "middle_east",
    "EG": "middle_east", "IQ": "middle_east", "IR": "middle_east",
    "IL": "middle_east", "JO": "middle_east", "KW": "middle_east",
    "LB": "middle_east", "LY": "middle_east", "OM": "middle_east",
    "PS": "middle_east", "QA": "middle_east", "SA": "middle_east",
    "SD": "middle_east", "SY": "middle_east", "TN": "middle_east",
    "YE": "middle_east",

    # Afrika
    "AO": "africa", "BF": "africa", "BI": "africa", "BJ": "africa",
    "BW": "africa", "CD": "africa", "CF": "africa", "CG": "africa",
    "CI": "africa", "CM": "africa", "CV": "africa", "DJ": "africa",
    "DZ": "africa", "ER": "africa", "ET": "africa", "GA": "africa",
    "GH": "africa", "GM": "africa", "GN": "africa", "GQ": "africa",
    "GW": "africa", "KE": "africa", "KM": "africa", "LR": "africa",
    "LS": "africa", "MA": "africa", "MG": "africa", "ML": "africa",
    "MR": "africa", "MU": "africa", "MW": "africa", "MZ": "africa",
    "NA": "africa", "NE": "africa", "NG": "africa", "RE": "africa",
    "RW": "africa", "SC": "africa", "SL": "africa", "SN": "africa",
    "SO": "africa", "SS": "africa", "ST": "africa", "SZ": "africa",
    "TD": "africa", "TG": "africa", "TZ": "africa", "UG": "africa",
    "YT": "africa", "ZA": "africa", "ZM": "africa", "ZW": "africa",

    # Oceanien
    "AU": "oceania", "FJ": "oceania", "FM": "oceania", "GU": "oceania",
    "KI": "oceania", "MH": "oceania", "MP": "oceania", "NC": "oceania",
    "NR": "oceania", "NZ": "oceania", "PF": "oceania", "PG": "oceania",
    "PW": "oceania", "SB": "oceania", "TO": "oceania", "TV": "oceania",
    "VU": "oceania", "WF": "oceania", "WS": "oceania",
}


def run(dry_run: bool, set_default: bool):
    print(f"\n{'='*60}")
    print(f"  Region-patch  {'[DRY RUN] ' if dry_run else ''}")
    print(f"{'='*60}")

    # --- Hämta alla länder med ISO-kod ---
    all_countries = kw("res.country", "search_read",
                       [[]],
                       {"fields": ["id", "code"], "limit": 300})
    country_to_region: dict[int, str] = {}
    for c in all_countries:
        region = COUNTRY_REGION.get(c["code"])
        if region:
            country_to_region[c["id"]] = region
    print(f"  Länder mappade: {len(country_to_region)}")

    # --- Encounters utan region ---
    no_region = kw("uap.encounter", "search_read",
                   [[["region", "=", False]]],
                   {"fields": ["id", "country_id", "title_en"], "limit": 50000})
    print(f"  Encounters utan region: {len(no_region)}")

    # Hitta USA:s country_id
    us = kw("res.country", "search_read",
            [[["code", "=", "US"]]],
            {"fields": ["id"], "limit": 1})
    us_id = us[0]["id"] if us else None

    with_country = no_country = updated_country = updated_default = 0

    for enc in no_region:
        enc_id    = enc["id"]
        country   = enc.get("country_id")
        country_id = country[0] if country else None

        if country_id and country_id in country_to_region:
            region = country_to_region[country_id]
            with_country += 1
        elif set_default:
            # Default: north_america (NUFORC-data), sätt även country=US om det saknas
            region = "north_america"
            no_country += 1
        else:
            continue

        if dry_run:
            title = (enc.get("title_en") or "")[:40]
            flag  = " [default→US]" if (not country_id and set_default) else ""
            print(f"  {enc_id:6d} {region:15s}{flag}  {title!r}")
        else:
            vals: dict = {"region": region}
            if not country_id and set_default and us_id:
                vals["country_id"] = us_id
            kw("uap.encounter", "write", [[enc_id], vals])

            if country_id:
                updated_country += 1
            else:
                updated_default += 1

    print(f"\n{'='*60}")
    if dry_run:
        print(f"  Skulle uppdateras (med country): {with_country}")
        print(f"  Skulle uppdateras (default US) : {no_country if set_default else 'ej (--no-default)'}")
    else:
        print(f"  Uppdaterade (från country_id) : {updated_country}")
        print(f"  Uppdaterade (default US)      : {updated_default}")
    print(f"{'='*60}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run",    action="store_true")
    ap.add_argument("--no-default", action="store_true",
                    help="Sätt INTE north_america som default för poster utan land")
    args = ap.parse_args()
    run(args.dry_run, not args.no_default)
