"""neo4j_sync.py — Synka UAP-encounters från Odoo till Neo4j.

Idempotent: MERGE används genomgående.

Noder:    :Encounter, :Source, :Witness, :Location, :Country
Relationer: DOCUMENTED_IN, WITNESSED_BY, OCCURRED_AT, HAS_SOURCE
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

# Force-load local config.py (avoids shadowing by clio-tools/config/ package)
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("uap_config", Path(__file__).parent / "config.py")
_uap_config = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_uap_config)


def _neo4j_driver():
    config = _uap_config
    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit("neo4j-driver saknas. Kör: pip install neo4j")
    return GraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
    )


def _setup_constraints(session) -> None:
    session.run(
        "CREATE CONSTRAINT uap_encounter_id IF NOT EXISTS "
        "FOR (e:Encounter) REQUIRE e.encounter_id IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT uap_source_id IF NOT EXISTS "
        "FOR (s:Source) REQUIRE s.source_id IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT uap_witness_name IF NOT EXISTS "
        "FOR (w:Witness) REQUIRE w.name IS UNIQUE"
    )


def _upsert_encounter(session, enc: dict) -> None:
    session.run(
        """
        MERGE (e:Encounter {encounter_id: $encounter_id})
        SET e.title         = $title,
            e.date_observed = $date_observed,
            e.country       = $country,
            e.encounter_class = $encounter_class,
            e.discourse_level = $discourse_level,
            e.official_response = $official_response,
            e.status        = $status,
            e.odoo_id       = $odoo_id
        """,
        encounter_id    = enc.get("encounter_id", ""),
        title           = enc.get("title_en") or enc.get("title_original") or "",
        date_observed   = str(enc.get("date_observed", "") or ""),
        country         = enc.get("country_name", ""),
        encounter_class = enc.get("encounter_class", ""),
        discourse_level = enc.get("discourse_level", ""),
        official_response = enc.get("official_response", ""),
        status          = enc.get("status", "pending"),
        odoo_id         = enc.get("id", 0),
    )


def _upsert_source_link(session, encounter_id: str, source: dict) -> None:
    session.run(
        """
        MERGE (s:Source {source_id: $source_id})
        SET s.name        = $name,
            s.source_type = $source_type,
            s.tier        = $tier
        WITH s
        MATCH (e:Encounter {encounter_id: $encounter_id})
        MERGE (e)-[:DOCUMENTED_IN]->(s)
        """,
        source_id    = source.get("source_id", ""),
        name         = source.get("name", ""),
        source_type  = source.get("source_type", ""),
        tier         = source.get("tier", ""),
        encounter_id = encounter_id,
    )


def _upsert_witness_link(session, encounter_id: str, witness: dict) -> None:
    session.run(
        """
        MERGE (w:Witness {name: $name})
        SET w.witness_type = $witness_type,
            w.credibility  = $credibility
        WITH w
        MATCH (e:Encounter {encounter_id: $encounter_id})
        MERGE (e)-[:WITNESSED_BY]->(w)
        """,
        name         = witness.get("name", ""),
        witness_type = witness.get("witness_type", ""),
        credibility  = witness.get("credibility", ""),
        encounter_id = encounter_id,
    )


def _upsert_location(session, encounter_id: str, country: str, location: str) -> None:
    if not country:
        return
    session.run(
        """
        MERGE (c:Country {name: $country})
        WITH c
        MATCH (e:Encounter {encounter_id: $encounter_id})
        MERGE (e)-[:OCCURRED_AT]->(c)
        """,
        country      = country,
        encounter_id = encounter_id,
    )


def sync_all(dry_run: bool = False) -> None:
    from odoo_sync import get_env

    env = get_env()
    Encounter = env["uap.encounter"]
    Source    = env["uap.source"]
    Witness   = env["uap.witness"]

    encounters = Encounter.search_read(
        [],
        ["id", "encounter_id", "title_en", "title_original", "date_observed",
         "country_id", "encounter_class", "discourse_level", "official_response",
         "status", "source_ids", "witness_ids"],
    )
    print(f"[neo4j] {len(encounters)} encounters att synka")

    if dry_run:
        print("[neo4j] Dry-run — ingenting skrivs till Neo4j")
        for e in encounters[:5]:
            print(f"  → {e['encounter_id']} | {e.get('title_en', '')[:50]}")
        return

    driver = _neo4j_driver()
    with driver.session() as session:
        _setup_constraints(session)

        for enc in encounters:
            country_name = enc["country_id"][1] if enc.get("country_id") else ""
            enc["country_name"] = country_name
            _upsert_encounter(session, enc)

            # Sources
            if enc.get("source_ids"):
                sources = Source.search_read(
                    [("id", "in", enc["source_ids"])],
                    ["source_id", "name", "source_type", "tier"],
                )
                for src in sources:
                    _upsert_source_link(session, enc["encounter_id"], src)

            # Witnesses
            if enc.get("witness_ids"):
                witnesses = Witness.search_read(
                    [("id", "in", enc["witness_ids"])],
                    ["name", "witness_type", "credibility"],
                )
                for wit in witnesses:
                    _upsert_witness_link(session, enc["encounter_id"], wit)

            # Location / Country
            _upsert_location(
                session, enc["encounter_id"], country_name,
                enc.get("location", ""),
            )

    driver.close()
    print(f"[neo4j] Sync klar. {len(encounters)} encounters i grafen.")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    sync_all(dry_run=args.dry_run)
