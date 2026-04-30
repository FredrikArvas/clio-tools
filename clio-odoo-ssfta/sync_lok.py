"""
sync_lok.py — Synkar LOK-stödsdata (FeeReports + FeeReportValues) från SSFTA till Odoo.

Tabeller:
  FeeReports      (11 492 rader) → ssf.fee.report
  FeeReportValues (67 917 rader) → ssf.fee.report.value

Env-variabler (.env.ssfta + .env):
  SSFTA_MSSQL_*  → SQL Server (SSFTA)
  ODOO_SSF_DB    → Odoo-databasnamn (default "ssf")

Körning:
    python3 sync_lok.py              # full sync
    python3 sync_lok.py --dry-run    # ingen skrivning
    python3 sync_lok.py --skip-updates  # bara nya poster
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


# ── Sync-funktioner ────────────────────────────────────────────────────────────

def sync_fee_reports(env, dry_run: bool, skip_updates: bool) -> None:
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT ID, Competition, Reference,
               ReportDate, ReportAmount, PaidDate, PaidAmount
        FROM FeeReports
    """)
    rows_raw = cur.fetchall()
    conn.close()

    comp_map = {
        r["ssfta_id"]: r["id"]
        for r in env["ssf.competition"].search_read([], ["ssfta_id", "id"])
    }

    rows = []
    skipped = 0
    for r in rows_raw:
        comp_id = comp_map.get(r["Competition"])
        if not comp_id:
            skipped += 1
            continue
        rows.append({
            "ssfta_id":      r["ID"],
            "competition_id": comp_id,
            "reference":     r["Reference"] or "",
            "report_date":   _to_date(r["ReportDate"]),
            "report_amount": float(r["ReportAmount"] or 0),
            "paid_date":     _to_date(r["PaidDate"]),
            "paid_amount":   float(r["PaidAmount"] or 0),
        })

    c, u = _upsert(env["ssf.fee.report"], rows, dry_run=dry_run, skip_updates=skip_updates)
    print(f"  FeeReports:       {c} skapade, {u} uppdaterade  (hoppade: {skipped})")


def sync_fee_report_values(env, dry_run: bool, skip_updates: bool) -> None:
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("SELECT ID, FeeReport, District, Competitors FROM FeeReportValues")
    rows_raw = cur.fetchall()
    conn.close()

    report_map = {
        r["ssfta_id"]: r["id"]
        for r in env["ssf.fee.report"].search_read([], ["ssfta_id", "id"])
    }

    # Bygg district_map: Organizations.ID → res.partner.id via rfid
    district_map: dict[int, int] = {}
    conn2 = _get_conn()
    cur2 = conn2.cursor(as_dict=True)
    district_ssfta_ids = list({r["District"] for r in rows_raw if r["District"]})
    if district_ssfta_ids:
        placeholders = ",".join(str(i) for i in district_ssfta_ids)
        cur2.execute(f"SELECT ID, rfid FROM Organizations WHERE ID IN ({placeholders})")
        for row in cur2.fetchall():
            if row["rfid"]:
                partners = env["res.partner"].search_read(
                    [("ref", "=", f"ssfta-{row['rfid']}")], ["id"]
                )
                if partners:
                    district_map[row["ID"]] = partners[0]["id"]
    conn2.close()

    rows = []
    skipped = 0
    for r in rows_raw:
        report_id = report_map.get(r["FeeReport"])
        if not report_id:
            skipped += 1
            continue
        rows.append({
            "ssfta_id":      r["ID"],
            "fee_report_id": report_id,
            "district_id":   district_map.get(r["District"]) or False,
            "competitors":   r["Competitors"] or 0,
        })

    c, u = _upsert(env["ssf.fee.report.value"], rows, dry_run=dry_run, skip_updates=skip_updates)
    print(f"  FeeReportValues:  {c} skapade, {u} uppdaterade  (hoppade: {skipped})")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    cfg = _load_ssfta_env()

    parser = argparse.ArgumentParser(description="Synkar LOK-stödsdata SSFTA → Odoo")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None, help="Odoo-databasnamn (override ODOO_SSF_DB)")
    parser.add_argument("--skip-updates", action="store_true",
                        help="Hoppa över write() på befintliga poster")
    args = parser.parse_args()

    db = args.db or os.environ.get("ODOO_SSF_DB", "ssf")
    dr = args.dry_run
    su = args.skip_updates
    mode = "[DRY-RUN] " if dr else ""

    print(f"{mode}Synkar LOK-stödsdata SSFTA → Odoo ({db})")

    env = connect(db=db)

    print("FeeReports...")
    sync_fee_reports(env, dr, su)

    print("FeeReportValues...")
    sync_fee_report_values(env, dr, su)

    print(f"\nKlar.")
    if dr:
        print("  (--dry-run, ingen data skrevs)")
    if su:
        print("  (--skip-updates, befintliga poster ej uppdaterade)")


if __name__ == "__main__":
    main()
