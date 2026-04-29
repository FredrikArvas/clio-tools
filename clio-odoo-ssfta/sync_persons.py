"""
sync_persons.py — Synkar Persons från SSFTA till Odoo res.partner (kontaktpersoner).

Importerar 108 K aktiva personer med rfid.
Upsert-nyckel: ref = ssfta-person-{rfid}
Skapar i batchar om 200 för prestanda.

Efter upsert körs populate_ssfta_club_id() som sätter res.partner.ssfta_club_id
till personens primära förening (MIN-Organisation via PersonOrganiztion WHERE OrgType=5).

Körning:
    python sync_persons.py                    # live
    python sync_persons.py --dry-run
    python sync_persons.py --db ssf_t2
    python sync_persons.py --limit 500
    python sync_persons.py --skip-club-fields # hoppa over ssfta_club_id-steget
"""

from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import pymssql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

REF_PREFIX = "ssfta-person-"
PERSON_TAG = "SSFTA:Person"
BATCH_SIZE = 200


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


def fetch_persons(limit=None) -> list[dict]:
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor(as_dict=True)
    top = f"TOP {limit}" if limit else ""
    cur.execute(f"""
        SELECT {top}
            ID, Firstname, Lastname, Gender, Birthdate, rfid, Email
        FROM Persons
        WHERE IsDeleted = 0
          AND IsDead    = 0
          AND rfid IS NOT NULL AND rfid != ''
        ORDER BY ID
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


# ── Odoo-hjälpare ──────────────────────────────────────────────────────────────

def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def _get_or_create_tag(env, name: str) -> int:
    Cat = env["res.partner.category"]
    hits = Cat.search_read([("name", "=", name)], ["id"])
    return _to_int(hits[0]["id"]) if hits else _to_int(Cat.create({"name": name}))


def _s(val) -> str:
    return "" if val is None else str(val).strip()


def _build_name(row: dict) -> str:
    return (_s(row["Firstname"]) + " " + _s(row["Lastname"])).strip() or REF_PREFIX + _s(row["rfid"])[:8]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db",    default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-club-fields", action="store_true",
                        help="Hoppa over populate_ssfta_club_id-steget")
    args = parser.parse_args()

    print("Hämtar personer från SSFTA...")
    persons = fetch_persons(limit=args.limit)
    print(f"  {len(persons)} personer hämtade.")

    print("Ansluter till Odoo...")
    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print(f"  Ansluten till {env.db}")

    tag_id  = _get_or_create_tag(env, PERSON_TAG)
    Partner = env["res.partner"]

    # Hämta befintliga ssfta-person- refs
    print("Hämtar befintliga person-poster från Odoo...")
    existing = Partner.search_read(
        [("active", "in", [True, False]), ("ref", "like", REF_PREFIX)],
        ["id", "ref"]
    )
    existing_refs = {_s(r["ref"]): _to_int(r["id"]) for r in existing if r.get("ref")}
    print(f"  {len(existing_refs)} befintliga ssfta-person-poster.")

    to_create = []
    to_update = []   # (partner_id, vals)

    for row in persons:
        ref  = REF_PREFIX + _s(row["rfid"]).upper()
        name = _build_name(row)
        bd = row.get("Birthdate")
        birthdate = str(bd.date()) if bd else False
        email = _s(row.get("Email"))
        vals = {
            "ref":            ref,
            "name":           name,
            "is_company":     False,
            "active":         True,
            "category_id":    [(4, tag_id)],
        }
        if birthdate:
            vals["birthdate_date"] = birthdate
        if email:
            vals["email"] = email
        if ref in existing_refs:
            update_vals = {"name": name, "active": True}
            if birthdate:
                update_vals["birthdate_date"] = birthdate
            if email:
                update_vals["email"] = email
            to_update.append((existing_refs[ref], update_vals))
        else:
            to_create.append(vals)

    print(f"  {len(to_create)} att skapa, {len(to_update)} att uppdatera.")

    if args.dry_run:
        print(f"  Exempel (topp 5 nya):")
        for v in to_create[:5]:
            print(f"    {v['ref']} — {v['name']}")
        print("  (--dry-run, ingen data skrevs)")
        if not args.skip_club_fields:
            populate_ssfta_club_id(env, dry_run=True)
        return

    # ── Skapa i batchar ───────────────────────────────────────────────────────
    created = 0
    errors  = 0
    print("Skapar nya poster i batchar...")
    for i in range(0, len(to_create), BATCH_SIZE):
        batch = to_create[i:i + BATCH_SIZE]
        try:
            Partner.create(batch)
            created += len(batch)
        except Exception:
            # Fallback: en i taget för att isolera fel
            for vals in batch:
                try:
                    Partner.create(vals)
                    created += 1
                except Exception as e:
                    print(f"  FEL ({vals.get('ref','?')}): {e}")
                    errors += 1
        if created % 5000 == 0 and created > 0:
            print(f"  ...{created} skapade")

    # ── Uppdatera befintliga i batchar ────────────────────────────────────────
    updated = 0
    print("Uppdaterar befintliga poster...")
    ids_vals: dict[str, list] = {}
    for pid, vals in to_update:
        key = str(vals)
        if key not in ids_vals:
            ids_vals[key] = (vals, [])
        ids_vals[key][1].append(pid)

    for vals, ids in ids_vals.values():
        for i in range(0, len(ids), BATCH_SIZE):
            Partner.write(ids[i:i + BATCH_SIZE], vals)
            updated += len(ids[i:i + BATCH_SIZE])

    print(f"\nKlar:")
    print(f"  {created} skapade")
    print(f"  {updated} uppdaterade")
    print(f"  {errors}  fel")

    if not args.skip_club_fields:
        populate_ssfta_club_id(env, dry_run=args.dry_run)


# ── ssfta_club_id — populera primär förening ───────────────────────────────────

def populate_ssfta_club_id(env, dry_run: bool = False) -> None:
    """
    Sätter res.partner.ssfta_club_id till personens primära förening.
    Primär = lägsta Organization-ID i PersonOrganiztion WHERE OrgType=5 och rfid finns.
    """
    print("\nPopulerar ssfta_club_id...")
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor(as_dict=True)

    # person.rfid → primär org.rfid (MIN org-id bland föreningar med rfid)
    cur.execute("""
        SELECT p.rfid AS person_rfid, o.rfid AS org_rfid
        FROM (
            SELECT po.Person,
                   MIN(po.Organization) AS MinOrgId
            FROM PersonOrganiztion po
            JOIN Organizations o ON o.ID = po.Organization
            WHERE po.Person IS NOT NULL
              AND po.Organization IS NOT NULL
              AND o.OrganizationType = 5
              AND o.rfid IS NOT NULL AND o.rfid != ''
            GROUP BY po.Person
        ) sub
        JOIN Persons p ON p.ID = sub.Person
        JOIN Organizations o ON o.ID = sub.MinOrgId
        WHERE p.rfid IS NOT NULL AND p.rfid != ''
          AND p.IsDeleted = 0
          AND p.IsDead    = 0
    """)
    rows = cur.fetchall()
    conn.close()

    print(f"  {len(rows)} person→förening-kopplingar hämtade från SSFTA.")

    # Bygg Odoo-referenskarta — inkludera ssfta_sdf_id på clubs
    Partner = env["res.partner"]
    existing_orgs = Partner.search_read(
        [("active", "in", [True, False]), ("ref", "like", "ssfta-")],
        ["id", "ref", "ssfta_sdf_id"]
    )
    ref_to_pid  = {_s(r["ref"]): _to_int(r["id"]) for r in existing_orgs}
    # club partner_id → sdf partner_id (för att sätta ssfta_sdf_id på persons)
    club_to_sdf = {
        _to_int(r["id"]): _to_int(r["ssfta_sdf_id"][0])
        for r in existing_orgs
        if r.get("ssfta_sdf_id")
    }

    set_ok = skipped = 0
    # (person_pid, club_pid, sdf_pid)
    batch: list[tuple[int, int, int | None]] = []

    for row in rows:
        person_ref = "ssfta-person-" + _s(row["person_rfid"]).upper()
        club_ref   = "ssfta-" + _s(row["org_rfid"])
        person_pid = ref_to_pid.get(person_ref)
        club_pid   = ref_to_pid.get(club_ref)
        if not person_pid or not club_pid:
            skipped += 1
            continue
        sdf_pid = club_to_sdf.get(club_pid)
        batch.append((person_pid, club_pid, sdf_pid))
        set_ok += 1

    if not dry_run:
        print(f"  Skriver {set_ok} kopplingar...")
        for i in range(0, len(batch), 500):
            chunk = batch[i:i + 500]
            for person_pid, club_pid, sdf_pid in chunk:
                vals = {"ssfta_club_id": club_pid}
                if sdf_pid:
                    vals["ssfta_sdf_id"] = sdf_pid
                Partner.write([person_pid], vals)
            if (i + 500) % 5000 == 0:
                print(f"  ...{i + 500} skrivna")

    sdf_also = sum(1 for _, _, s in batch if s)
    print(f"  {set_ok} ssfta_club_id satta ({sdf_also} fick aven ssfta_sdf_id)")
    print(f"  {skipped} hoppade over (person eller forening saknas i Odoo)")
    if dry_run:
        print("  (--dry-run, ingen data skrevs)")


if __name__ == "__main__":
    main()
