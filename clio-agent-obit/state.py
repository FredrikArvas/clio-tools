"""
state.py — SQLite-tillstånd för clio-agent-obit

Håller reda på vilka annons-ID:n som redan är sedda,
så att samma annons inte triggar notis vid varje körning.

state.db skapas automatiskt vid första körning.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Optional

STATE_DB = os.path.join(os.path.dirname(__file__), "state.db")

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS seen_announcements (
    id          TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL,
    matched     INTEGER NOT NULL DEFAULT 0
);
"""


def _connect(db_path: str = STATE_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(_CREATE_SQL)
    conn.commit()
    return conn


def is_seen(announcement_id: str, db_path: str = STATE_DB) -> bool:
    """Returnerar True om annonsen redan är registrerad."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_announcements WHERE id = ?",
            (announcement_id,),
        ).fetchone()
        return row is not None


def mark_seen(
    announcement_id: str,
    matched: bool = False,
    db_path: str = STATE_DB,
) -> None:
    """Markerar en annons som sedd. matched=True om den triggade notis."""
    now = datetime.now().isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_announcements (id, first_seen, matched) VALUES (?, ?, ?)",
            (announcement_id, now, int(matched)),
        )
        conn.commit()


def count_seen(db_path: str = STATE_DB) -> int:
    """Returnerar antal registrerade annonser i databasen."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM seen_announcements").fetchone()
        return row[0] if row else 0
