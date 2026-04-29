"""
assign_groups.py — Tilldelar SSF-behörighetsgrupper i Odoo baserat på SSFTA-data.

DEL 1: LoginPrivileges → ssf_sf_admin / ssf_sdf_admin
  - OrgType=2 + Privilege persons/settings → ssf_sf_admin
  - OrgType=4 + Privilege events/datatransfer → ssf_sdf_admin
  - Sätter ssfta_managed_partner_id på res.users

DEL 2: PersonIOLRoles Klubbadministratör → ssf_club_admin
  - person.rfid → res.partner.email → res.users.login
  - Sätter ssfta_managed_partner_id = föreningens partner

Alla tilldelade users: portal → intern (base.group_user).

Körning:
    python assign_groups.py              # live mot ssf-db
    python assign_groups.py --dry-run    # visa ändringar utan att skriva
    python assign_groups.py --db ssf_t2  # annan Odoo-db
    python assign_groups.py --reset      # ta bort alla SSF-grupper (admin-verktyg)
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

# Privilege → grupp-xml-id
PRIVILEGE_GROUP_MAP = {
    # OrgType=2 (SF)
    (2, "persons"):      "group_ssf_sf_admin",
    (2, "settings"):     "group_ssf_sf_admin",
    (2, "events"):       "group_ssf_sf_admin",
    (2, "payments"):     None,  # ej mappad i v1
    (2, "datatransfer"): "group_ssf_sf_admin",
    # OrgType=4 (SDF)
    (4, "events"):       "group_ssf_sdf_admin",
    (4, "datatransfer"): "group_ssf_sdf_admin",
    (4, "persons"):      "group_ssf_sdf_admin",
    (4, "settings"):     "group_ssf_sdf_admin",
    (4, "payments"):     None,
}

MODULE = "ssf_crm_access"
KLUBBADMIN_ROLE = "Klubbadministratör"


# ── SSFTA ──────────────────────────────────────────────────────────────────────

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
               o.ID AS OrgId, o.rfid AS OrgRfid, o.OrganizationType AS OrgType,
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
    """
    Returnerar PersonIOLRoles Klubbadministratör med person.rfid och org.rfid.
    Email-matchning sker via Odoo res.partner (syftar på prod-data eller test-emails).
    """
    conn = _ssfta_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT DISTINCT
               p.rfid  AS PersonRfid,
               o.rfid  AS OrgRfid,
               o.FullName AS OrgName
        FROM PersonIOLRoles ior
        JOIN Persons p       ON p.ID = ior.person
        JOIN Organizations o ON o.ID = ior.organization
        WHERE ior.role LIKE %s
          AND p.rfid  IS NOT NULL AND p.rfid  != ''
          AND o.rfid  IS NOT NULL AND o.rfid  != ''
          AND p.IsDeleted = 0 AND p.IsDead = 0
          AND o.OrganizationType = 5
    """, ("%" + KLUBBADMIN_ROLE + "%",))
    rows = cur.fetchall()
    conn.close()
    return rows


# ── Odoo-hjälpare ──────────────────────────────────────────────────────────────

def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def _s(val) -> str:
    return "" if val is None else str(val).strip()


def _get_group_id(env, module: str, name: str) -> int | None:
    IrData = env["ir.model.data"]
    hits = IrData.search_read(
        [("module", "=", module), ("name", "=", name)],
        ["res_id"]
    )
    return _to_int(hits[0]["res_id"]) if hits else None


def _build_group_cache(env) -> dict[str, int]:
    """Returnerar {xml_name: group_id} för alla SSF-grupper + bas-grupper."""
    cache = {}
    for name in ("group_ssf_sf_admin", "group_ssf_sdf_admin", "group_ssf_club_admin"):
        gid = _get_group_id(env, MODULE, name)
        if gid:
            cache[name] = gid
        else:
            print(f"  VARNING: grupp {MODULE}.{name} hittades inte i Odoo")
    for name in ("group_portal", "group_user"):
        gid = _get_group_id(env, "base", name)
        if gid:
            cache[name] = gid
    return cache


# ── DEL 1: LoginPrivileges ─────────────────────────────────────────────────────

def assign_from_login_privileges(env, groups: dict, dry_run: bool) -> dict:
    print("\n── DEL 1: LoginPrivileges → SF/SDF-admin ──")
    privs = fetch_login_privileges()
    print(f"  {len(privs)} aktiva LoginPrivileges hämtade.")

    Partner = env["res.partner"]
    User    = env["res.users"]

    # Bygg partner-karta: "ssfta-{rfid}" → partner_id
    org_partners = Partner.search_read(
        [("ref", "like", "ssfta-"), ("is_company", "=", True)],
        ["id", "ref"]
    )
    ref_to_partner = {"ssfta-" + _s(p["ref"]).replace("ssfta-", ""): _to_int(p["id"])
                      for p in org_partners if p.get("ref")}
    # Enklare: direkt ref → id
    ref_to_partner = {_s(p["ref"]): _to_int(p["id"]) for p in org_partners if p.get("ref")}

    # Bygg user-karta: login → user_id
    users = User.search_read([("active", "in", [True, False])], ["id", "login", "groups_id"])
    login_to_user = {_s(u["login"]): u for u in users}

    stats = {"assigned": 0, "skipped_no_user": 0, "skipped_no_partner": 0,
             "skipped_unmapped": 0, "already_set": 0}

    # login → {group_name, partner_id} — en user kan ha flera privileges
    pending: dict[str, dict] = {}

    for row in privs:
        login     = _s(row["Login"])
        privilege = _s(row["Privilege"]).lower()
        org_type  = row["OrgType"]
        org_rfid  = _s(row["OrgRfid"])

        group_name = PRIVILEGE_GROUP_MAP.get((org_type, privilege))
        if group_name is None:
            print(f"  [WARN] Omappad: login={login} OrgType={org_type} privilege={privilege}")
            stats["skipped_unmapped"] += 1
            continue

        partner_ref = "ssfta-" + org_rfid
        partner_id  = ref_to_partner.get(partner_ref)
        if not partner_id:
            stats["skipped_no_partner"] += 1
            continue

        if login not in login_to_user:
            stats["skipped_no_user"] += 1
            continue

        if login not in pending:
            pending[login] = {"groups": set(), "partner_id": partner_id,
                              "org_name": _s(row["OrgName"])}
        pending[login]["groups"].add(group_name)
        # Om SF-admin: partner_id är alltid SSF själv — ta senast
        if org_type == 2:
            pending[login]["partner_id"] = partner_id

    # Applicera
    for login, data in pending.items():
        user = login_to_user[login]
        uid  = _to_int(user["id"])
        existing_groups = set(user.get("groups_id") or [])
        group_ids_to_add = [groups[g] for g in data["groups"] if g in groups]
        portal_gid = groups.get("group_portal")
        user_gid   = groups.get("group_user")

        group_ops = [(4, gid) for gid in group_ids_to_add]
        if portal_gid and portal_gid in existing_groups:
            group_ops.append((3, portal_gid))   # ta bort portal
        if user_gid and user_gid not in existing_groups:
            group_ops.append((4, user_gid))      # lägg till intern

        vals = {
            "groups_id": group_ops,
            "ssfta_managed_partner_id": data["partner_id"],
        }

        grp_names = ", ".join(data["groups"])
        if dry_run:
            print(f"  [DRY] {login:45s} → {grp_names}  [{data['org_name']}]")
        else:
            User.write([uid], vals)
        stats["assigned"] += 1

    print(f"  {stats['assigned']} users tilldelade")
    print(f"  {stats['skipped_no_user']} logins saknar Odoo-user")
    print(f"  {stats['skipped_no_partner']} orgar saknar Odoo-partner")
    print(f"  {stats['skipped_unmapped']} omappade privilege-kombinationer")
    return stats


# ── DEL 2: Klubbadministratör ──────────────────────────────────────────────────

def assign_club_admins(env, groups: dict, dry_run: bool) -> dict:
    print("\n── DEL 2: PersonIOLRoles Klubbadministratör → ssf_club_admin ──")
    admins = fetch_club_admins()
    print(f"  {len(admins)} Klubbadministratör-poster hämtade.")

    Partner = env["res.partner"]
    User    = env["res.users"]

    # Karta: ssfta-person-{rfid} → email (från Odoo)
    persons = Partner.search_read(
        [("ref", "like", "ssfta-person-"), ("email", "!=", False)],
        ["id", "ref", "email"]
    )
    person_ref_to_email = {_s(p["ref"]): _s(p["email"]) for p in persons if p.get("email")}

    # Karta: email → user
    users = User.search_read([("active", "in", [True, False])], ["id", "login", "groups_id"])
    login_to_user = {_s(u["login"]): u for u in users}

    # Karta: ssfta-{rfid} → partner_id (föreningar)
    org_partners = Partner.search_read(
        [("ref", "like", "ssfta-"), ("is_company", "=", True)],
        ["id", "ref"]
    )
    ref_to_org_partner = {_s(p["ref"]): _to_int(p["id"]) for p in org_partners if p.get("ref")}

    portal_gid   = groups.get("group_portal")
    user_gid     = groups.get("group_user")
    club_gid     = groups.get("group_ssf_club_admin")

    stats = {"assigned": 0, "no_email": 0, "no_user": 0, "no_partner": 0}

    for row in admins:
        person_ref = "ssfta-person-" + _s(row["PersonRfid"]).upper()
        org_ref    = "ssfta-" + _s(row["OrgRfid"])

        email = person_ref_to_email.get(person_ref)
        if not email:
            stats["no_email"] += 1
            continue

        user = login_to_user.get(email)
        if not user:
            stats["no_user"] += 1
            continue

        org_partner_id = ref_to_org_partner.get(org_ref)
        if not org_partner_id:
            stats["no_partner"] += 1
            continue

        uid = _to_int(user["id"])
        existing_groups = set(user.get("groups_id") or [])

        group_ops = [(4, club_gid)] if club_gid else []
        if portal_gid and portal_gid in existing_groups:
            group_ops.append((3, portal_gid))
        if user_gid and user_gid not in existing_groups:
            group_ops.append((4, user_gid))

        vals = {
            "groups_id": group_ops,
            "ssfta_managed_partner_id": org_partner_id,
        }

        if dry_run:
            print(f"  [DRY] {email:45s} → ssf_club_admin  [{_s(row['OrgName'])}]")
        else:
            User.write([uid], vals)
        stats["assigned"] += 1

    print(f"  {stats['assigned']} klub-admins tilldelade")
    print(f"  {stats['no_email']} persons saknar email i Odoo (testdb-begränsning)")
    print(f"  {stats['no_user']} emails matchar ingen Odoo-user")
    print(f"  {stats['no_partner']} föreningar saknar Odoo-partner")
    return stats


# ── Reset ──────────────────────────────────────────────────────────────────────

def reset_all(env, groups: dict, dry_run: bool) -> None:
    print("\n── RESET: tar bort alla SSF-grupptilldelningar ──")
    User = env["res.users"]
    ssf_gids = [gid for name, gid in groups.items() if name.startswith("group_ssf_")]
    portal_gid = groups.get("group_portal")

    users_with_ssf = User.search_read(
        [("groups_id", "in", ssf_gids)],
        ["id", "login", "groups_id"]
    )
    print(f"  {len(users_with_ssf)} users med SSF-grupper hittade.")

    for u in users_with_ssf:
        uid = _to_int(u["id"])
        existing = set(u.get("groups_id") or [])
        ops = [(3, gid) for gid in ssf_gids if gid in existing]
        if portal_gid and portal_gid not in existing:
            ops.append((4, portal_gid))   # återställ till portal

        if dry_run:
            print(f"  [DRY] RESET {_s(u['login'])}")
        else:
            User.write([uid], {
                "groups_id": ops,
                "ssfta_managed_partner_id": False,
            })

    print(f"  {'(dry-run) ' if dry_run else ''}Reset klar.")


# ── Huvud ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db",      default=None)
    parser.add_argument("--reset",   action="store_true",
                        help="Ta bort alla SSF-grupptilldelningar")
    parser.add_argument("--del1-only", action="store_true",
                        help="Kör bara DEL 1 (LoginPrivileges)")
    parser.add_argument("--del2-only", action="store_true",
                        help="Kör bara DEL 2 (Klubbadministratör)")
    args = parser.parse_args()

    print("Ansluter till Odoo...")
    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print(f"  Ansluten till {env.db}")

    print("Hämtar grupp-ID:n...")
    groups = _build_group_cache(env)
    print(f"  Grupper: { {k: v for k, v in groups.items()} }")

    if args.reset:
        reset_all(env, groups, dry_run=args.dry_run)
        return

    if not args.del2_only:
        assign_from_login_privileges(env, groups, dry_run=args.dry_run)

    if not args.del1_only:
        assign_club_admins(env, groups, dry_run=args.dry_run)

    if args.dry_run:
        print("\n(--dry-run, inga ändringar skrevs)")
    else:
        print("\nKlar.")


if __name__ == "__main__":
    main()
