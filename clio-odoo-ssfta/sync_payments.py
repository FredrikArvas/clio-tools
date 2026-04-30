"""
sync_payments.py — Synkar betalningsdata (Payments + PaymentEntry) från SSFTA till Odoo.

Tabeller:
  Payments      (17 580 rader) → ssf.payment
  PaymentEntry  (17 456 rader) → ssf.payment.entry

Env-variabler (.env.ssfta + .env):
  SSFTA_MSSQL_*  → SQL Server (SSFTA)
  ODOO_SSF_DB    → Odoo-databasnamn (default "ssf")

Körning:
    python3 sync_payments.py              # full sync
    python3 sync_payments.py --dry-run    # ingen skrivning
    python3 sync_payments.py --skip-updates  # bara nya poster
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


def _build_org_map(env, org_ids: list[int]) -> dict[int, int]:
    """Organizations.ID → res.partner.id via rfid-uppslag i SSFTA."""
    if not org_ids:
        return {}
    org_map: dict[int, int] = {}
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    placeholders = ",".join(str(i) for i in org_ids)
    cur.execute(f"SELECT ID, rfid FROM Organizations WHERE ID IN ({placeholders})")
    for row in cur.fetchall():
        if row["rfid"]:
            partners = env["res.partner"].search_read(
                [("ref", "=", f"ssfta-{row['rfid']}")], ["id"]
            )
            if partners:
                org_map[row["ID"]] = partners[0]["id"]
    conn.close()
    return org_map


# ── Sync-funktioner ────────────────────────────────────────────────────────────

def sync_payments(env, dry_run: bool, skip_updates: bool) -> None:
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT ID, Organization, Event, OrderID, Date, Amount, Status
        FROM Payments
    """)
    rows_raw = cur.fetchall()
    conn.close()

    # Bygg org_map: Organizations.ID → res.partner.id via rfid
    distinct_org_ids = list({r["Organization"] for r in rows_raw if r["Organization"]})
    org_map = _build_org_map(env, distinct_org_ids)

    # Bygg event_map: ssf.event.ssfta_id → ssf.event.id
    event_map = {
        r["ssfta_id"]: r["id"]
        for r in env["ssf.event"].search_read([], ["ssfta_id", "id"])
    }

    rows = []
    skipped = 0
    for r in rows_raw:
        org_id = org_map.get(r["Organization"])
        if not org_id:
            skipped += 1
            continue
        rows.append({
            "ssfta_id":        r["ID"],
            "organization_id": org_id,
            "event_id":        event_map.get(r["Event"]) or False,
            "order_id":        r["OrderID"] or "",
            "date":            _to_date(r["Date"]),
            "amount":          float(r["Amount"] or 0),
            "status":          r["Status"] or "",
        })

    c, u = _upsert(env["ssf.payment"], rows, dry_run=dry_run, skip_updates=skip_updates)
    print(f"  Payments:      {c} skapade, {u} uppdaterade  (hoppade: {skipped})")


def sync_payment_entries(env, dry_run: bool, skip_updates: bool) -> None:
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("SELECT ID, Payment, Entry, TeamEntry FROM PaymentEntry")
    rows_raw = cur.fetchall()
    conn.close()

    # Bygg payment_map
    payment_map = {
        r["ssfta_id"]: r["id"]
        for r in env["ssf.payment"].search_read([], ["ssfta_id", "id"])
    }

    # Bygg entry_map för bara de Entry-IDs som faktiskt används
    distinct_entry_ids = list({r["Entry"] for r in rows_raw if r["Entry"]})
    entry_map: dict[int, int] = {}
    for i in range(0, len(distinct_entry_ids), BATCH):
        chunk = distinct_entry_ids[i:i + BATCH]
        for rec in env["ssf.entry"].search_read(
            [("ssfta_id", "in", chunk)], ["ssfta_id", "id"]
        ):
            entry_map[rec["ssfta_id"]] = rec["id"]

    rows = []
    skipped = 0
    for r in rows_raw:
        payment_id = payment_map.get(r["Payment"])
        if not payment_id:
            skipped += 1
            continue
        rows.append({
            "ssfta_id":   r["ID"],
            "payment_id": payment_id,
            "entry_id":   entry_map.get(r["Entry"]) or False,
            "team_entry": r["TeamEntry"] or 0,
        })

    c, u = _upsert(env["ssf.payment.entry"], rows, dry_run=dry_run, skip_updates=skip_updates)
    print(f"  PaymentEntry:  {c} skapade, {u} uppdaterade  (hoppade: {skipped})")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    _load_ssfta_env()

    parser = argparse.ArgumentParser(description="Synkar betalningsdata SSFTA → Odoo")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None, help="Odoo-databasnamn (override ODOO_SSF_DB)")
    parser.add_argument("--skip-updates", action="store_true",
                        help="Hoppa över write() på befintliga poster")
    args = parser.parse_args()

    db = args.db or os.environ.get("ODOO_SSF_DB", "ssf")
    dr = args.dry_run
    su = args.skip_updates
    mode = "[DRY-RUN] " if dr else ""

    print(f"{mode}Synkar betalningsdata SSFTA → Odoo ({db})")

    env = connect(db=db)

    print("Payments...")
    sync_payments(env, dr, su)

    print("PaymentEntry...")
    sync_payment_entries(env, dr, su)

    print(f"\nKlar.")
    if dr:
        print("  (--dry-run, ingen data skrevs)")
    if su:
        print("  (--skip-updates, befintliga poster ej uppdaterade)")


if __name__ == "__main__":
    main()
