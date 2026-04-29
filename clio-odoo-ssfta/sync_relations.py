"""
sync_relations.py — Skapar partner_multi_relation-typer och synkar
OrganizationRelations från SSFTA till Odoo res.partner.relation.

Relationstyper:
  ssf_distrikt  : SF → SDF       (2→4)
  ssf_forening  : SDF → Förening (4→5)
  ssf_gren      : Gren → Förening (13→5)

Körning:
    python sync_relations.py             # live
    python sync_relations.py --dry-run   # ingen skrivning
    python sync_relations.py --db ssf_t2
"""

from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import pymssql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

# ── Relationstyper ─────────────────────────────────────────────────────────────

RELATION_TYPES = [
    {
        "name":         "ssf_distrikt",
        "name_a":       "har distrikt",
        "name_b":       "tillhör förbund",
        "parent_types": {2},
        "child_types":  {4},
    },
    {
        "name":         "ssf_forening",
        "name_a":       "har förening",
        "name_b":       "tillhör distrikt",
        "parent_types": {4},
        "child_types":  {5},
    },
    {
        "name":         "ssf_gren",
        "name_a":       "bedriver gren",
        "name_b":       "bedrivs av förening",
        "parent_types": {13},
        "child_types":  {5},
    },
]


# ── SSFTA-hämtning ─────────────────────────────────────────────────────────────

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


def fetch_relations() -> list[dict]:
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT
            r.ParentId, r.ChildId,
            r.ParentOrgTypeId, r.ChildOrgTypeId,
            o_parent.rfid as parent_rfid,
            o_child.rfid  as child_rfid
        FROM OrganizationRelations r
        JOIN Organizations o_parent ON o_parent.ID = r.ParentId
        JOIN Organizations o_child  ON o_child.ID  = r.ChildId
        WHERE r.ParentOrgTypeId IN (2, 4, 13)
          AND r.ChildOrgTypeId  IN (4, 5)
          AND o_parent.rfid IS NOT NULL AND o_parent.rfid != ''
          AND o_child.rfid  IS NOT NULL AND o_child.rfid  != ''
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


# ── Odoo-hjälpare ──────────────────────────────────────────────────────────────

def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def _get_or_create_relation_type(env, defn: dict) -> int:
    RelType = env["res.partner.relation.type"]
    hits = RelType.search_read([("name", "=", defn["name_a"])], ["id"])
    if hits:
        return _to_int(hits[0]["id"])
    print("  Skapar relationstyp: " + defn["name_a"] + " / " + defn["name_b"])
    return _to_int(RelType.create({
        "name":         defn["name_a"],
        "name_inverse": defn["name_b"],
    }))


def build_type_map(relations: list[dict]) -> dict[tuple, str]:
    """(parent_type, child_type) → relationstyp-namn"""
    m = {}
    for rt in RELATION_TYPES:
        for pt in rt["parent_types"]:
            for ct in rt["child_types"]:
                m[(pt, ct)] = rt["name_a"]
    return m


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    print("Hämtar relationer från SSFTA...")
    relations = fetch_relations()
    print("  " + str(len(relations)) + " relationer hämtade.")

    print("Ansluter till Odoo...")
    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print("  Ansluten till " + env.db)

    # Skapa/hämta relationstyper
    type_id_map = {}  # name_a → Odoo type_id
    for defn in RELATION_TYPES:
        if args.dry_run:
            print("  [DRY] Relationstyp: " + defn["name_a"] + " / " + defn["name_b"])
            type_id_map[defn["name_a"]] = -1
        else:
            type_id_map[defn["name_a"]] = _get_or_create_relation_type(env, defn)

    # Bygg rfid → partner_id-karta (inkl arkiverade)
    print("Bygger partner-karta...")
    Partner = env["res.partner"]
    all_partners = Partner.search_read(
        [("active", "in", [True, False]), ("ref", "like", "ssfta-")],
        ["id", "ref"]
    )
    rfid_to_pid = {}
    for p in all_partners:
        ref = (p.get("ref") or "")
        if ref.startswith("ssfta-"):
            rfid = ref[len("ssfta-"):]
            rfid_to_pid[rfid.upper()] = _to_int(p["id"])
    print("  " + str(len(rfid_to_pid)) + " partners i kartan.")

    # Hämta befintliga relationer för dedup
    Relation = env["res.partner.relation"]
    existing_rels = Relation.search_read([], ["left_partner_id", "type_id", "right_partner_id"])
    existing_set = set()
    for r in existing_rels:
        left  = _to_int(r["left_partner_id"])
        rtype = _to_int(r["type_id"])
        right = _to_int(r["right_partner_id"])
        existing_set.add((left, rtype, right))
    print("  " + str(len(existing_set)) + " befintliga relationer.")

    # Typ-mapping (parent_type, child_type) → name_a
    key_to_name = {}
    for rt in RELATION_TYPES:
        for pt in rt["parent_types"]:
            for ct in rt["child_types"]:
                key_to_name[(pt, ct)] = rt["name_a"]

    created = skipped = missing = 0

    for rel in relations:
        type_key  = (rel["ParentOrgTypeId"], rel["ChildOrgTypeId"])
        type_name = key_to_name.get(type_key)
        if not type_name:
            skipped += 1
            continue

        parent_rfid = str(rel["parent_rfid"]).upper()
        child_rfid  = str(rel["child_rfid"]).upper()

        left_pid  = rfid_to_pid.get(parent_rfid)
        right_pid = rfid_to_pid.get(child_rfid)

        if not left_pid or not right_pid:
            missing += 1
            continue

        type_id = type_id_map.get(type_name, -1)
        key     = (left_pid, type_id, right_pid)

        if key in existing_set:
            skipped += 1
            continue

        if args.dry_run:
            print("  [DRY] " + type_name + ": " + str(parent_rfid[:8]) + "... → " + str(child_rfid[:8]) + "...")
            created += 1
            continue

        try:
            Relation.create({
                "left_partner_id":  left_pid,
                "type_id":          type_id,
                "right_partner_id": right_pid,
            })
            existing_set.add(key)
            created += 1
        except Exception as e:
            print("  FEL: " + str(e))
            skipped += 1

    print("\nKlar:")
    print("  " + str(created) + " relationer skapade")
    print("  " + str(skipped) + " hoppade över (befintliga eller okänd typ)")
    print("  " + str(missing) + " saknade partner i Odoo (rfid ej synkat)")
    if args.dry_run:
        print("  (--dry-run, ingen data skrevs)")


if __name__ == "__main__":
    main()
