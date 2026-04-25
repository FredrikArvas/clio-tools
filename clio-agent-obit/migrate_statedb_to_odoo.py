"""
migrate_statedb_to_odoo.py
Migrerar seen_announcements från state.db → clio.obit.announcement i Odoo.

Skapar minimala stub-poster (bara ann_id + first_seen) för deduplicering.
Poster som redan finns i Odoo hoppas över.

Kör en gång på servern efter Release 2-uppgradering:
    python3 clio-agent-obit/migrate_statedb_to_odoo.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

STATE_DB = Path(__file__).parent / "state.db"


def _utcnow_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main():
    if not STATE_DB.exists():
        print(f"state.db hittades inte på {STATE_DB}")
        sys.exit(1)

    # Anslut till Odoo
    try:
        from clio_odoo import connect
        env = connect()
    except Exception as e:
        print(f"Odoo-anslutning misslyckades: {e}")
        sys.exit(1)

    # Läs state.db
    conn = sqlite3.connect(STATE_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, first_seen, matched FROM seen_announcements").fetchall()
    print(f"Hittade {len(rows)} poster i state.db")

    # Hämta redan kända IDs från Odoo (bulk)
    existing = env["clio.obit.announcement"].search_read([], ["ann_id"])
    existing_ids = {r["ann_id"] for r in existing}
    print(f"Odoo har redan {len(existing_ids)} annonser")

    Announcement = env["clio.obit.announcement"]
    created = skipped = failed = 0

    for row in rows:
        ann_id = row["id"]
        if ann_id in existing_ids:
            skipped += 1
            continue

        first_seen = row["first_seen"] or _utcnow_str()
        # Normalisera: state.db sparar ibland ISO med T, Odoo vill ha mellanslag
        first_seen = first_seen.replace("T", " ")[:19]

        try:
            Announcement.create({
                "ann_id":     ann_id,
                "name":       "(importerad — ingen annonstext)",
                "matched":    bool(row["matched"]),
                "first_seen": first_seen,
            })
            created += 1
        except Exception as e:
            print(f"  FEL för {ann_id[:40]}...: {e}")
            failed += 1

    conn.close()
    print(f"\nKlart: {created} skapade, {skipped} hoppades över, {failed} fel")


if __name__ == "__main__":
    main()
