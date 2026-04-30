"""odoo_sync.py — Upsert-logik mot Odoo för UAP-modeller."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))


def get_env():
    from clio_odoo import connect
    return connect()


def upsert_source(env, row: dict, dry_run: bool = False) -> int | None:
    """Skapa eller uppdatera en uap.source. Returnerar Odoo-ID."""
    if dry_run:
        print(f"  [DRY] uap.source: {row['source_id']} — {row.get('name', '')}")
        return None

    Source = env["uap.source"]
    existing = Source.search([("source_id", "=", row["source_id"])])
    vals = {k: v for k, v in row.items() if v not in (None, "", False) or k == "name"}

    if existing:
        Source.write(existing, vals)
        return existing[0]
    else:
        return Source.create(vals)


def upsert_witness(env, row: dict, dry_run: bool = False) -> int | None:
    """Skapa eller uppdatera en uap.witness. Returnerar Odoo-ID."""
    if dry_run:
        print(f"  [DRY] uap.witness: {row['name']}")
        return None

    Witness = env["uap.witness"]
    existing = Witness.search([("name", "=", row["name"])])
    vals = {k: v for k, v in row.items() if v not in (None, "", False) or k == "name"}

    if existing:
        Witness.write(existing, vals)
        return existing[0]
    else:
        return Witness.create(vals)


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
    existing = Encounter.search([("encounter_id", "=", row["encounter_id"])])

    vals = {k: v for k, v in row.items() if v not in (None, "", False) or k == "encounter_id"}
    if source_ids:
        vals["source_ids"] = [(6, 0, source_ids)]
    if witness_ids:
        vals["witness_ids"] = [(6, 0, witness_ids)]

    if existing:
        Encounter.write(existing, vals)
        return existing[0]
    else:
        return Encounter.create(vals)


def upsert_verification(env, row: dict, encounter_odoo_id: int, dry_run: bool = False) -> int | None:
    """Skapa en uap.verification-post. Returnerar Odoo-ID."""
    if dry_run:
        print(f"  [DRY] uap.verification: {row['name']}")
        return None

    Verification = env["uap.verification"]
    existing = Verification.search([
        ("name", "=", row["name"]),
        ("encounter_id", "=", encounter_odoo_id),
    ])

    vals = {k: v for k, v in row.items() if v not in (None, "", False) or k == "name"}
    vals["encounter_id"] = encounter_odoo_id

    if existing:
        Verification.write(existing, vals)
        return existing[0]
    else:
        return Verification.create(vals)


def get_model_counts(env) -> dict[str, int]:
    """Räkna poster per UAP-modell."""
    counts = {}
    for model in ["uap.encounter", "uap.source", "uap.witness", "uap.verification"]:
        try:
            ids = env[model].search([])
            counts[model] = len(ids)
        except Exception:
            counts[model] = -1
    return counts
