"""
sync_agare.py - Importerar/uppdaterar GSF-agare fran Excel till Odoo res.partner.

Korning:
    python sync_agare.py <xlsx-fil>               # live
    python sync_agare.py <xlsx-fil> --dry-run     # ingen skrivning

Upsert-nyckel: ref = "gsf-{Unikt ID}"
Kraver .env med ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

GSF_TAG = "GSF:Agare"
REF_PREFIX = "gsf-"


def _clean(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() == "none" else s


def _first_line(val) -> str:
    return _clean(val).split("\n")[0].strip()


def _fastigheter_note(row) -> str:
    fastigheter = _clean(row.get("Fastigheter", ""))
    andelar = _clean(row.get("\u00c4garandel", ""))
    if not fastigheter:
        return ""
    lines = fastigheter.split("\n")
    andel_lines = andelar.split("\n") if andelar else []
    parts = []
    for i, f in enumerate(lines):
        andel = andel_lines[i] if i < len(andel_lines) else ""
        parts.append(f"{f} ({andel})" if andel else f)
    return "GSF fastigheter: " + ", ".join(parts)


def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def _get_or_create_tag(env, tag_name: str) -> int:
    Tag = env["res.partner.category"]
    hits = Tag.search_read([("name", "=", tag_name)], ["id"])
    if hits:
        return _to_int(hits[0]["id"])
    return _to_int(Tag.create({"name": tag_name}))


def _get_country_se(env) -> int:
    Country = env["res.country"]
    hits = Country.search_read([("code", "=", "SE")], ["id"])
    return _to_int(hits[0]["id"]) if hits else None


def _build_vals(row: dict, country_id: int, tag_id: int) -> dict:
    ref = f"{REF_PREFIX}{row['Unikt ID']}"
    typ = _clean(row.get("Typ", ""))
    is_company = typ != "Fysisk person"

    street2 = _clean(row.get("c/o", ""))
    note = _fastigheter_note(row)

    vals: dict = {
        "ref": ref,
        "name": _clean(row.get("Namn", "")),
        "is_company": is_company,
        "street": _clean(row.get("Gatuadress", "")),
        "zip": _first_line(row.get("Postnr", "")),
        "city": _clean(row.get("Postort", "")),
        "email": _clean(row.get("E-post", "")),
        "mobile": _clean(row.get("Mobilnr", "")),
        "phone": _clean(row.get("Telefonnr", "")),
        "comment": note,
        "category_id": [(4, tag_id)],
    }
    if street2:
        vals["street2"] = street2
    if country_id:
        vals["country_id"] = country_id
    return vals


def _read_xlsx(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    return [dict(zip(headers, row)) for row in rows[1:]]


ODOO_URLS = {
    "hem": "http://192.168.1.189:8069",
    "jobbet": "http://100.107.127.104:8069",
}


def _ask_location() -> str:
    print("Var sitter du? [hem / jobbet]: ", end="", flush=True)
    val = input().strip().lower()
    return ODOO_URLS.get(val, ODOO_URLS["hem"])


def run(xlsx_path: str, dry_run: bool = False) -> None:
    print(f"Laser: {xlsx_path}")
    rows = _read_xlsx(xlsx_path)
    print(f"  {len(rows)} rader hittade")

    if not dry_run:
        url = _ask_location()
        env = connect(url=url)
        Partner = env["res.partner"]
        tag_id = _get_or_create_tag(env, GSF_TAG)
        country_id = _get_country_se(env)
        print(f"  Tag '{GSF_TAG}' id={tag_id}, land SE id={country_id}")
    else:
        Partner = None
        tag_id = 0
        country_id = 0
        print("  [DRY-RUN] ingen anslutning till Odoo")

    created = updated = skipped = errors = 0

    for row in rows:
        uid = row.get("Unikt ID")
        if not uid:
            skipped += 1
            continue

        ref = f"{REF_PREFIX}{uid}"
        vals = _build_vals(row, country_id, tag_id)

        if dry_run:
            print(f"  [DRY] {ref} | {vals['name']} | {vals.get('email','')}")
            created += 1
            continue

        try:
            hits = Partner.search_read([("ref", "=", ref)], ["id", "name"])
            if hits:
                Partner.write([hits[0]["id"]], vals)
                updated += 1
            else:
                Partner.create(vals)
                created += 1
        except Exception as e:
            print(f"  FEL {ref}: {e}")
            errors += 1

    print(f"\nKlart: {created} skapade | {updated} uppdaterade | {skipped} hoppade over | {errors} fel")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synka GSF-agare till Odoo")
    parser.add_argument("xlsx", help="Sokvaeg till AegareDetaljerad.xlsx")
    parser.add_argument("--dry-run", action="store_true", help="Skriv inget till Odoo")
    args = parser.parse_args(argv)
    run(args.xlsx, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
