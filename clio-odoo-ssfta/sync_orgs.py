"""
sync_orgs.py — Synkar Organizations från SSFTA testdb till Odoo res.partner (company).

Upsert-prioritet:
  1. Befintlig post med ref = ssfta-{rfid}   (tidigare synkad)
  2. Befintlig post med ref = {Code}          (importerad från skidor.com-skrapning)
  3. Skapa ny post

När en skrapad post (ref=Code) hittas uppgraderas ref till ssfta-{rfid}.
Tagg: SSFTA:Org

Efter upsert körs populate_ssfta_sdf_id() som sätter res.partner.ssfta_sdf_id:
  - SDF-partners (OrgType=4): pekar på sig själva
  - Förening-partners (OrgType=5): pekar på sin SDF

Körning:
    python sync_orgs.py                   # live mot ssf-db
    python sync_orgs.py --dry-run         # ingen skrivning
    python sync_orgs.py --db ssf_t2       # annan Odoo-db
    python sync_orgs.py --limit 50        # bara 50 poster
    python sync_orgs.py --skip-sdf-fields # hoppa över ssfta_sdf_id-steget
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

REF_PREFIX = "ssfta-"
ORG_TAG    = "SSFTA:Org"

ORG_TYPE_MAP = {
    2:  "SF",
    4:  "SDF",
    5:  "Förening",
    11: "Region",
    13: "Gren/klass",
}


# ── SSFTA-hämtning ─────────────────────────────────────────────────────────────

def _load_ssfta_env() -> dict:
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


def fetch_organizations(limit: int | None = None) -> list[dict]:
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor(as_dict=True)
    sql = """
        SELECT
            ID, Code, OrgNumber, ShortName, FullName, DescribingName,
            Address, CoAddress, ZipCode, City,
            Phone, Mobile, Email, HomePage,
            OrganizationType, IsPassive, rfid
        FROM Organizations
        WHERE rfid IS NOT NULL AND rfid != ''
    """
    if limit:
        sql = sql.replace("SELECT", f"SELECT TOP {limit}")
    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return rows


# ── Odoo-hjälpare ──────────────────────────────────────────────────────────────

def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def _s(val) -> str:
    return "" if val is None else str(val).strip()


def _get_or_create_tag(env, name: str) -> int:
    Tag = env["res.partner.category"]
    hits = Tag.search_read([("name", "=", name)], ["id"])
    if hits:
        return _to_int(hits[0]["id"])
    return _to_int(Tag.create({"name": name}))


def _get_country_id(env, code: str = "SE") -> int | None:
    hits = env["res.country"].search_read([("code", "=", code)], ["id"])
    return _to_int(hits[0]["id"]) if hits else None


def _build_vals(org: dict, country_id: int | None, tag_id: int) -> dict:
    org_type = ORG_TYPE_MAP.get(org["OrganizationType"], "")
    vals = {
        "ref":        REF_PREFIX + _s(org["rfid"]),
        "name":       _s(org["FullName"]) or _s(org["ShortName"]),
        "is_company": True,
        "active":     not org["IsPassive"],
        "street":     _s(org["Address"]),
        "street2":    _s(org["CoAddress"]),
        "zip":        _s(org["ZipCode"]),
        "city":       _s(org["City"]),
        "phone":      _s(org["Phone"]),
        "mobile":     _s(org["Mobile"]),
        "email":      _s(org["Email"]),
        "website":          _s(org["HomePage"]),
        "company_registry": _s(org["OrgNumber"]),
        "comment":    "\n".join(filter(None, [
            "Kod: "  + _s(org["Code"]) if org["Code"] else "",
            "Typ: "  + org_type        if org_type else "",
        ])),
        "category_id": [(4, tag_id)],
    }
    if country_id:
        vals["country_id"] = country_id
    return {k: v for k, v in vals.items() if v != "" or k in ("is_company", "active", "category_id")}


# ── Huvud ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db",    default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-sdf-fields", action="store_true",
                        help="Hoppa över populate_ssfta_sdf_id-steget")
    args = parser.parse_args()

    print("Hämtar organisationer från SSFTA...")
    orgs = fetch_organizations(limit=args.limit)
    print(f"  {len(orgs)} organisationer hämtade.")

    print("Ansluter till Odoo...")
    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print(f"  Ansluten till {env.db}")

    tag_id     = _get_or_create_tag(env, ORG_TAG)
    country_id = _get_country_id(env)
    Partner    = env["res.partner"]

    # Bygg uppslagstabell: ref → partner_id
    # active_test=False via domän-trick: inkluderar arkiverade poster
    # så att passiva SSFTA-orgar inte dupliceras vid omsynk
    existing = Partner.search_read(
        [("active", "in", [True, False]), ("ref", "!=", False)],
        ["id", "ref", "active"]
    )
    existing_map = {_s(r["ref"]): _to_int(r["id"]) for r in existing if r.get("ref")}

    created = updated = linked = errors = 0

    for org in orgs:
        ssfta_ref = REF_PREFIX + _s(org["rfid"])
        code_ref  = _s(org["Code"])   # rfNumber från skidor.com

        try:
            vals = _build_vals(org, country_id, tag_id)

            # Hitta befintlig post
            partner_id = existing_map.get(ssfta_ref)
            is_linked  = False

            if partner_id is None and code_ref and code_ref in existing_map:
                # Skrapad post hittad — uppgradera ref
                partner_id = existing_map[code_ref]
                is_linked  = True

            if args.dry_run:
                if partner_id and is_linked:
                    print(f"  [DRY] LINK   {code_ref} → {ssfta_ref}  ({vals.get('name','?')})")
                    linked += 1
                elif partner_id:
                    print(f"  [DRY] UPDATE {ssfta_ref}  ({vals.get('name','?')})")
                    updated += 1
                else:
                    print(f"  [DRY] CREATE {ssfta_ref}  ({vals.get('name','?')})")
                    created += 1
                continue

            if partner_id:
                Partner.write([partner_id], vals)
                if is_linked:
                    linked += 1
                else:
                    updated += 1
            else:
                new_id = _to_int(Partner.create(vals))
                existing_map[ssfta_ref] = new_id
                created += 1

        except Exception as e:
            print(f"  FEL {ssfta_ref}: {e}")
            errors += 1

    print(f"\nKlar:")
    print(f"  {created} skapade")
    print(f"  {updated} uppdaterade")
    print(f"  {linked}  länkade (skidor.com-post uppgraderad till ssfta-ref)")
    print(f"  {errors}  fel")
    if args.dry_run:
        print("  (--dry-run, ingen data skrevs)")

    if not args.skip_sdf_fields:
        populate_ssfta_sdf_id(env, dry_run=args.dry_run)


# ── ssfta_sdf_id — populera SDF-koppling ───────────────────────────────────────

def populate_ssfta_sdf_id(env, dry_run: bool = False) -> None:
    """
    Sätter res.partner.ssfta_sdf_id:
      SDF-partners (OrgType=4): pekar på sig själva
      Förening-partners (OrgType=5): pekar på sin SDF (via OrganizationRelations)
    """
    print("\nPopulerar ssfta_sdf_id...")
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor(as_dict=True)

    cur.execute("""
        SELECT ID, OrganizationType, rfid
        FROM Organizations
        WHERE rfid IS NOT NULL AND rfid != ''
    """)
    all_orgs = cur.fetchall()

    ssfta_id_to_rfid = {o["ID"]: _s(o["rfid"]) for o in all_orgs}

    cur.execute("""
        SELECT ChildId, ParentId
        FROM OrganizationRelations
        WHERE ParentOrgTypeId = 4 AND ChildOrgTypeId = 5
    """)
    relations = cur.fetchall()
    conn.close()

    # SSFTA club-id → SDF rfid
    club_to_sdf_rfid: dict[int, str] = {}
    for rel in relations:
        sdf_rfid = ssfta_id_to_rfid.get(rel["ParentId"])
        if sdf_rfid:
            club_to_sdf_rfid[rel["ChildId"]] = sdf_rfid

    Partner = env["res.partner"]
    existing = Partner.search_read(
        [("active", "in", [True, False]), ("ref", "like", "ssfta-")],
        ["id", "ref"]
    )
    ref_to_partner_id = {_s(r["ref"]): _to_int(r["id"]) for r in existing}

    # SSFTA-org-id → Odoo partner_id
    ssfta_org_id_to_partner: dict[int, int] = {}
    for org in all_orgs:
        ref = REF_PREFIX + ssfta_id_to_rfid[org["ID"]]
        pid = ref_to_partner_id.get(ref)
        if pid:
            ssfta_org_id_to_partner[org["ID"]] = pid

    sdf_set = club_set = skipped = 0

    for org in all_orgs:
        partner_id = ssfta_org_id_to_partner.get(org["ID"])
        if partner_id is None:
            skipped += 1
            continue

        org_type = org["OrganizationType"]
        sdf_partner_id = None

        if org_type == 4:
            sdf_partner_id = partner_id
            sdf_set += 1
        elif org_type == 5:
            sdf_rfid = club_to_sdf_rfid.get(org["ID"])
            if sdf_rfid:
                sdf_partner_id = ref_to_partner_id.get(REF_PREFIX + sdf_rfid)
            if sdf_partner_id:
                club_set += 1
            else:
                skipped += 1
                continue
        else:
            skipped += 1
            continue

        if not dry_run:
            Partner.write([partner_id], {"ssfta_sdf_id": sdf_partner_id})

    print(f"  {sdf_set} SDF-partners pekade pa sig sjalva")
    print(f"  {club_set} foreningar fick SDF-koppling")
    print(f"  {skipped} hoppade over (okand typ eller saknad SDF-koppling)")
    if dry_run:
        print("  (--dry-run, ingen data skrevs)")


if __name__ == "__main__":
    main()
