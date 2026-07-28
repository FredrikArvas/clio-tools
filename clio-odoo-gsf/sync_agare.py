"""
sync_agare.py - Importerar/uppdaterar GSF-agare fran Excel till Odoo.

Skapar/uppdaterar:
  - res.partner          (agare, upsert-nyckel: ref = "gsf-{Unikt ID}")
  - property.property    (fastighet, upsert-nyckel: code = fastighetsbeteckning)
  - property.stakeholder (agare <-> fastighet med andel i %)

Korning:
    python sync_agare.py <xlsx-fil>           # live
    python sync_agare.py <xlsx-fil> --dry-run # ingen skrivning

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
PARTNER_STATUS = "legal_owner"

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


def _first_line(val) -> str:
    return _clean(val).split("\n")[0].strip()


def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def _parse_andel_pct(andel: str) -> int:
    """Omvandla ägarandel-sträng till heltalsprocent.

    Accepterar: "1/4", "1/2", "25%", "25", "0.25"
    Returnerar: 0-100 (int), 0 vid ogiltigt värde.
    """
    s = andel.strip().rstrip("%")
    if not s:
        return 0
    try:
        if "/" in s:
            num, den = s.split("/", 1)
            return round(float(num) / float(den) * 100)
        val = float(s)
        # Värden <= 1 tolkas som decimalandel (0.25 → 25)
        return round(val * 100) if val <= 1 else round(val)
    except (ValueError, ZeroDivisionError):
        return 0


def _parse_fastigheter(row: dict) -> list[tuple[str, int]]:
    """Returnerar lista av (fastighetsbeteckning, andel_pct) från raden."""
    fastigheter_raw = _clean(row.get("Fastigheter", ""))
    andelar_raw = _clean(row.get("Ägarandel", ""))
    if not fastigheter_raw:
        return []
    fast_lines = [f.strip() for f in fastigheter_raw.split("\n") if f.strip()]
    andel_lines = [a.strip() for a in andelar_raw.split("\n")] if andelar_raw else []
    result = []
    for i, beteckning in enumerate(fast_lines):
        andel_str = andel_lines[i] if i < len(andel_lines) else ""
        result.append((beteckning, _parse_andel_pct(andel_str)))
    return result


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


def _build_partner_vals(row: dict, country_id: int, tag_id: int) -> dict:
    ref = f"{REF_PREFIX}{row['Unikt ID']}"
    typ = _clean(row.get("Typ", ""))
    is_company = typ != "Fysisk person"
    street2 = _clean(row.get("c/o", ""))
    vals: dict = {
        "ref": ref,
        "name": _clean(row.get("Namn", "")),
        "is_company": is_company,
        "street": _clean(row.get("Gatuadress", "")),
        "zip": _first_line(row.get("Postnr", "")),
        "city": _clean(row.get("Postort", "")),
        "email": _clean(row.get("E-post", "")),
        "phone": _clean(row.get("Mobilnr", "")) or _clean(row.get("Telefonnr", "")),
        "category_id": [(4, tag_id)],
    }
    if street2:
        vals["street2"] = street2
    if country_id:
        vals["country_id"] = country_id
    return vals


# ---------------------------------------------------------------------------
# Odoo upsert-hjälpredor
# ---------------------------------------------------------------------------

def _upsert_partner(Partner, row: dict, country_id: int, tag_id: int) -> int:
    ref = f"{REF_PREFIX}{row['Unikt ID']}"
    vals = _build_partner_vals(row, country_id, tag_id)
    hits = Partner.search_read([("ref", "=", ref)], ["id"])
    if hits:
        Partner.write([hits[0]["id"]], vals)
        return _to_int(hits[0]["id"]), "updated"
    pid = Partner.create(vals)
    return _to_int(pid), "created"


def _upsert_property(Property, beteckning: str) -> tuple[int, str]:
    """Hämta eller skapa property.property med given fastighetsbeteckning (code)."""
    hits = Property.search_read([("code", "=", beteckning)], ["id"])
    if hits:
        return _to_int(hits[0]["id"]), "existing"
    pid = Property.create({
        "name": beteckning,
        "code": beteckning,
        "state": "ok",
    })
    return _to_int(pid), "created"


def _upsert_stakeholder(Stakeholder, property_id: int, partner_id: int, pct: int) -> str:
    """Hämta eller skapa property.stakeholder; uppdatera andel vid ändring."""
    hits = Stakeholder.search_read(
        [("property_id", "=", property_id), ("partner_id", "=", partner_id)],
        ["id", "percentage"],
    )
    if hits:
        existing_pct = hits[0].get("percentage") or 0
        if existing_pct != pct:
            Stakeholder.write([hits[0]["id"]], {"percentage": pct})
            return "updated"
        return "unchanged"
    Stakeholder.create({
        "property_id": property_id,
        "partner_id": partner_id,
        "percentage": pct,
        "partner_status": PARTNER_STATUS,
    })
    return "created"


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
        Partner = env["res.partner"]
        Property = env["property.property"]
        Stakeholder = env["property.stakeholder"]
        tag_id = _get_or_create_tag(env, GSF_TAG)
        country_id = _get_country_se(env)
        print(f"  Tag '{GSF_TAG}' id={tag_id}, land SE id={country_id}")
    else:
        print("  [DRY-RUN] ingen anslutning till Odoo")

    p_created = p_updated = p_skipped = p_errors = 0
    prop_created = prop_existing = 0
    sh_created = sh_updated = sh_unchanged = 0

    for row in rows:
        uid = row.get("Unikt ID")
        if not uid:
            p_skipped += 1
            continue

        fastigheter = _parse_fastigheter(row)

        if dry_run:
            ref = f"{REF_PREFIX}{uid}"
            name = _clean(row.get("Namn", ""))
            print(f"  [DRY] {ref} | {name} | fastigheter: {fastigheter}")
            p_created += 1
            continue

        # --- res.partner ---
        try:
            partner_id, action = _upsert_partner(Partner, row, country_id, tag_id)
            if action == "created":
                p_created += 1
            else:
                p_updated += 1
        except Exception as e:
            ref = f"{REF_PREFIX}{uid}"
            print(f"  FEL partner {ref}: {e}")
            p_errors += 1
            continue

        # --- property.property + property.stakeholder ---
        for beteckning, pct in fastigheter:
            try:
                prop_id, prop_action = _upsert_property(Property, beteckning)
                if prop_action == "created":
                    prop_created += 1
                else:
                    prop_existing += 1

                sh_action = _upsert_stakeholder(Stakeholder, prop_id, partner_id, pct)
                if sh_action == "created":
                    sh_created += 1
                elif sh_action == "updated":
                    sh_updated += 1
                else:
                    sh_unchanged += 1
            except Exception as e:
                print(f"  FEL fastighet '{beteckning}' for {REF_PREFIX}{uid}: {e}")
                p_errors += 1

    print(f"""
Partners  : {p_created} skapade | {p_updated} uppdaterade | {p_skipped} hoppade over | {p_errors} fel
Fastigheter: {prop_created} skapade | {prop_existing} befintliga
Stakeholders: {sh_created} skapade | {sh_updated} uppdaterade | {sh_unchanged} oforändrade
""")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synka GSF-agare och fastigheter till Odoo")
    parser.add_argument("xlsx", help="Sokvaeg till AegareDetaljerad.xlsx")
    parser.add_argument("--dry-run", action="store_true", help="Skriv inget till Odoo")
    parser.add_argument("--url", help="Odoo-URL, t.ex. http://localhost:8079")
    parser.add_argument("--db", help="Databasnamn, t.ex. gsf_t2")
    args = parser.parse_args(argv)
    run(args.xlsx, dry_run=args.dry_run, url=args.url, db=args.db)


if __name__ == "__main__":
    main()
