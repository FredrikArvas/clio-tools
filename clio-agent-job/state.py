"""
state.py
SQLite-baserad deduplicering och körlogg för clio-agent-job.
Skapas automatiskt vid första anropet.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_DB_PATH = Path(__file__).parent / "state.db"

_DDL = """
CREATE TABLE IF NOT EXISTS seen_articles (
    article_id  TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    first_seen  TEXT NOT NULL,
    match_score INTEGER NOT NULL DEFAULT -1
);

CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at      TEXT NOT NULL,
    articles_fetched  INTEGER NOT NULL DEFAULT 0,
    articles_new      INTEGER NOT NULL DEFAULT 0,
    articles_matched  INTEGER NOT NULL DEFAULT 0,
    mail_sent   INTEGER NOT NULL DEFAULT 0,
    dry_run     INTEGER NOT NULL DEFAULT 0
);
"""


def _connect(db_path: Path = _DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_DDL)
    conn.commit()
    return conn


def is_seen(article_id: str, db_path: Path = _DB_PATH) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_articles WHERE article_id = ?", (article_id,)
        ).fetchone()
        return row is not None


def mark_seen(
    article_id: str,
    url: str = "",
    title: str = "",
    source: str = "",
    match_score: int = -1,
    db_path: Path = _DB_PATH,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO seen_articles
               (article_id, url, title, source, first_seen, match_score)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (article_id, url, title, source,
             datetime.utcnow().isoformat(), match_score),
        )
        conn.commit()


def log_run(
    articles_fetched: int,
    articles_new: int,
    articles_matched: int,
    mail_sent: int,
    dry_run: bool,
    db_path: Path = _DB_PATH,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO run_log
               (ran_at, articles_fetched, articles_new, articles_matched, mail_sent, dry_run)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(),
             articles_fetched, articles_new, articles_matched,
             mail_sent, int(dry_run)),
        )
        conn.commit()


def last_run_summary(db_path: Path = _DB_PATH) -> str:
    """Returnerar en textrad med senaste körningens statistik."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT ran_at, articles_fetched, articles_new, articles_matched, mail_sent, dry_run "
            "FROM run_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return "Ingen körning loggad ännu."
    ran_at, fetched, new, matched, mail, dry = row
    label = " [dry-run]" if dry else ""
    return (
        f"Senast{label}: {ran_at[:16].replace('T', ' ')} — "
        f"{fetched} hämtade, {new} nya, {matched} matchade, {mail} mail skickade"
    )
