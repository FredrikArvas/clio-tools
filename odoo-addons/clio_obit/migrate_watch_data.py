"""
migrate_watch_data.py
Engångsmigering: skapar clio.obit.watch-rader för alla res.partner
som har clio_obit_watch=True, och kopplar dem till angiven användare.

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

    # Hämta alla bevakade partners (gamla boolean-flaggan)
    partners = env["res.partner"].search_read(
        [("clio_obit_watch", "=", True)],
        ["id", "name", "clio_obit_priority", "clio_obit_notify_email"],
    )
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

        priority = p.get("clio_obit_priority") or "normal"
        notify   = p.get("clio_obit_notify_email") or ""

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
