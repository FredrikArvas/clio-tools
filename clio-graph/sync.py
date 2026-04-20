"""
sync.py
Huvud-sync: Odoo → Neo4j.

Upserterar (:Partner)-noder och [:RELATION]-kanter.
Uppdaterar neo4j_synced_at i Odoo efter lyckad synk.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from graph_client import GraphClient
from odoo_reader import get_env, read_partners, read_relations, mark_synced

_UPSERT_PARTNER = """
MERGE (p:Partner {odoo_id: $odoo_id})
SET p.name       = $name,
    p.email      = $email,
    p.is_company = $is_company
"""

_UPSERT_RELATION = """
MATCH (a:Partner {odoo_id: $left_id})
MATCH (b:Partner {odoo_id: $right_id})
MERGE (a)-[r:RELATION {odoo_id: $rel_id}]->(b)
SET r.type         = $rel_type,
    r.synced_at    = $synced_at
"""


def run_sync(dry_run: bool = False) -> tuple[int, int]:
    """
    Synkar alla aktiva partners och relationer (sync_to_neo4j=True) till Neo4j.
    Returnerar (antal_noder, antal_kanter).
    """
    env = get_env()
    partners  = read_partners(env)
    relations = read_relations(env, only_sync=True)
    synced_at = datetime.now(timezone.utc)

    if dry_run:
        print(f"  [dry-run] Skulle synka {len(partners)} noder, {len(relations)} kanter.")
        return len(partners), len(relations)

    with GraphClient() as graph:
        with graph.session() as s:
            for p in partners:
                s.run(
                    _UPSERT_PARTNER,
                    odoo_id=p["id"],
                    name=p["name"] or "",
                    email=p["email"] or "",
                    is_company=bool(p["is_company"]),
                )

            rel_ids = []
            for r in relations:
                left_id  = r["left_partner_id"][0]  if r["left_partner_id"]  else None
                right_id = r["right_partner_id"][0] if r["right_partner_id"] else None
                rel_type = r["type_id"][1]           if r["type_id"]          else ""
                if left_id is None or right_id is None:
                    continue
                s.run(
                    _UPSERT_RELATION,
                    left_id=left_id,
                    right_id=right_id,
                    rel_id=r["id"],
                    rel_type=rel_type,
                    synced_at=synced_at.isoformat(),
                )
                rel_ids.append(r["id"])

    mark_synced(env, rel_ids, synced_at)
    return len(partners), len(rel_ids)
