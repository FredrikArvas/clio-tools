"""
sync_memberships.py — Synkar PersonOrganiztion från SSFTA till Odoo
                      res.partner.relation (relationstyp ssf_member).

Skapar relationstypen om den saknas:
  "är utövare i" (person → org) / "har utövare" (org → person)

Körning:
    python sync_memberships.py             # live
    python sync_memberships.py --dry-run
    python sync_memberships.py --db ssf_t2
"""

from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import pymssql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

RELATION_NAME_A = "har utövare"
RELATION_NAME_B = "är utövare i"
BATCH_SIZE      = 500


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


def fetch_memberships() -> list[dict]:
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT
            p.rfid  AS person_rfid,
            o.rfid  AS org_rfid
        FROM PersonOrganiztion po
        JOIN Persons       p ON p.ID = po.Person
        JOIN Organizations o ON o.ID = po.Organization
        WHERE p.rfid  IS NOT NULL AND p.rfid  != ''
          AND o.rfid  IS NOT NULL AND o.rfid  != ''
          AND p.IsDeleted = 0
          AND p.IsDead    = 0
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def _to_int(val) -> int:
    if isinstance(val, (list, tuple)):
        return int(val[0])
    return val.id if hasattr(val, "id") else int(val)


def _get_or_create_relation_type(env) -> int:
    RelType = env["res.partner.relation.type"]
    hits = RelType.search_read([("name", "=", RELATION_NAME_A)], ["id"])
    if hits:
        return _to_int(hits[0]["id"])
    print("  Skapar relationstyp: " + RELATION_NAME_A + " / " + RELATION_NAME_B)
    return _to_int(RelType.create({
        "name":         RELATION_NAME_A,
        "name_inverse": RELATION_NAME_B,
    }))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    print("Hämtar PersonOrganiztion från SSFTA...")
    rows = fetch_memberships()
    print("  " + str(len(rows)) + " rader hämtade.")

    print("Ansluter till Odoo...")
    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print("  Ansluten till " + env.db)

    if args.dry_run:
        type_id = -1
        print("  [DRY] Relationstyp: " + RELATION_NAME_A + " / " + RELATION_NAME_B)
    else:
        type_id = _get_or_create_relation_type(env)

    # Bygg rfid→partner_id-kartor
    print("Bygger partner-kartor...")
    Partner = env["res.partner"]

    org_partners = Partner.search_read(
        [("active", "in", [True, False]), ("ref", "like", "ssfta-"),
         ("is_company", "=", True)],
        ["id", "ref"]
    )
    org_rfid_to_pid = {}
    for p in org_partners:
        ref = (p.get("ref") or "")
        if ref.startswith("ssfta-") and not ref.startswith("ssfta-person-"):
            org_rfid_to_pid[ref[len("ssfta-"):].upper()] = _to_int(p["id"])

    person_partners = Partner.search_read(
        [("active", "in", [True, False]), ("ref", "like", "ssfta-person-")],
        ["id", "ref"]
    )
    person_rfid_to_pid = {}
    for p in person_partners:
        ref = (p.get("ref") or "")
        if ref.startswith("ssfta-person-"):
            person_rfid_to_pid[ref[len("ssfta-person-"):].upper()] = _to_int(p["id"])

    print("  " + str(len(org_rfid_to_pid)) + " org-partners, " +
          str(len(person_rfid_to_pid)) + " person-partners.")

    # Hämta befintliga relationer av denna typ för dedup
    if not args.dry_run:
        print("Hämtar befintliga ssf_member-relationer...")
        Relation = env["res.partner.relation"]
        existing = Relation.search_read(
            [("type_id", "=", type_id)],
            ["left_partner_id", "right_partner_id"]
        )
        existing_set = set()
        for r in existing:
            existing_set.add((_to_int(r["left_partner_id"]), _to_int(r["right_partner_id"])))
        print("  " + str(len(existing_set)) + " befintliga.")
    else:
        existing_set = set()

    # Bygg lista att skapa
    to_create = []
    missing = skipped = 0

    for row in rows:
        org_rfid    = str(row["org_rfid"]).upper()
        person_rfid = str(row["person_rfid"]).upper()

        left_pid  = org_rfid_to_pid.get(org_rfid)
        right_pid = person_rfid_to_pid.get(person_rfid)

        if not left_pid or not right_pid:
            missing += 1
            continue

        key = (left_pid, right_pid)
        if key in existing_set:
            skipped += 1
            continue

        to_create.append({
            "left_partner_id":  left_pid,
            "type_id":          type_id,
            "right_partner_id": right_pid,
        })
        existing_set.add(key)

    print("  " + str(len(to_create)) + " att skapa, " +
          str(skipped) + " dubblett, " + str(missing) + " saknar partner.")

    if args.dry_run:
        print("  Exempel (topp 3):")
        for v in to_create[:3]:
            print("  [DRY] org=" + str(v["left_partner_id"]) +
                  " → person=" + str(v["right_partner_id"]))
        print("  (--dry-run, ingen data skrevs)")
        return

    # Skapa i batchar
    Relation = env["res.partner.relation"]
    created = errors = 0
    print("Skapar relationer i batchar...")
    for i in range(0, len(to_create), BATCH_SIZE):
        batch = to_create[i:i + BATCH_SIZE]
        try:
            Relation.create(batch)
            created += len(batch)
        except Exception:
            for vals in batch:
                try:
                    Relation.create(vals)
                    created += 1
                except Exception as e:
                    print("  FEL: " + str(e)[:80])
                    errors += 1
        if created % 50000 == 0 and created > 0:
            print("  ..." + str(created) + " skapade")

    print("\nKlar:")
    print("  " + str(created) + " relationer skapade")
    print("  " + str(skipped) + " dubblett (hoppade)")
    print("  " + str(missing) + " saknade partner")
    print("  " + str(errors)  + " fel")


if __name__ == "__main__":
    main()
