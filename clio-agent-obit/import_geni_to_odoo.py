"""
import_geni_to_odoo.py
Importerar geni_relations.json till Odoo:
  1. Sätter clio_obit_geni_id på befintliga res.partner (namnmatchning)
  2. Skapar clio.partner.link-poster för alla relationer

Kör: python import_geni_to_odoo.py [--json FILE] [--db examensbyran] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Lägg till clio-tools root i sökvägen så clio_odoo hittas
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent  # ...git/clio-tools
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from clio_odoo import connect  # type: ignore


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _norm(name: str) -> str:
    """Normalisera namn för matchning: lowercase, inga extra blanksteg."""
    return " ".join(name.lower().split())


def load_partners(env) -> dict[str, int]:
    """
    Läser alla res.partner med namn → {normerat_namn: partner_id}.
    Om flera partners har samma namn väljs den med högst ID.
    """
    Partner = env["res.partner"]
    records = Partner.search_read([], ["id", "name", "clio_obit_geni_id"], limit=0)
    by_name: dict[str, int] = {}
    by_geni: dict[str, int] = {}
    for r in records:
        pid = r["id"]
        name = r.get("name") or ""
        geni = r.get("clio_obit_geni_id") or ""
        key = _norm(name)
        if key:
            if key not in by_name or pid > by_name[key]:
                by_name[key] = pid
        if geni:
            by_geni[geni] = pid
    return by_name, by_geni


def find_partner(geni_id: str, name: str,
                 by_name: dict[str, int],
                 by_geni: dict[str, int]) -> int | None:
    """
    Slår upp befintlig partner via Geni-ID eller namn.
    Skapar ingenting — returnerar None om ingen matchning.
    """
    if geni_id in by_geni:
        return by_geni[geni_id]
    key = _norm(name)
    return by_name.get(key)


# ── Huvud-import ──────────────────────────────────────────────────────────────

def run(env, geni_data: dict, dry_run: bool, verbose: bool):
    Partner = env["res.partner"]
    Link = env["clio.partner.link"]

    print("Läser befintliga partners från Odoo...")
    by_name, by_geni = load_partners(env)
    print(f"  {len(by_name)} unika partnernamn, {len(by_geni)} med Geni-ID")

    # ── Steg 1: Koppla Geni-ID till partners ─────────────────────────────────
    geni_id_set = 0
    skipped = 0
    geni_to_partner: dict[str, int] = {}

    for geni_id, person in geni_data.items():
        name = person.get("name", "").strip()
        if not name:
            continue

        pid = find_partner(geni_id, name, by_name, by_geni)
        if pid is None:
            skipped += 1
            if verbose:
                print(f"  EJ MATCHAD: {name} ({geni_id})")
            continue

        geni_to_partner[geni_id] = pid

        # Upsert: sätt Geni-ID + URL (hämta aktuella värden för jämförelse)
        geni_url = person.get("geni_url", "")
        need_id  = by_geni.get(geni_id) != pid
        # Hämta befintlig URL för att avgöra om den behöver uppdateras
        current = Partner.read([pid], ["clio_obit_geni_id", "clio_obit_geni_url"])
        cur_id  = (current[0].get("clio_obit_geni_id") or "") if current else ""
        cur_url = (current[0].get("clio_obit_geni_url") or "") if current else ""
        need_url = bool(geni_url) and cur_url != geni_url

        if need_id or need_url:
            vals: dict = {}
            if need_id or not cur_id:
                vals["clio_obit_geni_id"] = geni_id
            if need_url:
                vals["clio_obit_geni_url"] = geni_url
            if vals:
                if not dry_run:
                    Partner.write([pid], vals)
                    by_geni[geni_id] = pid
                geni_id_set += 1
                if verbose:
                    print(f"  Uppdaterad: {name} ({pid}) {vals}")

    print(f"\nSteg 1 klar:")
    print(f"  Geni-ID satt/uppdaterat: {geni_id_set}")
    print(f"  Ej matchade (hoppas):    {skipped}")

    # ── Steg 2: Skapa clio.partner.link-poster ────────────────────────────────
    print("\nLäser befintliga clio.partner.link...")
    existing_links = Link.search_read(
        [], ["from_partner_id", "to_partner_id", "relation_label"], limit=0
    )
    existing_set: set[tuple] = {
        (r["from_partner_id"][0], r["to_partner_id"][0], r["relation_label"])
        for r in existing_links
    }
    print(f"  {len(existing_set)} befintliga relationer")

    links_created = 0
    links_skipped = 0

    for geni_id, person in geni_data.items():
        from_pid = geni_to_partner.get(geni_id)
        if from_pid is None:
            continue

        for rel in person.get("relations", []):
            to_geni = rel["geni_id"]
            to_pid = geni_to_partner.get(to_geni)
            if to_pid is None:
                continue

            label = rel["type"]
            key = (from_pid, to_pid, label)
            if key in existing_set:
                links_skipped += 1
                continue

            if not dry_run:
                Link.create({
                    "from_partner_id": from_pid,
                    "to_partner_id":   to_pid,
                    "relation_label":  label,
                })
            existing_set.add(key)
            links_created += 1
            if verbose:
                print(f"  LÄNK: {person['name']} --[{label}]--> {rel['name']}")

    print(f"\nSteg 2 klar:")
    print(f"  Nya relationer skapade:  {links_created}")
    print(f"  Redan befintliga:        {links_skipped}")

    if dry_run:
        print("\n[DRY RUN — inga ändringar sparades]")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Importera geni_relations.json -> Odoo res.partner + clio.partner.link"
    )
    p.add_argument(
        "--json",
        default="geni_relations.json",
        help="Sökväg till geni_relations.json (default: geni_relations.json)",
    )
    p.add_argument(
        "--db",
        default="examensbyran",
        help="Odoo-databas (default: examensbyran)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulera utan att skriva till Odoo",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Visa detaljerad logg per person/relation",
    )
    args = p.parse_args(argv)

    json_path = Path(args.json)
    if not json_path.exists():
        print(f"Hittar inte: {json_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Läser {json_path}...")
    with open(json_path, encoding="utf-8") as f:
        geni_data = json.load(f)
    print(f"  {len(geni_data)} personer i JSON")

    print(f"Ansluter till Odoo (db={args.db})...")
    env = connect(db=args.db)

    run(env, geni_data, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
