"""
sync_fastigheter.py - Importerar/uppdaterar GSF-fastigheter fran Excel till Odoo.

Skapar/uppdaterar property.property (upsert-nyckel: code = Fastighetsbeteckning).
Kors laempligen FOERE sync_agare.py saa att fastigheter finns naar stakeholders skapas.

Korning:
    python sync_fastigheter.py <xlsx-fil>               # live
    python sync_fastigheter.py <xlsx-fil> --dry-run     # ingen skrivning

Flaggor:
    --url   Odoo-URL  (default: fraagas interaktivt)
    --db    Databas   (default: fran .env)

Kraver .env med ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

ODOO_URLS = {
    "hem": "http://192.168.1.189:8069",
    "jobbet": "http://100.107.127.104:8069",
}


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _clean(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() == "none" else s


def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def _get_country_se(env) -> int:
    hits = env["res.country"].search_read([("code", "=", "SE")], ["id"])
    return _to_int(hits[0]["id"]) if hits else None


def _build_property_vals(row: dict, country_id: int) -> dict:
    beteckning = _clean(row.get("Fastighetsbeteckning", ""))
    bebyggd = _clean(row.get("Bebyggd", "")).lower()
    areal_raw = row.get("Areal (ha)")

    vals: dict = {
        "name": beteckning,
        "code": beteckning,
        "street": _clean(row.get("Gatuadress", "")),
        "zip": _clean(row.get("Postnr", "")),
        "city": _clean(row.get("Postort", "")),
        "state": "ok",
        "property_status": "has_building" if bebyggd == "ja" else "no_building",
    }
    if areal_raw is not None:
        try:
            vals["size"] = str(round(float(str(areal_raw).replace(",", ".")), 4))
        except ValueError:
            pass
    if country_id:
        vals["country_id"] = country_id
    return vals


# ---------------------------------------------------------------------------
# Excel-läsning
# ---------------------------------------------------------------------------

def _read_xlsx(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    return [dict(zip(headers, row)) for row in rows[1:]]


# ---------------------------------------------------------------------------
# Huvudrutin
# ---------------------------------------------------------------------------

def _ask_location() -> str:
    print("Var sitter du? [hem / jobbet]: ", end="", flush=True)
    val = input().strip().lower()
    return ODOO_URLS.get(val, ODOO_URLS["hem"])


def run(xlsx_path: str, dry_run: bool = False, url: str = None, db: str = None) -> None:
    print(f"Laser: {xlsx_path}")
    rows = _read_xlsx(xlsx_path)
    print(f"  {len(rows)} rader hittade")

    if not dry_run:
        if not url:
            url = _ask_location()
        env = connect(url=url, db=db)
        Property = env["property.property"]
        country_id = _get_country_se(env)
        print(f"  Land SE id={country_id}")
    else:
        Property = None
        country_id = 0
        print("  [DRY-RUN] ingen anslutning till Odoo")

    created = updated = skipped = errors = 0

    for row in rows:
        beteckning = _clean(row.get("Fastighetsbeteckning", ""))
        if not beteckning:
            skipped += 1
            continue

        vals = _build_property_vals(row, country_id)

        if dry_run:
            print(f"  [DRY] {beteckning} | {vals.get('street','')} {vals.get('zip','')} {vals.get('city','')}")
            created += 1
            continue

        try:
            hits = Property.search_read([("code", "=", beteckning)], ["id"])
            if hits:
                Property.write([hits[0]["id"]], vals)
                updated += 1
            else:
                Property.create(vals)
                created += 1
        except Exception as e:
            print(f"  FEL {beteckning}: {e}")
            errors += 1

    print(f"\nKlart: {created} skapade | {updated} uppdaterade | {skipped} hoppade over | {errors} fel")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synka GSF-fastigheter till Odoo")
    parser.add_argument("xlsx", help="Sokvaeg till FastigheterDetaljerad.xlsx")
    parser.add_argument("--dry-run", action="store_true", help="Skriv inget till Odoo")
    parser.add_argument("--url", help="Odoo-URL, t.ex. http://localhost:8079")
    parser.add_argument("--db", help="Databasnamn, t.ex. gsf_t3")
    args = parser.parse_args(argv)
    run(args.xlsx, dry_run=args.dry_run, url=args.url, db=args.db)


if __name__ == "__main__":
    main()
