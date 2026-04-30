"""odoo_sync.py — Upsert-logik mot Odoo för UAP-modeller."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))


def _to_id(result) -> int | None:
    """Extrahera int-ID från OdooRecord/OdooRecordset/int returnerat av create()."""
    if result is None:
        return None
    if isinstance(result, int):
        return result
    if hasattr(result, "id"):
        return int(result.id)
    if hasattr(result, "ids") and result.ids:
        return int(result.ids[0])
    try:
        return int(result)
    except (TypeError, ValueError):
        return None


def get_env():
    from clio_odoo import connect
    return connect()


def upsert_source(env, row: dict, dry_run: bool = False) -> int | None:
    """Skapa eller uppdatera en uap.source. Returnerar Odoo-ID."""
    if dry_run:
        print(f"  [DRY] uap.source: {row['source_id']} — {row.get('name', '')}")
        return None

    Source = env["uap.source"]
    existing = Source.search_read([("source_id", "=", row["source_id"])], ["id"])
    vals = {k: v for k, v in row.items() if v not in (None, "", False) or k == "name"}

    if existing:
        ids = [r["id"] for r in existing]
        Source.write(ids, vals)
        return ids[0]
    else:
        return _to_id(Source.create(vals))


def upsert_witness(env, row: dict, dry_run: bool = False) -> int | None:
    """Skapa eller uppdatera en uap.witness. Returnerar Odoo-ID."""
    if dry_run:
        print(f"  [DRY] uap.witness: {row['name']}")
        return None

    Witness = env["uap.witness"]
    existing = Witness.search_read([("name", "=", row["name"])], ["id"])
    vals = {k: v for k, v in row.items() if v not in (None, "", False) or k == "name"}

    if existing:
        ids = [r["id"] for r in existing]
        Witness.write(ids, vals)
        return ids[0]
    else:
        return _to_id(Witness.create(vals))


def upsert_encounter(
    env,
    row: dict,
    source_ids: list[int],
    witness_ids: list[int],
    dry_run: bool = False,
) -> int | None:
    """Skapa eller uppdatera en uap.encounter. Returnerar Odoo-ID."""
    if dry_run:
        print(f"  [DRY] uap.encounter: {row['encounter_id']} — {row.get('title_en', '')[:60]}")
        return None

    Encounter = env["uap.encounter"]
    existing = Encounter.search_read([("encounter_id", "=", row["encounter_id"])], ["id"])

    vals = {k: v for k, v in row.items() if v not in (None, "", False) or k == "encounter_id"}
    if source_ids:
        vals["source_ids"] = [(6, 0, source_ids)]
    if witness_ids:
        vals["witness_ids"] = [(6, 0, witness_ids)]

    if existing:
        ids = [r["id"] for r in existing]
        Encounter.write(ids, vals)
        return ids[0]
    else:
        return _to_id(Encounter.create(vals))


def upsert_verification(env, row: dict, encounter_odoo_id: int, dry_run: bool = False) -> int | None:
    """Skapa en uap.verification-post. Returnerar Odoo-ID."""
    if dry_run:
        print(f"  [DRY] uap.verification: {row['name']}")
        return None

    Verification = env["uap.verification"]
    existing = Verification.search_read([
        ("name", "=", row["name"]),
        ("encounter_id", "=", encounter_odoo_id),
    ], ["id"])

    vals = {k: v for k, v in row.items() if v not in (None, "", False) or k == "name"}
    vals["encounter_id"] = encounter_odoo_id

    if existing:
        ids = [r["id"] for r in existing]
        Verification.write(ids, vals)
        return ids[0]
    else:
        return _to_id(Verification.create(vals))


def create_draft_encounter(env, data: dict) -> int | None:
    """Skapa ett utkast till uap.encounter från videoanalys. Returnerar Odoo-ID."""
    Encounter = env["uap.encounter"]
    vals = {k: v for k, v in data.items() if v not in (None, "", False)}
    return _to_id(Encounter.create(vals))


def get_model_counts(env) -> dict[str, int]:
    """Räkna poster per UAP-modell."""
    counts = {}
    for model in ["uap.encounter", "uap.source", "uap.witness", "uap.verification"]:
        try:
            counts[model] = env[model].search_count([])
        except Exception:
            counts[model] = -1
    return counts
