"""
import_gedcom_to_odoo.py
Importerar ett GEDCOM-släktträd till Odoo res.partner med clio_obit_watch=True.

Återanvänder all parsninglogik från clio-partnerdb/import_gedcom.py.
Skriver till Odoo istället för partnerdb.

Idempotent, två nivåer:
  1. GEDCOM-ID (ir.model.data, modul clio_obit_gedcom) — primär nyckel.
     Hittar rätt partner även om namn ändrats (t.ex. giftermål).
  2. Namn + födelseår — fallback för nyimport eller om GEDCOM-ID saknas.

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


def _odoo_create(env, model: str, vals: dict) -> int:
    """Skapar en post och returnerar alltid ett heltal-ID (ORM eller xmlrpc)."""
    result = env[model].create(vals)
    return result.id if hasattr(result, "id") else int(result)


def _odoo_write(env, model: str, ids: list, vals: dict) -> None:
    """Skriver till poster med ids (ORM eller xmlrpc)."""
    if hasattr(env[model], "browse"):
        env[model].browse(ids).write(vals)
    else:
        env[model].write(ids, vals)


# ── Namnsökning i Odoo ───────────────────────────────────────────────────────

_GEDCOM_MODULE = "clio_obit_gedcom"


def _xref_to_name(xref: str) -> str:
    """Konverterar '@I42@' → 'I42' (giltigt ir.model.data-namn)."""
    return xref.strip("@").replace(" ", "_")


def _build_odoo_lookup(env) -> dict[tuple, int]:
    """
    Hämtar alla partners med namn + födelsenamn från Odoo.
    Returnerar {(fornamn_lower, efternamn_lower): partner_id}.
    Inkluderar clio_obit_birth_name som alternativ efternamns-nyckel.
    """
    rows = env["res.partner"].search_read(
        [("is_company", "=", False)],
        ["id", "name", "clio_obit_birth_name"],
    )
    lookup: dict[tuple, int] = {}
    for r in rows:
        pid = r["id"]
        name = (r.get("name") or "").strip()
        parts = name.split()
        if len(parts) >= 2:
            fornamn = " ".join(parts[:-1]).lower()
            efternamn = parts[-1].lower()
            lookup.setdefault((fornamn, efternamn), pid)

        # Födelsenamn som alternativ matchningsnyckel
        birth_name = (r.get("clio_obit_birth_name") or "").strip()
        if birth_name:
            bparts = birth_name.split()
            if len(bparts) >= 2:
                bf = " ".join(bparts[:-1]).lower()
                be = bparts[-1].lower()
                lookup.setdefault((bf, be), pid)
    return lookup


def _build_gedcom_id_lookup(env) -> dict[str, int]:
    """
    Hämtar alla ir.model.data-poster för modul clio_obit_gedcom.
    Returnerar {xref_name: partner_id}, t.ex. {'I42': 1337}.
    """
    rows = env["ir.model.data"].search_read(
        [("module", "=", _GEDCOM_MODULE), ("model", "=", "res.partner")],
        ["name", "res_id"],
    )
    return {r["name"]: r["res_id"] for r in rows if r.get("res_id")}


def _store_gedcom_xref(env, xref: str, partner_id: int) -> None:
    """
    Sparar eller uppdaterar GEDCOM-ID → partner-kopplingen i ir.model.data.
    Idempotent: befintlig post skrivs aldrig om med samma res_id.
    """
    name = _xref_to_name(xref)
    existing = env["ir.model.data"].search_read(
        [("module", "=", _GEDCOM_MODULE), ("name", "=", name)],
        ["id", "res_id"],
    )
    if existing:
        if existing[0]["res_id"] != partner_id:
            _odoo_write(env, "ir.model.data", [existing[0]["id"]], {"res_id": partner_id})
    else:
        _odoo_create(env, "ir.model.data", {
            "module":   _GEDCOM_MODULE,
            "name":     name,
            "model":    "res.partner",
            "res_id":   partner_id,
            "noupdate": True,
        })


def _find_or_create_partner(
    env,
    lookup: dict,
    gedcom_lookup: dict,
    fornamn: str,
    efternamn: str,
    birth_year: int | None,
    birth_place: str | None,
    gedcom_xref: str | None,
    dry_run: bool,
) -> tuple[int | None, str]:
    """
    Hittar befintlig partner eller skapar ny.
    Söker i prioritetsordning:
      1. GEDCOM-ID (ir.model.data) — robust mot namnbyten
      2. Namn (visnings- eller födelsenamn) — fallback för nyimport
    Returnerar (partner_id, action) där action är 'found'|'created'|'dry_run'.
    """
    # 1. GEDCOM-ID-sökning
    if gedcom_xref:
        xref_name = _xref_to_name(gedcom_xref)
        pid = gedcom_lookup.get(xref_name)
        if pid:
            return pid, "found"

    # 2. Namnmatchning (visningsnamn eller födelsenamn)
    fn_low = fornamn.lower()
    en_low = efternamn.lower()
    pid = lookup.get((fn_low, en_low))

    if pid:
        return pid, "found"

    if dry_run:
        return None, "dry_run"

    # Skapa ny partner — GEDCOM-namn blir födelsenamn, också visningsnamn vid skapande
    birth_name = f"{fornamn} {efternamn}"
    vals: dict = {
        "name":                  birth_name,
        "is_company":            False,
        "clio_obit_birth_name":  birth_name,
    }
    if birth_place:
        vals["city"] = birth_place[:100]

    pid = _odoo_create(env, "res.partner", vals)
    # Uppdatera lookup för idempotens inom samma körning
    lookup[(fn_low, en_low)] = pid
    return pid, "created"


def _upsert_watch_record(env, partner_id: int, priority_odoo: str, user_id: int, dry_run: bool):
    """Skapar eller uppdaterar en clio.obit.watch-rad för partner+användare."""
    if dry_run:
        return
    existing = env["clio.obit.watch"].search_read(
        [("partner_id", "=", partner_id), ("user_id", "=", user_id)],
        ["id"],
    )
    vals = {"partner_id": partner_id, "user_id": user_id, "priority": priority_odoo}
    if existing:
        _odoo_write(env, "clio.obit.watch", [existing[0]["id"]], {"priority": priority_odoo})
    else:
        _odoo_create(env, "clio.obit.watch", vals)


# ── Huvudimport ──────────────────────────────────────────────────────────────

def run_import(
    gedcom_path: str,
    user_id: int | None,
    ego_name: str | None,
    depth: int,
    full: bool,
    dry_run: bool,
    env=None,
    owner_email: str | None = None,  # Legacy CLI-parameter, används ej internt
) -> None:
    """
    env: skickas in från Odoo-wizard (self.env) för att undvika deadlock.
         Om None används _get_env() (CLI-läge via xmlrpc).
    user_id: Odoo res.users ID för bevakningsrelationen.
             I CLI-läge: slås upp via owner_email om None.
    """
    print(f"\n{'DRY RUN — ' if dry_run else ''}Importerar {gedcom_path}")
    print(f"Djup: {'full' if full else depth}")

    # ── Parsa GEDCOM ──────────────────────────────────────────────────────────
    utf8_path, is_temp = _to_utf8_tempfile(gedcom_path)
    parser = Parser()
    parser.parse_file(utf8_path, strict=False)
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
    if env is None:
        env = _get_env()

    # Slå upp user_id via owner_email i CLI-läge
    if user_id is None and owner_email:
        users = env["res.users"].search_read(
            [("login", "=", owner_email)], ["id", "name"]
        )
        if not users:
            users = env["res.users"].search_read(
                [("email", "=", owner_email)], ["id", "name"]
            )
        if users:
            user_id = users[0]["id"]
            print(f"Bevakare: {users[0]['name']} (id={user_id})")
        else:
            print(f"Varning: Ingen användare med e-post {owner_email} — faller tillbaka på admin (id=1)")
            user_id = 1

    if not user_id:
        print("Fel: user_id krävs. Ange --owner EMAIL i CLI-läge.")
        return

    lookup = _build_odoo_lookup(env)
    gedcom_lookup = _build_gedcom_id_lookup(env)
    print(f"Odoo har {len(lookup)} befintliga kontakter, {len(gedcom_lookup)} GEDCOM-ID-kopplingar")

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
        gedcom_xref = ind.get_pointer() if hasattr(ind, "get_pointer") else None

        pid, action = _find_or_create_partner(
            env, lookup, gedcom_lookup,
            fornamn, efternamn, birth_year, birth_place,
            gedcom_xref, dry_run,
        )
        # birth_year behålls i signaturen för framtida eget fält men används ej mot Odoo nu

        if action == "dry_run":
            dry_count += 1
            print(f"  [DRY] {fornamn} {efternamn} ({birth_year or '?'}) → {priority_odoo}")
            continue

        _upsert_watch_record(env, pid, priority_odoo, user_id, dry_run)

        # Spara GEDCOM-ID → partner-kopplingen (idempotent)
        if gedcom_xref and pid:
            _store_gedcom_xref(env, gedcom_xref, pid)
            gedcom_lookup[_xref_to_name(gedcom_xref)] = pid

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
    p.add_argument("--owner",    required=True, metavar="EMAIL",    help="E-post för bevakaren (slås upp mot res.users)")
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
        user_id      = None,
        owner_email  = args.owner,
        ego_name     = args.ego,
        depth        = args.depth,
        full         = args.full,
        dry_run      = args.dry_run,
    )


if __name__ == "__main__":
    main()
