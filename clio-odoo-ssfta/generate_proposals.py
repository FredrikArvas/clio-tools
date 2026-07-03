"""
generate_proposals.py — Genererar ssf.permission.proposal i Odoo från SSFTA-data.

Skapar ett behörighetsförslag (status=draft) per (person, organisation) baserat på:
  DEL 1: LoginPrivileges → SF-admin / SDF-admin
  DEL 2: PersonIOLRoles Klubbadministratör + Huvudadministratör → Klubbadmin

Befintliga proposals:
  - status=draft   → uppdateras med ny data
  - status=approved/assigned/revoked → rörs ej (human decision preserved)

Körning:
    python generate_proposals.py              # live mot ssf
    python generate_proposals.py --dry-run    # visa utan att skriva
    python generate_proposals.py --db ssf_t2  # annan Odoo-db
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

import pymssql
from dotenv import load_dotenv

sys.path.insert(0, str(Path.home() / "clio-tools"))
from clio_odoo import connect

# IOL-roller som ger ssf_club_admin
CLUB_ADMIN_ROLES = {"Klubbadministratör", "Huvudadministratör"}

ORGTYPE_MAP = {2: "sf", 4: "sdf", 5: "club"}

PRIVILEGE_FIELD_MAP = {
    "persons":      "perm_persons",
    "settings":     "perm_settings",
    "events":       "perm_events",
    "datatransfer": "perm_datatransfer",
    "payments":     "perm_payments",
}


# ------------------------------------------------------------------ #
# SSFTA-hämtning                                                       #
# ------------------------------------------------------------------ #

def _load_ssfta_env() -> dict:
    env_path = Path.home() / "clio-tools" / ".env.ssfta"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    return {
        "host":     os.environ.get("SSFTA_MSSQL_HOST", "localhost"),
        "port":     int(os.environ.get("SSFTA_MSSQL_PORT", "1433")),
        "db":       os.environ.get("SSFTA_MSSQL_DB", "SSFTADB"),
        "user":     os.environ.get("SSFTA_MSSQL_USER", "sa"),
        "password": os.environ.get("SSFTA_MSSQL_PASSWORD", ""),
    }


def _ssfta_conn():
    cfg = _load_ssfta_env()
    return pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )


def fetch_login_privileges() -> list[dict]:
    conn = _ssfta_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT lp.Login, lp.Privilege,
               o.rfid AS OrgRfid, o.OrganizationType AS OrgType,
               o.FullName AS OrgName
        FROM LoginPrivileges lp
        JOIN Organizations o ON o.ID = lp.Organization
        WHERE lp.IsRevoked = 0
          AND o.rfid IS NOT NULL AND o.rfid != ''
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_club_admins() -> list[dict]:
    conn = _ssfta_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT DISTINCT
               p.rfid  AS PersonRfid,
               o.rfid  AS OrgRfid,
               o.FullName AS OrgName,
               ior.role AS RoleName
        FROM PersonIOLRoles ior
        JOIN Persons p       ON p.ID = ior.person
        JOIN Organizations o ON o.ID = ior.organization
        WHERE ior.role IN (N'Klubbadministratör', N'Huvudadministratör')
          AND p.rfid  IS NOT NULL AND p.rfid  != ''
          AND o.rfid  IS NOT NULL AND o.rfid  != ''
          AND p.IsDeleted = 0 AND p.IsDead = 0
          AND o.OrganizationType = 5
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


# ------------------------------------------------------------------ #
# Datastruktur för merge: nyckel = (person_ref, org_ref)              #
# ------------------------------------------------------------------ #

def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def build_proposals(lp_rows: list[dict], ca_rows: list[dict]) -> dict:
    """
    Returnerar dict: (person_ref, org_ref) → proposal_data

    person_ref: "ssfta-person-{RFID}" (LoginPrivileges: login används som nyckel,
                men vi matchar mot res.users.login direkt i Odoo-fasen)
    org_ref:    "ssfta-{ORG_RFID}"

    För LoginPrivileges saknas person-rfid — nyckeln är (login, org_ref).
    Vi håller dem separata tills vi matchat mot Odoo.
    """
    # Format: key = (login_or_person_ref, org_ref)
    # value = dict med all samlad data
    merged: dict[tuple, dict] = {}

    # DEL 1 — LoginPrivileges
    for row in lp_rows:
        login    = _s(row["Login"])
        priv     = _s(row["Privilege"]).lower()
        org_type = row["OrgType"]
        org_rfid = _s(row["OrgRfid"])

        if org_type not in ORGTYPE_MAP:
            continue
        if priv not in PRIVILEGE_FIELD_MAP:
            continue

        key = (login, "ssfta-" + org_rfid)
        if key not in merged:
            merged[key] = {
                "login":        login,
                "person_ref":   None,    # okänt ännu
                "org_ref":      "ssfta-" + org_rfid,
                "org_type":     ORGTYPE_MAP[org_type],
                "org_name":     _s(row["OrgName"]),
                "iol_role_name": None,
                "source":       "login_privileges",
                "perm_persons":      False,
                "perm_settings":     False,
                "perm_events":       False,
                "perm_datatransfer": False,
                "perm_payments":     False,
            }
        merged[key][PRIVILEGE_FIELD_MAP[priv]] = True
        if merged[key]["source"] == "iol_role":
            merged[key]["source"] = "both"

    # DEL 2 — PersonIOLRoles
    for row in ca_rows:
        person_rfid = _s(row["PersonRfid"]).upper()
        org_rfid    = _s(row["OrgRfid"])
        role_name   = _s(row["RoleName"])

        person_ref = "ssfta-person-" + person_rfid
        key = (person_ref, "ssfta-" + org_rfid)

        if key not in merged:
            merged[key] = {
                "login":        None,
                "person_ref":   person_ref,
                "org_ref":      "ssfta-" + org_rfid,
                "org_type":     "club",
                "org_name":     _s(row["OrgName"]),
                "iol_role_name": role_name,
                "source":       "iol_role",
                "perm_persons":      True,
                "perm_settings":     False,
                "perm_events":       False,
                "perm_datatransfer": False,
                "perm_payments":     False,
            }
        else:
            merged[key]["iol_role_name"] = role_name
            merged[key]["source"] = "both"
            merged[key]["perm_persons"] = True

    return merged


# ------------------------------------------------------------------ #
# Odoo-skrivning                                                       #
# ------------------------------------------------------------------ #

def sync_to_odoo(env, proposals: dict, dry_run: bool) -> None:
    Partner  = env["res.partner"]
    Proposal = env["ssf.permission.proposal"]

    # Ladda ref → partner_id (org-partners)
    org_partners = {
        _s(p["ref"]): _to_int(p["id"])
        for p in Partner.search_read(
            [("ref", "like", "ssfta-"), ("is_company", "=", True)],
            ["id", "ref"]
        )
        if p.get("ref")
    }

    # Ladda ref → partner_id + email (person-partners)
    person_partners = {
        _s(p["ref"]): {"id": _to_int(p["id"]), "email": _s(p.get("email") or "")}
        for p in Partner.search_read(
            [("ref", "like", "ssfta-person-"), ("is_company", "=", False)],
            ["id", "ref", "email"]
        )
        if p.get("ref")
    }

    # login → partner via email (för LoginPrivileges utan person_ref)
    email_to_partner = {
        v["email"]: v["id"]
        for v in person_partners.values()
        if v["email"]
    }

    # Befintliga proposals: (person_id, org_id) → {id, status}
    existing_proposals = {
        (_to_int(r["person_id"]), _to_int(r["organization_id"])): {
            "id": _to_int(r["id"]), "status": r["status"]
        }
        for r in Proposal.search_read([], ["id", "person_id", "organization_id", "status"])
    }

    stats = {"created": 0, "updated": 0, "skipped_protected": 0,
             "skipped_no_person": 0, "skipped_no_org": 0}

    for (key_login_or_ref, org_ref), data in proposals.items():
        # Hitta org-partner
        org_id = org_partners.get(data["org_ref"])
        if not org_id:
            stats["skipped_no_org"] += 1
            continue

        # Hitta person-partner
        person_id = None
        if data["person_ref"]:
            pp = person_partners.get(data["person_ref"])
            person_id = pp["id"] if pp else None
        elif data["login"]:
            person_id = email_to_partner.get(data["login"])

        if not person_id:
            stats["skipped_no_person"] += 1
            continue

        vals = {
            "person_id":       person_id,
            "organization_id": org_id,
            "org_type":        data["org_type"],
            "iol_role_name":   data["iol_role_name"] or "",
            "source":          data["source"],
            "perm_persons":      data["perm_persons"],
            "perm_settings":     data["perm_settings"],
            "perm_events":       data["perm_events"],
            "perm_datatransfer": data["perm_datatransfer"],
            "perm_payments":     data["perm_payments"],
        }

        existing = existing_proposals.get((person_id, org_id))

        if existing:
            if existing["status"] in ("approved", "assigned", "revoked"):
                # Mänskligt beslut — rör ej
                stats["skipped_protected"] += 1
                continue
            # Uppdatera draft
            if dry_run:
                print(f"  [DRY UPDATE] person={person_id} org={org_id} "
                      f"org_type={data['org_type']} source={data['source']}")
            else:
                Proposal.write([existing["id"]], vals)
            stats["updated"] += 1
        else:
            # Skapa ny som draft
            vals["status"] = "draft"
            if dry_run:
                print(f"  [DRY CREATE] person={person_id} org={org_id} "
                      f"org_type={data['org_type']} role={data['iol_role_name']} "
                      f"source={data['source']}")
            else:
                Proposal.create(vals)
            stats["created"] += 1

    print(f"\n  Skapade:             {stats['created']}")
    print(f"  Uppdaterade (draft): {stats['updated']}")
    print(f"  Skyddade (approved+): {stats['skipped_protected']}")
    print(f"  Saknar person-match: {stats['skipped_no_person']}")
    print(f"  Saknar org-match:    {stats['skipped_no_org']}")


# ------------------------------------------------------------------ #
# Main                                                                 #
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(description="Generera SSF behörighetsförslag i Odoo")
    parser.add_argument("--dry-run", action="store_true", help="Visa ändringar utan att skriva")
    parser.add_argument("--db", default=None, help="Odoo-databas (default: ssf)")
    args = parser.parse_args()

    print("Ansluter till Odoo...")
    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print(f"  Ansluten till {env.db}")

    print("\nHämtar LoginPrivileges från SSFTA...")
    lp_rows = fetch_login_privileges()
    print(f"  {len(lp_rows)} aktiva LoginPrivileges")

    print("\nHämtar Klubb- och Huvudadministratörer från SSFTA...")
    ca_rows = fetch_club_admins()
    print(f"  {len(ca_rows)} KlubbAdmin/HuvudAdmin-poster")

    print("\nMergar till proposals per (person, org)...")
    proposals = build_proposals(lp_rows, ca_rows)
    print(f"  {len(proposals)} unika (person, org)-par")

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Synkar till Odoo...")
    sync_to_odoo(env, proposals, dry_run=args.dry_run)

    if args.dry_run:
        print("\n(--dry-run, inga ändringar skrevs)")
    else:
        print("\nKlar.")


if __name__ == "__main__":
    main()
