"""
sync_odoo_to_neo4j.py
Synkar bevakade kontakter och familjerelationer från Odoo till Neo4j.

Körs manuellt eller via cron. Idempotent — MERGE används genomgående.

Usage:
    python3 sync_odoo_to_neo4j.py
    python3 sync_odoo_to_neo4j.py --dry-run
    python3 sync_odoo_to_neo4j.py --clear   # tar bort alla Clio-noder först
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
for _p in [str(_ROOT / "clio-agent-obit"), str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

NEO4J_URI      = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.environ.get("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

RELATION_TYPE_MAP = {
    "make/maka": "MAKE_MAKA",
    "barn":      "BARN",
    "förälder":  "FORALDER",
    "syskon":    "SYSKON",
}


# ── Neo4j-hjälpare ────────────────────────────────────────────────────────────

def _neo4j_driver():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Fel: neo4j-driver saknas. Installera med: pip install neo4j")
        sys.exit(1)
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def setup_constraints(session) -> None:
    """Skapar unika index på Person(odoo_id) — engångskörning är idempotent."""
    session.run(
        "CREATE CONSTRAINT person_odoo_id IF NOT EXISTS "
        "FOR (p:Person) REQUIRE p.odoo_id IS UNIQUE"
    )


def clear_clio_nodes(session) -> None:
    """Tar bort alla Person-noder och deras relationer."""
    result = session.run("MATCH (p:Person) DETACH DELETE p")
    counters = result.consume().counters
    print(f"Rensade {counters.nodes_deleted} noder, {counters.relationships_deleted} relationer")


# ── Odoo-hämtning ─────────────────────────────────────────────────────────────

def fetch_partners(env) -> list[dict]:
    """Hämtar alla bevakade partners (clio_obit_watch=True)."""
    return env["res.partner"].search_read(
        [("clio_obit_watch", "=", True), ("is_company", "=", False)],
        [
            "id", "name",
            "clio_obit_birth_name", "clio_obit_birth_year", "clio_obit_death_year",
            "clio_family_role", "city",
        ],
    )


def fetch_links(env) -> list[dict]:
    """Hämtar alla clio.partner.link-rader."""
    return env["clio.partner.link"].search_read(
        [],
        ["from_partner_id", "to_partner_id", "relation_label"],
    )


# ── Synk ─────────────────────────────────────────────────────────────────────

def sync_persons(session, partners: list[dict], dry_run: bool) -> int:
    count = 0
    for p in partners:
        props = {
            "odoo_id":    p["id"],
            "name":       p["name"] or "",
            "birth_name": p.get("clio_obit_birth_name") or "",
            "birth_year": p.get("clio_obit_birth_year") or 0,
            "death_year": p.get("clio_obit_death_year") or 0,
            "family_role": p.get("clio_family_role") or "",
            "city":       p.get("city") or "",
        }
        if dry_run:
            count += 1
            continue
        session.run(
            """
            MERGE (p:Person {odoo_id: $odoo_id})
            SET p.name       = $name,
                p.birth_name = $birth_name,
                p.birth_year = $birth_year,
                p.death_year = $death_year,
                p.family_role = $family_role,
                p.city       = $city
            """,
            **props,
        )
        count += 1
    return count


def sync_relations(session, links: list[dict], dry_run: bool) -> tuple[int, int]:
    created = skipped = 0
    for lnk in links:
        from_id = lnk["from_partner_id"][0]
        to_id   = lnk["to_partner_id"][0]
        label   = lnk["relation_label"] or ""
        rel_type = RELATION_TYPE_MAP.get(label, "RELATION")

        if dry_run:
            created += 1
            continue

        result = session.run(
            f"""
            MATCH (a:Person {{odoo_id: $from_id}})
            MATCH (b:Person {{odoo_id: $to_id}})
            MERGE (a)-[r:{rel_type} {{label: $label}}]->(b)
            RETURN r
            """,
            from_id=from_id, to_id=to_id, label=label,
        )
        if result.single():
            created += 1
        else:
            skipped += 1
    return created, skipped


# ── Huvud ─────────────────────────────────────────────────────────────────────

def run_sync(dry_run: bool = False, clear: bool = False) -> None:
    from clio_odoo import connect
    env = connect()

    print("Hämtar data från Odoo...")
    partners = fetch_partners(env)
    links    = fetch_links(env)
    print(f"  {len(partners)} bevakade kontakter")
    print(f"  {len(links)} relationer")

    if dry_run:
        print(f"\nDRY RUN — inga ändringar görs i Neo4j.")
        print(f"  Skulle synka {len(partners)} noder, {len(links)} kanter")
        return

    driver = _neo4j_driver()
    with driver.session() as session:
        setup_constraints(session)

        if clear:
            print("Rensar befintliga Clio-noder...")
            clear_clio_nodes(session)

        print("Synkar noder...")
        n_persons = sync_persons(session, partners, dry_run=False)

        print("Synkar relationer...")
        n_created, n_skipped = sync_relations(session, links, dry_run=False)

    driver.close()

    print(f"\n── Klart ──────────────────────────────────")
    print(f"  Noder (Person):  {n_persons}")
    print(f"  Kanter skapade:  {n_created}")
    print(f"  Kanter redan ok: {n_skipped}")
    print(f"\nÖppna Neo4j Browser: {NEO4J_URI.replace('bolt://', 'http://').replace('7687', '7474')}")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Synka Odoo → Neo4j")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--clear",   action="store_true",
                   help="Rensa alla Person-noder innan synk")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    run_sync(dry_run=args.dry_run, clear=args.clear)


if __name__ == "__main__":
    main()
