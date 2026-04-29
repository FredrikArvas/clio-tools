"""
update_test_emails.py — Sätter {ID}@test.ssf på alla SSFTA-personer utan email
och skriver sedan email till Odoo res.partner via sync_persons-logiken.

Steg 1: UPDATE SSFTADB.Persons SET Email = '{ID}@test.ssf' WHERE Email IS NULL/tom
Steg 2: Skriv emails till res.partner i Odoo (batch-update)
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pymssql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

REF_PREFIX = "ssfta-person-"

def _load_ssfta_env():
    env_path = Path(__file__).parent.parent / ".env.ssfta"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    return {
        "host":     os.environ.get("SSFTA_MSSQL_HOST", "localhost"),
        "port":     int(os.environ.get("SSFTA_MSSQL_PORT", "1433")),
        "db":       os.environ.get("SSFTA_MSSQL_DB", "SSFTADB"),
        "user":     os.environ.get("SSFTA_MSSQL_USER", "sa"),
        "password": os.environ.get("SSFTA_MSSQL_PASSWORD", ""),
    }

def _s(val) -> str:
    return "" if val is None else str(val).strip()

def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def step1_update_ssfta():
    print("Steg 1: Sätter test-emails i SSFTADB...")
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor()
    cur.execute("""
        UPDATE Persons
        SET Email = CAST(ID AS VARCHAR(20)) + '@test.ssf'
        WHERE (Email IS NULL OR Email = '')
          AND IsDeleted = 0 AND IsDead = 0
          AND rfid IS NOT NULL AND rfid != ''
    """)
    conn.commit()
    updated = cur.rowcount
    print(f"  {updated} rader uppdaterade i SSFTADB")
    conn.close()


def step2_sync_emails_to_odoo(db=None):
    print("\nSteg 2: Hämtar rfid→email från SSFTADB...")
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT rfid, Email
        FROM Persons
        WHERE IsDeleted = 0 AND IsDead = 0
          AND rfid IS NOT NULL AND rfid != ''
          AND Email IS NOT NULL AND Email != ''
    """)
    rows = cur.fetchall()
    conn.close()
    print(f"  {len(rows)} persons med email hämtade från SSFTA.")

    rfid_to_email = {_s(r["rfid"]).upper(): _s(r["Email"]) for r in rows}

    print("Ansluter till Odoo...")
    env = connect(db=db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print(f"  Ansluten till {env.db}")

    Partner = env["res.partner"]

    print("Hämtar ssfta-person-partner utan email (eller med fel email)...")
    partners = Partner.search_read(
        [("ref", "like", REF_PREFIX), ("active", "in", [True, False])],
        ["id", "ref", "email"]
    )
    print(f"  {len(partners)} ssfta-person-partner hittade.")

    to_update: list[tuple[int, str]] = []
    for p in partners:
        ref = _s(p["ref"])
        rfid = ref.replace(REF_PREFIX, "").upper()
        email = rfid_to_email.get(rfid)
        current_email = _s(p.get("email"))
        if email and email != current_email:
            to_update.append((_to_int(p["id"]), email))

    print(f"  {len(to_update)} partner behöver email-uppdatering.")

    BATCH = 500
    updated = 0
    for i in range(0, len(to_update), BATCH):
        chunk = to_update[i:i + BATCH]
        for pid, email in chunk:
            Partner.write([pid], {"email": email})
        updated += len(chunk)
        if updated % 5000 == 0:
            print(f"  ...{updated} skrivna")

    print(f"\nKlar: {updated} emails skrivna till Odoo")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None)
    parser.add_argument("--skip-ssfta", action="store_true",
                        help="Hoppa Steg 1 (SSFTADB-update)")
    args = parser.parse_args()

    if not args.skip_ssfta:
        step1_update_ssfta()
    step2_sync_emails_to_odoo(db=args.db)
