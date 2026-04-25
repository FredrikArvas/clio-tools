"""
import_gedcom_to_odoo.py
Importerar ett GEDCOM-släktträd till Odoo res.partner med clio_obit_watch=True.

Återanvänder all parsninglogik från clio-partnerdb/import_gedcom.py.
Skriver till Odoo istället för partnerdb.

Idempotent: matchar på namn + födelseår. Befintliga partner uppdateras
med bevakningsflaggor utan att dubbletter skapas.

Usage:
    python import_gedcom_to_odoo.py --gedcom FILE.ged --owner EMAIL
    python import_gedcom_to_odoo.py --gedcom FILE.ged --owner EMAIL --ego "Fredrik Arvas"
    python import_gedcom_to_odoo.py --gedcom FILE.ged --owner EMAIL --depth 2
    python import_gedcom_to_odoo.py --gedcom FILE.ged --owner EMAIL --full
    python import_gedcom_to_odoo.py --gedcom FILE.ged --owner EMAIL --dry-run

Djup och prioritet:
    --depth 1  → djupa relationer (make/maka, barn, föräldrar) → viktig
    --depth 2  → syskon, mor/farföräldrar → normal  [standard]
    --depth 3  → syskonbarn, fastrar/morbröder → normal

Prioritetsöversättning:
    important → viktig
    normal    → normal
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Lägg till clio-partnerdb och clio-tools i sökvägen
_ROOT = Path(__file__).parent.parent
_PARTNERDB = _ROOT / "clio-partnerdb"
for _p in [str(_ROOT), str(_PARTNERDB)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Återanvänd parsning från clio-partnerdb
from import_gedcom import (
    _to_utf8_tempfile,
    find_ego,
    _collect_ego_network,
    _collect_full,
    _get_name,
    _extract_birth_year,
    _extract_birth_place,
    _is_likely_alive,
)

try:
    from gedcom.parser import Parser
    from gedcom.element.individual import IndividualElement
except ImportError:
    print("Fel: python-gedcom saknas. Installera med: pip install python-gedcom")
    sys.exit(1)

PRIORITY_MAP = {
    "important": "viktig",
    "normal":    "normal",
}


# ── Odoo-anslutning ──────────────────────────────────────────────────────────

def _get_env():
    from clio_odoo import connect
    try:
        return connect()
    except Exception as e:
        print(f"Odoo-anslutning misslyckades: {e}")
        sys.exit(1)


# ── Namnsökning i Odoo ───────────────────────────────────────────────────────

def _build_odoo_lookup(env) -> dict[tuple, int]:
    """
    Hämtar alla partners med namn + birthdate från Odoo.
    Returnerar {(fornamn_lower, efternamn_lower, birth_year_or_0): partner_id}.
    """
    rows = env["res.partner"].search_read(
        [("is_company", "=", False)],
        ["id", "name", "birthdate"],
    )
    lookup: dict[tuple, int] = {}
    for r in rows:
        name = (r.get("name") or "").strip()
        parts = name.split()
        if len(parts) < 2:
            continue
        fornamn = " ".join(parts[:-1]).lower()
        efternamn = parts[-1].lower()
        bd = r.get("birthdate") or ""
        birth_year = 0
        if bd and len(bd) >= 4:
            try:
                birth_year = int(bd[:4])
            except ValueError:
                pass
        lookup[(fornamn, efternamn, birth_year)] = r["id"]
        # Lägg också in utan födelseår som fallback
        lookup.setdefault((fornamn, efternamn, 0), r["id"])
    return lookup


def _find_or_create_partner(
    env,
    lookup: dict,
    fornamn: str,
    efternamn: str,
    birth_year: int | None,
    birth_place: str | None,
    dry_run: bool,
) -> tuple[int | None, str]:
    """
    Hittar befintlig partner eller skapar ny.
    Returnerar (partner_id, action) där action är 'found'|'created'|'dry_run'.
    """
    fn_low = fornamn.lower()
    en_low = efternamn.lower()
    by = birth_year or 0

    # Försök: exakt namn + födelseår
    pid = lookup.get((fn_low, en_low, by))
    # Fallback: bara namn (födelseår okänt)
    if pid is None and by:
        pid = lookup.get((fn_low, en_low, 0))

    if pid:
        return pid, "found"

    if dry_run:
        return None, "dry_run"

    # Skapa ny partner
    vals: dict = {
        "name":         f"{fornamn} {efternamn}",
        "is_company":   False,
    }
    if birth_year:
        vals["birthdate"] = f"{birth_year}-01-01"
    if birth_place:
        vals["city"] = birth_place[:100]

    pid = env["res.partner"].create(vals)
    # Uppdatera lookup för idempotens inom samma körning
    lookup[(fn_low, en_low, by)] = pid
    lookup.setdefault((fn_low, en_low, 0), pid)
    return pid, "created"


def _set_watch_fields(env, partner_id: int, priority_odoo: str, owner_email: str, dry_run: bool):
    """Sätter clio_obit-fälten på en befintlig partner."""
    if dry_run:
        return
    env["res.partner"].write([partner_id], {
        "clio_obit_watch":         True,
        "clio_obit_priority":      priority_odoo,
        "clio_obit_notify_email":  owner_email,
    })


# ── Huvudimport ──────────────────────────────────────────────────────────────

def run_import(
    gedcom_path: str,
    owner_email: str,
    ego_name: str | None,
    depth: int,
    full: bool,
    dry_run: bool,
) -> None:
    print(f"\n{'DRY RUN — ' if dry_run else ''}Importerar {gedcom_path}")
    print(f"Ägare: {owner_email} | Djup: {'full' if full else depth}")

    # ── Parsa GEDCOM ──────────────────────────────────────────────────────────
    utf8_path, is_temp = _to_utf8_tempfile(gedcom_path)
    parser = Parser()
    parser.parse_file(utf8_path)
    if is_temp:
        os.unlink(utf8_path)

    # ── Välj poster ───────────────────────────────────────────────────────────
    if full:
        candidates: list[tuple] = _collect_full(parser)
        print(f"Helträd: {len(candidates)} levande individer hittade")
    else:
        ego = find_ego(parser, owner_email, ego_name)
        if ego:
            candidates = _collect_ego_network(ego, parser, depth)
            ego_name_str = " ".join(_get_name(ego)) if _get_name(ego) else "?"
            print(f"Ego: {ego_name_str} | Nätverk (djup {depth}): {len(candidates)} individer")
        else:
            candidates = _collect_full(parser)
            print(f"Inget ego hittat — helträd: {len(candidates)} individer")

    if not candidates:
        print("Inga individer att importera.")
        return

    # ── Odoo ──────────────────────────────────────────────────────────────────
    env = _get_env()
    lookup = _build_odoo_lookup(env)
    print(f"Odoo har {len(lookup)} befintliga kontakter")

    created = updated = skipped = dry_count = 0

    for ind, priority_en in candidates:
        name = _get_name(ind)
        if not name:
            skipped += 1
            continue
        fornamn, efternamn = name
        birth_year = _extract_birth_year(ind)
        birth_place = _extract_birth_place(ind)
        priority_odoo = PRIORITY_MAP.get(priority_en, "normal")

        pid, action = _find_or_create_partner(
            env, lookup, fornamn, efternamn, birth_year, birth_place, dry_run
        )

        if action == "dry_run":
            dry_count += 1
            print(f"  [DRY] {fornamn} {efternamn} ({birth_year or '?'}) → {priority_odoo}")
            continue

        _set_watch_fields(env, pid, priority_odoo, owner_email, dry_run)

        if action == "created":
            created += 1
            print(f"  [NY]  {fornamn} {efternamn} ({birth_year or '?'}) → {priority_odoo}")
        else:
            updated += 1

    # ── Rapport ───────────────────────────────────────────────────────────────
    print(f"\n{'─' * 50}")
    if dry_run:
        print(f"DRY RUN: {dry_count} skulle ha importerats, {skipped} hoppades över")
    else:
        print(f"Klart: {created} nya partners, {updated} uppdaterade, {skipped} hoppades över")
        print(f"Alla satta till clio_obit_watch=True, notify → {owner_email}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Importera GEDCOM-släktträd till Odoo res.partner med dödsannonsbevakning"
    )
    p.add_argument("--gedcom",   required=True, metavar="FILE.ged", help="Sökväg till GEDCOM-fil")
    p.add_argument("--owner",    required=True, metavar="EMAIL",    help="E-post som får notiser")
    p.add_argument("--ego",      metavar="NAMN", default=None,       help="Ego-person i trädet (namn)")
    p.add_argument("--depth",    type=int, default=2, choices=[1, 2, 3],
                   help="Antal relationsled från ego (1–3, standard: 2)")
    p.add_argument("--full",     action="store_true",
                   help="Importera hela trädet (alla levande individer)")
    p.add_argument("--dry-run",  action="store_true",
                   help="Simulera — gör inga ändringar i Odoo")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    run_import(
        gedcom_path  = args.gedcom,
        owner_email  = args.owner,
        ego_name     = args.ego,
        depth        = args.depth,
        full         = args.full,
        dry_run      = args.dry_run,
    )


if __name__ == "__main__":
    main()
