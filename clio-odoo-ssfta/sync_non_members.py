"""
sync_non_members.py — Synkar NonMembers (motionärer) från SSFTA till Odoo.

Tabell:
  NonMembers  (31 462 rader) → ssf.non.member

OBS: PersonalNumber synkas inte — PII.

Env-variabler (.env.ssfta + .env):
  SSFTA_MSSQL_*  → SQL Server (SSFTA)
  ODOO_SSF_DB    → Odoo-databasnamn (default "ssf")

Körning:
    python3 sync_non_members.py              # full sync
    python3 sync_non_members.py --dry-run    # ingen skrivning
    python3 sync_non_members.py --skip-updates
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pymssql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

BATCH = 500

GENDER_MAP = {"M": "M", "F": "F", "W": "F"}  # W = Women, alias för F


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_ssfta_env() -> dict:
    env_path = Path(__file__).parent.parent / ".env.ssfta"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
    return {
        "host": os.environ.get("SSFTA_MSSQL_HOST", "localhost"),
        "port": int(os.environ.get("SSFTA_MSSQL_PORT", "1433")),
        "db": os.environ.get("SSFTA_MSSQL_DB", "SSFTADB"),
        "user": os.environ.get("SSFTA_MSSQL_USER", "sa"),
        "password": os.environ.get("SSFTA_MSSQL_PASSWORD", ""),
    }


def _get_conn():
    cfg = _load_ssfta_env()
    return pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8",
    )


def _upsert(Model, rows: list[dict], key: str = "ssfta_id",
            dry_run: bool = False, skip_updates: bool = False) -> tuple[int, int]:
    created = updated = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        ids = [r[key] for r in batch]
        existing = {
            r[key]: r["id"]
            for r in Model.search_read([[key, "in", ids]], [key, "id"])
        }
        to_create = [r for r in batch if r[key] not in existing]
        to_update = [(existing[r[key]], r) for r in batch if r[key] in existing]

        if to_create and not dry_run:
            Model.create(to_create)
        created += len(to_create)

        for odoo_id, row in to_update:
            if not dry_run and not skip_updates:
                Model.browse(odoo_id).write(row)
        updated += len(to_update)

    return created, updated


def _to_date(val):
    if val is None:
        return False
    if hasattr(val, "date"):
        return str(val.date())
    return str(val)


# ── Sync ───────────────────────────────────────────────────────────────────────

def sync_non_members(env, dry_run: bool, skip_updates: bool) -> None:
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT ID, Firstname, Lastname, Gender, Birthdate, Nationality, CoAddress
        FROM NonMembers
    """)
    rows_raw = cur.fetchall()
    conn.close()

    rows = []
    for r in rows_raw:
        gender_raw = (r["Gender"] or "").strip().upper()
        gender = GENDER_MAP.get(gender_raw, "X")
        rows.append({
            "ssfta_id":    r["ID"],
            "firstname":   (r["Firstname"] or "").strip(),
            "lastname":    (r["Lastname"] or "").strip(),
            "gender":      gender,
            "birthdate":   _to_date(r["Birthdate"]),
            "nationality": (r["Nationality"] or "").strip(),
            "co_address":  (r["CoAddress"] or "").strip(),
        })

    c, u = _upsert(env["ssf.non.member"], rows, dry_run=dry_run, skip_updates=skip_updates)
    print(f"  NonMembers:  {c} skapade, {u} uppdaterade")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    _load_ssfta_env()

    parser = argparse.ArgumentParser(description="Synkar NonMembers SSFTA → Odoo")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None, help="Odoo-databasnamn (override ODOO_SSF_DB)")
    parser.add_argument("--skip-updates", action="store_true",
                        help="Hoppa över write() på befintliga poster")
    args = parser.parse_args()

    db = args.db or os.environ.get("ODOO_SSF_DB", "ssf")
    dr = args.dry_run
    su = args.skip_updates
    mode = "[DRY-RUN] " if dr else ""

    print(f"{mode}Synkar NonMembers SSFTA → Odoo ({db})")

    env = connect(db=db)

    print("NonMembers...")
    sync_non_members(env, dr, su)

    print(f"\nKlar.")
    if dr:
        print("  (--dry-run, ingen data skrevs)")
    if su:
        print("  (--skip-updates, befintliga poster ej uppdaterade)")


if __name__ == "__main__":
    main()
