"""
sync_functionaries.py — Sätter parent_id på funktionärer/anställda i Odoo.

Hämtar PersonIOLRoles med administrativa roller från SSFTA och sätter
parent_id = primär org på res.partner (person) i Odoo.

Körs EFTER sync_persons.py och sync_orgs.py.

Körning:
    python sync_functionaries.py             # live
    python sync_functionaries.py --dry-run
    python sync_functionaries.py --db ssf_t2
"""

from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import pymssql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

# Roller som innebär formellt uppdrag i föreningen (ej utövare)
ADMIN_ROLES = {
    "Ordförande", "Vice Ordförande", "Kassör", "Sekreterare",
    "Styrelseledamot", "Ledamot", "Klubbadministratör",
    "Huvudadministratör", "Förbundsadministratör", "Anställd",
    "Idrottsansvarig", "Utbildningsansvarig förening",
    "Ungdomsansvarig", "GS/VD/Kanslichef", "Valberedning",
    "Kontaktperson mot SSF", "Kontakt dataskydd",
    "Idrottsmedel ansvarig", "Administratör TA-system",
    "Admin utbildning", "Superadministratör utbildning",
    "Administratör Föreningsansökan", "Distriktskontakt Utb.",
    "Tävlingsledare", "Kommittéordförande", "Kommittéledamot",
}

BATCH_SIZE = 500


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


def fetch_functionaries() -> list[dict]:
    """Returnerar (person_rfid, org_rfid) för varje administrativ roll."""
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor(as_dict=True)
    placeholders = ",".join(["'" + r.replace("'", "''") + "'" for r in ADMIN_ROLES])
    cur.execute(f"""
        SELECT DISTINCT
            p.rfid  AS person_rfid,
            o.rfid  AS org_rfid,
            r.role
        FROM PersonIOLRoles r
        JOIN Persons       p ON p.ID = r.person
        JOIN Organizations o ON o.ID = r.organization
        WHERE r.role IN ({placeholders})
          AND p.rfid IS NOT NULL AND p.rfid != ''
          AND o.rfid IS NOT NULL AND o.rfid != ''
          AND p.IsDeleted = 0 AND p.IsDead = 0
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    print("Hämtar funktionärer från SSFTA...")
    rows = fetch_functionaries()
    print("  " + str(len(rows)) + " rader (person, org, roll).")

    # En person kan ha roller i flera orgar — välj primär org per person
    # (den org med lägst position i listan = första träffen)
    person_to_org: dict[str, str] = {}
    for row in rows:
        prfid = str(row["person_rfid"]).upper()
        orfid = str(row["org_rfid"]).upper()
        if prfid not in person_to_org:
            person_to_org[prfid] = orfid

    print("  " + str(len(person_to_org)) + " unika funktionärer.")

    print("Ansluter till Odoo...")
    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print("  Ansluten till " + env.db)

    Partner = env["res.partner"]

    # rfid-kartor
    org_partners = Partner.search_read(
        [("active", "in", [True, False]), ("is_company", "=", True),
         ("ref", "like", "ssfta-")],
        ["id", "ref"]
    )
    org_rfid_to_pid = {}
    for p in org_partners:
        ref = (p.get("ref") or "")
        if ref.startswith("ssfta-") and not ref.startswith("ssfta-person-"):
            org_rfid_to_pid[ref[len("ssfta-"):].upper()] = _to_int(p["id"])

    person_partners = Partner.search_read(
        [("active", "in", [True, False]), ("ref", "like", "ssfta-person-")],
        ["id", "ref", "parent_id"]
    )
    person_rfid_to_pid   = {}
    person_rfid_has_parent = {}
    for p in person_partners:
        ref = (p.get("ref") or "")
        if ref.startswith("ssfta-person-"):
            rfid = ref[len("ssfta-person-"):].upper()
            person_rfid_to_pid[rfid]     = _to_int(p["id"])
            person_rfid_has_parent[rfid] = bool(p.get("parent_id"))

    print("  " + str(len(org_rfid_to_pid)) + " org, " +
          str(len(person_rfid_to_pid)) + " person-partners.")

    # Bygg uppdateringslista: bara de som saknar parent_id
    to_update: dict[int, int] = {}  # person_pid → org_pid
    skipped = missing = 0

    for person_rfid, org_rfid in person_to_org.items():
        person_pid = person_rfid_to_pid.get(person_rfid)
        org_pid    = org_rfid_to_pid.get(org_rfid)

        if not person_pid or not org_pid:
            missing += 1
            continue

        if person_rfid_has_parent.get(person_rfid):
            skipped += 1
            continue

        to_update[person_pid] = org_pid

    print("  " + str(len(to_update)) + " att uppdatera, " +
          str(skipped) + " har redan parent_id, " + str(missing) + " saknar partner.")

    if args.dry_run:
        sample = list(to_update.items())[:5]
        for ppid, opid in sample:
            print("  [DRY] person=" + str(ppid) + " → parent_id=" + str(opid))
        print("  (--dry-run, ingen data skrevs)")
        return

    # Gruppera per org_pid för batch-write
    org_to_persons: dict[int, list] = {}
    for ppid, opid in to_update.items():
        org_to_persons.setdefault(opid, []).append(ppid)

    updated = errors = 0
    for org_pid, person_ids in org_to_persons.items():
        for i in range(0, len(person_ids), BATCH_SIZE):
            batch = person_ids[i:i + BATCH_SIZE]
            try:
                Partner.write(batch, {"parent_id": org_pid})
                updated += len(batch)
            except Exception as e:
                print("  FEL (org=" + str(org_pid) + "): " + str(e)[:80])
                errors += len(batch)

    print("\nKlar:")
    print("  " + str(updated) + " funktionärer fick parent_id")
    print("  " + str(skipped) + " hade redan parent_id")
    print("  " + str(missing) + " saknade partner")
    print("  " + str(errors)  + " fel")


if __name__ == "__main__":
    main()
