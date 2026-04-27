"""
migrate_watch_data.py
Engångsmigering: skapar clio.obit.watch-rader för alla res.partner
som hade clio_obit_watch=True (läses direkt ur PostgreSQL-kolumnen
som nu är en orphan-kolumn sedan fältet togs bort från modellen).

Kör på servern:
    python3 migrate_watch_data.py --user fredrik@arvas.se

Idempotent: hoppar över partners som redan har en watch-rad.
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent  # clio-tools/
for _p in [str(_ROOT / "clio-partnerdb"), str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _pg_connect():
    """Anslut direkt till PostgreSQL för att läsa orphan-kolumner."""
    import psycopg2
    import os
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    dbname = os.environ.get("PGDATABASE", "aiab")
    user = os.environ.get("PGUSER", "odoo")
    password = os.environ.get("PGPASSWORD", "odoo")
    return psycopg2.connect(host=host, port=port, dbname=dbname,
                            user=user, password=password)


def migrate(owner_email: str, dry_run: bool = False) -> None:
    from clio_odoo import connect
    env = connect()

    # Hitta användaren
    users = env["res.users"].search_read(
        [("login", "=", owner_email)], ["id", "name"]
    )
    if not users:
        users = env["res.users"].search_read(
            [("email", "=", owner_email)], ["id", "name"]
        )
    if not users:
        print(f"Fel: Ingen användare med e-post {owner_email}")
        sys.exit(1)
    user_id = users[0]["id"]
    print(f"Bevakare: {users[0]['name']} (id={user_id})")

    # Läs orphan-kolumnerna direkt ur PostgreSQL
    # (clio_obit_watch, clio_obit_priority, clio_obit_notify_email
    #  finns kvar i tabellen efter att fälten togs bort från modellen)
    conn = _pg_connect()
    cur = conn.cursor()

    # Kontrollera att kolumnerna finns
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'res_partner'
          AND column_name IN ('clio_obit_watch','clio_obit_priority','clio_obit_notify_email')
    """)
    found_cols = {r[0] for r in cur.fetchall()}
    print(f"Hittade orphan-kolumner: {found_cols}")

    if "clio_obit_watch" not in found_cols:
        print("Kolumnen clio_obit_watch saknas — ingenting att migrera.")
        conn.close()
        return

    priority_col = "clio_obit_priority" if "clio_obit_priority" in found_cols else None
    email_col = "clio_obit_notify_email" if "clio_obit_notify_email" in found_cols else None

    select_cols = "id, name"
    if priority_col:
        select_cols += f", {priority_col}"
    if email_col:
        select_cols += f", {email_col}"

    cur.execute(f"SELECT {select_cols} FROM res_partner WHERE clio_obit_watch = true AND active = true")
    rows = cur.fetchall()
    conn.close()

    col_names = ["id", "name"]
    if priority_col:
        col_names.append(priority_col)
    if email_col:
        col_names.append(email_col)

    partners = [dict(zip(col_names, row)) for row in rows]
    print(f"Hittade {len(partners)} bevakade partners att migrera")

    # Hämta befintliga watch-rader för denna användare
    existing = env["clio.obit.watch"].search_read(
        [("user_id", "=", user_id)],
        ["partner_id"],
    )
    existing_pids = {r["partner_id"][0] for r in existing}

    created = skipped = 0
    for p in partners:
        pid = p["id"]
        if pid in existing_pids:
            skipped += 1
            continue

        priority = p.get(priority_col) or "normal" if priority_col else "normal"
        notify   = p.get(email_col) or "" if email_col else ""

        if dry_run:
            print(f"  [DRY] {p['name']} → {priority}")
            created += 1
            continue

        env["clio.obit.watch"].create({
            "partner_id":   pid,
            "user_id":      user_id,
            "priority":     priority,
            "notify_email": notify,
        })
        print(f"  [NY]  {p['name']} → {priority}")
        created += 1

    print(f"\nKlart: {created} skapade, {skipped} redan befintliga")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Migrera clio_obit_watch-data till clio.obit.watch")
    p.add_argument("--user",    required=True, metavar="EMAIL", help="E-post för bevakaren")
    p.add_argument("--dry-run", action="store_true", help="Simulera utan att skriva")
    args = p.parse_args()
    migrate(args.user, args.dry_run)
