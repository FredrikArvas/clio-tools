"""
sync_users.py — Skapar Odoo portal-users från SSFTA LoginPrivileges.

Strategi B:
  Alla aktiva logins skapas som portal-users oavsett om de matchar en person.
  Person-koppling via PersonAdmins → Persons.rfid där möjligt (ca 19 av 137).
  Övriga: partner söks via login-email, skapas om den saknas.
  Privileges tagggas på partnern (SSFTA:priv:events m.fl.).

Körning:
    python sync_users.py             # live
    python sync_users.py --dry-run
    python sync_users.py --db ssf_t2
"""

from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import pymssql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

USER_TAG       = "SSFTA:Login"
PRIV_PREFIX    = "SSFTA:priv:"


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


def fetch_logins() -> dict[str, dict]:
    """Returnerar dict keyed på login-email med aggregerad data."""
    cfg = _load_ssfta_env()
    conn = pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8"
    )
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT
            lp.Login,
            lp.Privilege,
            lp.IsRevoked,
            o.rfid     AS org_rfid,
            o.FullName AS org_name,
            p.rfid     AS person_rfid,
            p.Firstname,
            p.Lastname
        FROM LoginPrivileges lp
        JOIN Organizations o ON o.ID = lp.Organization
        LEFT JOIN PersonAdmins pa ON pa.login = lp.Login AND pa.persontype = 'Member'
        LEFT JOIN Persons p ON p.ID = pa.person
    """)
    rows = cur.fetchall()
    conn.close()

    users = {}
    for r in rows:
        login = r["Login"].strip().lower()
        if login not in users:
            users[login] = {
                "login":       login,
                "active":      not r["IsRevoked"],
                "person_rfid": None,
                "firstname":   None,
                "lastname":    None,
                "privileges":  set(),
                "org_rfids":   set(),
            }
        if r["Privilege"]:
            users[login]["privileges"].add(r["Privilege"])
        if r["org_rfid"]:
            users[login]["org_rfids"].add(str(r["org_rfid"]).upper())
        if not r["IsRevoked"]:
            users[login]["active"] = True
        if not users[login]["person_rfid"] and r["person_rfid"]:
            users[login]["person_rfid"] = r["person_rfid"]
            users[login]["firstname"]   = r["Firstname"]
            users[login]["lastname"]    = r["Lastname"]

    return users


# ── Odoo-hjälpare ──────────────────────────────────────────────────────────────

def _to_int(val) -> int:
    return val.id if hasattr(val, "id") else int(val)


def _get_or_create_tag(env, name: str, cache: dict) -> int:
    if name in cache:
        return cache[name]
    Cat = env["res.partner.category"]
    hits = Cat.search_read([("name", "=", name)], ["id"])
    tid = _to_int(hits[0]["id"]) if hits else _to_int(Cat.create({"name": name}))
    cache[name] = tid
    return tid


def _portal_group_id(env) -> int:
    groups = env["res.groups"].search_read([("full_name", "=", "Portal")], ["id"])
    if not groups:
        raise RuntimeError("Hittade inte Portal-gruppen i Odoo")
    return _to_int(groups[0]["id"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    print("Hämtar logins från SSFTA...")
    users_data = fetch_logins()
    total  = len(users_data)
    active = sum(1 for u in users_data.values() if u["active"])
    print(f"  {total} unika logins ({active} aktiva, {total - active} revokerade)")

    print("Ansluter till Odoo...")
    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print(f"  Ansluten till {env.db}")

    # rfid → partner_id (ssfta-poster)
    print("Bygger partner-karta...")
    Partner = env["res.partner"]
    ssfta_partners = Partner.search_read(
        [("active", "in", [True, False]), ("ref", "like", "ssfta-")],
        ["id", "ref", "email"]
    )
    rfid_to_pid   = {}
    email_to_pid  = {}
    for p in ssfta_partners:
        ref = p.get("ref") or ""
        if ref.startswith("ssfta-"):
            rfid_to_pid[ref[len("ssfta-"):].upper()] = _to_int(p["id"])
        if p.get("email"):
            email_to_pid[p["email"].strip().lower()] = _to_int(p["id"])

    # Komplettera email_to_pid med alla partners
    all_with_email = Partner.search_read(
        [("active", "in", [True, False]), ("email", "!=", False)],
        ["id", "email"]
    )
    for p in all_with_email:
        em = (p.get("email") or "").strip().lower()
        if em and em not in email_to_pid:
            email_to_pid[em] = _to_int(p["id"])
    print(f"  {len(rfid_to_pid)} ssfta-rfid, {len(email_to_pid)} email-mappningar")

    # Portal-grupp
    portal_gid = None
    if not args.dry_run:
        portal_gid = _portal_group_id(env)

    # Befintliga Odoo-users
    Users = env["res.users"]
    existing = Users.search_read(
        [("active", "in", [True, False])], ["login", "active"]
    )
    existing_logins = {u["login"].strip().lower() for u in existing}
    print(f"  {len(existing_logins)} befintliga Odoo-users")

    tag_cache = {}
    created = skipped = errors = 0

    for login, u in users_data.items():
        name = " ".join(filter(None, [u["firstname"], u["lastname"]])) or login

        # ── Hitta partner ────────────────────────────────────────────────────
        partner_id = None
        source     = "?"

        if u["person_rfid"]:
            rfid_key   = str(u["person_rfid"]).upper()
            partner_id = rfid_to_pid.get(rfid_key)
            if partner_id:
                source = "person_rfid"

        if not partner_id:
            partner_id = email_to_pid.get(login)
            if partner_id:
                source = "email"

        if not partner_id:
            source = "ny"
            if not args.dry_run:
                partner_id = _to_int(Partner.create({
                    "name":       name,
                    "email":      login,
                    "is_company": False,
                }))
                email_to_pid[login] = partner_id

        # ── Taggar ───────────────────────────────────────────────────────────
        tag_names = [USER_TAG] + [PRIV_PREFIX + p for p in u["privileges"]]
        if not args.dry_run and partner_id:
            tag_ids = [_get_or_create_tag(env, t, tag_cache) for t in tag_names]
            Partner.write([partner_id], {"category_id": [(4, tid) for tid in tag_ids]})

        # ── Skapa user ───────────────────────────────────────────────────────
        if login in existing_logins:
            skipped += 1
            continue

        privs = ", ".join(sorted(u["privileges"]))
        if args.dry_run:
            print(f"  [DRY] {login:<38} | {name:<22} | src:{source:<10} | {privs}")
            created += 1
            continue

        try:
            Users.create({
                "login":      login,
                "name":       name,
                "partner_id": partner_id,
                "active":     u["active"],
                "groups_id":  [(6, 0, [portal_gid])],
            })
            existing_logins.add(login)
            created += 1
        except Exception as e:
            print(f"  FEL ({login}): {e}")
            errors += 1

    print("\nKlar:")
    print(f"  {created} users skapade")
    print(f"  {skipped} hoppade över (login fanns redan)")
    print(f"  {errors} fel")
    if args.dry_run:
        print("  (--dry-run, ingen data skrevs)")


if __name__ == "__main__":
    main()
