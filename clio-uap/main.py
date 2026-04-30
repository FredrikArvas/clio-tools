"""
main.py — clio-uap: UAP Tracking CLI

Användning:
    python main.py import --path "C:/Users/fredr/Dropbox/projekt/UAP/UAP Research project"
    python main.py import --dry-run
    python main.py stats
    python main.py validate
    python main.py sync-neo4j
    python main.py sync-qdrant
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# UTF-8 på Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_BASE_DIR = Path(__file__).parent

# clio-uap must be first in sys.path to shadow the clio-tools/config/ package
_ROOT_DIR = _BASE_DIR.parent
for _p in [str(_ROOT_DIR), str(_BASE_DIR)]:
    if _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, str(_ROOT_DIR))
sys.path.insert(0, str(_BASE_DIR))


def _banner():
    print("=" * 60)
    print("  clio-uap — UAP Tracking Migration & CLI")
    print("=" * 60)


def cmd_import(args):
    """Importera UAP-data från Notion CSV-export till Odoo."""
    import config
    from migrate import load_sources, load_witnesses, load_encounters, load_verifications
    from odoo_sync import (
        get_env, upsert_source, upsert_witness, upsert_encounter, upsert_verification,
    )

    data_path = Path(args.path) if args.path else config.UAP_DATA_PATH
    dry_run   = args.dry_run

    print(f"\n[import] Källmapp: {data_path}")
    print(f"[import] Dry-run: {dry_run}\n")

    # --- Steg 1: Läs data ---
    print("[1/5] Läser Sources...")
    sources = load_sources(data_path)
    print(f"       {len(sources)} sources")

    print("[2/5] Läser Witnesses...")
    witnesses = load_witnesses(data_path)
    print(f"       {len(witnesses)} witnesses")

    print("[3/5] Läser Encounters...")
    encounters = load_encounters(data_path)
    print(f"       {len(encounters)} encounters")

    print("[4/5] Läser Verification Log...")
    verifications = load_verifications(data_path)
    print(f"       {len(verifications)} verifications\n")

    if not any([sources, witnesses, encounters]):
        print("[FEL] Inga data hittades. Kontrollera sökvägen.")
        return 1

    # --- Steg 2: Anslut till Odoo (skip vid dry-run) ---
    env = None
    if not dry_run:
        print("[5/5] Ansluter till Odoo...")
        env = get_env()
        print("       Ansluten.\n")

    # --- Steg 3: Importera Sources ---
    print("[IMPORT] Sources")
    source_id_map: dict[str, int] = {}
    source_name_map: dict[str, int] = {}
    for row in sources:
        odoo_id = upsert_source(env, row, dry_run=dry_run)
        if odoo_id:
            source_id_map[row["source_id"]] = odoo_id
            source_name_map[row["name"]] = odoo_id
    print(f"  → {len(sources)} sources importerade\n")

    # --- Steg 4: Importera Witnesses ---
    print("[IMPORT] Witnesses")
    witness_name_map: dict[str, int] = {}
    for row in witnesses:
        odoo_id = upsert_witness(env, row, dry_run=dry_run)
        if odoo_id:
            witness_name_map[row["name"]] = odoo_id
    print(f"  → {len(witnesses)} witnesses importerade\n")

    # --- Steg 5: Importera Encounters (med relationer) ---
    print("[IMPORT] Encounters")
    encounter_id_map: dict[str, int] = {}
    country_cache: dict[str, int] = {}
    enc_ok = 0
    RECONNECT_EVERY = 100  # återanslut för att undvika session-timeout

    for i, row in enumerate(encounters):
        # Periodic reconnect to avoid Odoo session timeout on large imports
        if not dry_run and i > 0 and i % RECONNECT_EVERY == 0:
            print(f"    [{i}/{len(encounters)}] Återansluter till Odoo...")
            env = get_env()

        # Resolva sources (by name, since encounters reference sources by display name)
        src_ids = [
            source_name_map[sn]
            for sn in row.get("_source_names", [])
            if sn in source_name_map
        ]
        # Resolva witnesses
        wit_ids = [
            witness_name_map[wn]
            for wn in row.get("_witness_names", [])
            if wn in witness_name_map
        ]
        # Resolva country
        country_name = row.pop("_country_name", "")
        row.pop("_source_names", None)
        row.pop("_witness_names", None)

        if country_name and env and not dry_run:
            if country_name not in country_cache:
                Country = env["res.country"]
                results = Country.search_read(
                    [("name", "ilike", country_name)], ["id", "name"], limit=1
                )
                country_cache[country_name] = results[0]["id"] if results else False
            row["country_id"] = country_cache.get(country_name, False)

        try:
            odoo_id = upsert_encounter(env, row, src_ids, wit_ids, dry_run=dry_run)
        except Exception as e:
            print(f"    [FEL] {row.get('encounter_id', '?')}: {e}")
            if not dry_run:
                env = get_env()  # reconnect after error
            continue
        if odoo_id:
            encounter_id_map[row["encounter_id"]] = odoo_id
            enc_ok += 1
    print(f"  → {enc_ok}/{len(encounters)} encounters importerade\n")

    # --- Steg 6: Importera Verifications ---
    print("[IMPORT] Verification Log")
    ver_ok = 0
    for row in verifications:
        enc_text_id = row.pop("_encounter_id", "")
        encounter_odoo_id = encounter_id_map.get(enc_text_id)
        if not encounter_odoo_id and not dry_run:
            continue
        odoo_id = upsert_verification(
            env, row,
            encounter_odoo_id=encounter_odoo_id or 0,
            dry_run=dry_run,
        )
        if odoo_id or dry_run:
            ver_ok += 1
    print(f"  → {ver_ok} verifications importerade\n")

    print("[KLAR] Import genomförd.")
    return 0


def cmd_stats(args):
    """Visa antal poster per UAP-modell i Odoo."""
    import config  # loads .env including ODOO_DB=uapdb
    from odoo_sync import get_env, get_model_counts
    print("\n[stats] Ansluter till Odoo...")
    env = get_env()
    counts = get_model_counts(env)
    print("\n  UAP-data i Odoo:")
    for model, count in counts.items():
        label = model.replace("uap.", "").capitalize()
        print(f"    {label:<15} {count}")
    print()
    return 0


def cmd_validate(args):
    """Validera data i CSV-filerna utan att skriva till Odoo."""
    import config
    from migrate import load_sources, load_witnesses, load_encounters, load_verifications

    data_path = Path(args.path) if args.path else config.UAP_DATA_PATH
    errors = 0

    sources = load_sources(data_path)
    witnesses = load_witnesses(data_path)
    encounters = load_encounters(data_path)
    verifications = load_verifications(data_path)

    print(f"\n[validate] sources:       {len(sources)}")
    print(f"[validate] witnesses:     {len(witnesses)}")
    print(f"[validate] encounters:    {len(encounters)}")
    print(f"[validate] verifications: {len(verifications)}")

    warnings = 0

    # Duplicerade source_id — hanteras av upsert (sista skrivning vinner)
    source_ids = [s["source_id"] for s in sources]
    dupes = set(sid for sid in source_ids if source_ids.count(sid) > 1)
    if dupes:
        print(f"[INFO]    Duplicerade source_id (upsert hanterar): {dupes}")
        warnings += 1

    # Duplicerade encounter_id — hanteras av upsert
    enc_ids = [e["encounter_id"] for e in encounters]
    dupes = set(eid for eid in enc_ids if enc_ids.count(eid) > 1)
    if dupes:
        print(f"[INFO]    Duplicerade encounter_id (upsert hanterar): {dupes}")
        warnings += 1

    # Verifications utan matchande encounter
    enc_set = set(enc_ids)
    orphan_vers = [v for v in verifications if v.get("_encounter_id") not in enc_set]
    if orphan_vers:
        orphan_prefixes = set(
            v["_encounter_id"].split("_")[0] + "_" + v["_encounter_id"].split("_")[1]
            for v in orphan_vers if "_" in v.get("_encounter_id", "")
        )
        print(f"[INFO]    {len(orphan_vers)} verifications ref. encounters ej i denna export "
              f"(prefix: {orphan_prefixes}) — hoppar över vid import")
        warnings += 1

    matched_vers = len(verifications) - len(orphan_vers)
    print(f"\n[validate] Verifications som kan importeras: {matched_vers}/{len(verifications)}")

    print(f"\n[OK] Validering klar. {warnings} informationsmeddelanden (0 blockerande fel).")
    return 0


def cmd_sync_neo4j(args):
    """Synka UAP-encounters till Neo4j."""
    from neo4j_sync import sync_all
    print("\n[neo4j] Startar Neo4j-sync...")
    sync_all(dry_run=args.dry_run)
    return 0


def cmd_sync_qdrant(args):
    """Indexera UAP-encounters i Qdrant."""
    from qdrant_index import index_all
    print("\n[qdrant] Startar Qdrant-indexering...")
    index_all(dry_run=args.dry_run)
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="clio-uap — UAP Tracking CLI")
    sub = p.add_subparsers(dest="command")

    # import
    p_import = sub.add_parser("import", help="Importera Notion CSV → Odoo")
    p_import.add_argument("--path", default=None,
                          help="Sökväg till UAP Research Project-mappen")
    p_import.add_argument("--dry-run", action="store_true",
                          help="Simulera utan att skriva till Odoo")

    # stats
    sub.add_parser("stats", help="Visa antal poster per modell i Odoo")

    # validate
    p_val = sub.add_parser("validate", help="Validera CSV-data utan att importera")
    p_val.add_argument("--path", default=None)

    # sync-neo4j
    p_neo4j = sub.add_parser("sync-neo4j", help="Synka till Neo4j")
    p_neo4j.add_argument("--dry-run", action="store_true")

    # sync-qdrant
    p_qdrant = sub.add_parser("sync-qdrant", help="Indexera i Qdrant")
    p_qdrant.add_argument("--dry-run", action="store_true")

    return p.parse_args(argv)


def main(argv=None) -> None:
    _banner()
    args = parse_args(argv)
    if not args.command:
        parse_args(["--help"])
        return

    dispatch = {
        "import":      cmd_import,
        "stats":       cmd_stats,
        "validate":    cmd_validate,
        "sync-neo4j":  cmd_sync_neo4j,
        "sync-qdrant": cmd_sync_qdrant,
    }
    func = dispatch.get(args.command)
    if func:
        sys.exit(func(args))


if __name__ == "__main__":
    main()
