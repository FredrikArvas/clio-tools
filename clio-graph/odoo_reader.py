"""
odoo_reader.py
Läser partners och relationer från Odoo ORM. Återanvänder clio_odoo.connect().
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clio_odoo import connect


def get_env(url=None, db=None, user=None, password=None):
    return connect(url=url, db=db, user=user, password=password)


def read_partners(env) -> list[dict]:
    return env["res.partner"].search_read(
        [("active", "=", True)],
        ["id", "name", "email", "is_company"],
    )


def read_relations(env, only_sync: bool = True) -> list[dict]:
    domain = [("sync_to_neo4j", "=", True)] if only_sync else []
    return env["res.partner.relation"].search_read(
        domain,
        ["id", "left_partner_id", "right_partner_id", "type_id",
         "date_start", "date_end", "sync_to_neo4j"],
    )


def mark_synced(env, relation_ids: list[int], synced_at: datetime) -> None:
    if not relation_ids:
        return
    env["res.partner.relation"].browse(relation_ids).write(
        {"neo4j_synced_at": synced_at.strftime("%Y-%m-%d %H:%M:%S")}
    )
