"""
state.py — SQLite-tillståndshantering för clio-agent-mail

Tabeller:
  mail       — varje inkommande mail med status
  approvals  — väntande och besvarade godkännanden
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "state.db"

STATUS_NEW = "NEW"
STATUS_PENDING = "PENDING"
STATUS_SENT = "SENT"
STATUS_FLAGGED = "FLAGGED"
STATUS_REJECTED = "REJECTED"


def get_connection(db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn):
    """Lägger till kolumner som saknas i befintliga tabeller (idempotent)."""
    migrations = [
        ("approvals",            "fredrik_cc",          "ALTER TABLE approvals ADD COLUMN fredrik_cc TEXT"),
        ("flagged_notifications", "responded_at",        "ALTER TABLE flagged_notifications ADD COLUMN responded_at TEXT"),
        ("flagged_notifications", "response",            "ALTER TABLE flagged_notifications ADD COLUMN response TEXT"),
    ]
    for table, col, sql in migrations:
        # Kör bara om tabellen finns och kolumnen saknas
        tbl_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not tbl_exists:
            continue
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(sql)
            conn.commit()


def init_db(db_path=None):
    """Skapar tabeller om de inte redan finns och kör migreringar."""
    with get_connection(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS mail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                account TEXT NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT,
                body TEXT,
                date_received TEXT,
                status TEXT NOT NULL DEFAULT 'NEW',
                action TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mail_id INTEGER NOT NULL REFERENCES mail(id),
                approval_message_id TEXT,
                draft TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                responded_at TEXT,
                response TEXT,
                fredrik_cc TEXT
            );

            CREATE TABLE IF NOT EXISTS learned_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_subject TEXT,
                original_body TEXT,
                original_sender TEXT,
                approved_reply TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS flagged_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mail_id INTEGER NOT NULL REFERENCES mail(id),
                notification_message_id TEXT NOT NULL,
                sender_email TEXT NOT NULL,
                responded_at TEXT,
                response TEXT
            );

            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                added_at TEXT NOT NULL
            );
        """)
        _migrate(conn)


def is_seen(message_id, db_path=None):
    """Returnerar True om ett mail med detta message_id redan finns i databasen."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM mail WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row is not None


def save_mail(message_id, account, sender, subject, body,
              date_received, status=STATUS_NEW, action=None, db_path=None):
    """Sparar ett nytt mail. Ignorerar om message_id redan finns."""
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO mail
               (message_id, account, sender, subject, body,
                date_received, status, action, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (message_id, account, sender, subject, body,
             date_received, status, action, now, now),
        )


def update_status(message_id, status, db_path=None):
    """Uppdaterar status på ett mail."""
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE mail SET status = ?, updated_at = ? WHERE message_id = ?",
            (status, now, message_id),
        )


def get_mail_id(message_id, db_path=None):
    """Returnerar intern databas-id för ett givet message_id, eller None."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM mail WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row["id"] if row else None


def save_approval(mail_id, draft, approval_message_id=None, fredrik_cc=None, db_path=None):
    """Sparar ett nytt godkännandeärende."""
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO approvals
               (mail_id, approval_message_id, draft, sent_at, fredrik_cc)
               VALUES (?, ?, ?, ?, ?)""",
            (mail_id, approval_message_id, draft, now, fredrik_cc),
        )


def get_pending_approvals(db_path=None):
    """Returnerar alla godkännanden som väntar på Fredriks svar."""
    with get_connection(db_path) as conn:
        return conn.execute(
            """SELECT a.id, a.mail_id, a.draft, a.approval_message_id, a.sent_at,
                      a.fredrik_cc,
                      m.message_id, m.account, m.sender, m.subject, m.body
               FROM approvals a
               JOIN mail m ON a.mail_id = m.id
               WHERE a.responded_at IS NULL
               AND m.status = 'PENDING'"""
        ).fetchall()


def record_approval_response(approval_id, response, db_path=None):
    """Registrerar Fredriks JA/NEJ-svar på ett godkännandeärende."""
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE approvals SET responded_at = ?, response = ? WHERE id = ?",
            (now, response, approval_id),
        )


def save_learned_reply(original_subject, original_body, original_sender,
                       approved_reply, db_path=None):
    """Sparar ett av Fredrik godkänt svar som läroexempel."""
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO learned_replies
               (original_subject, original_body, original_sender, approved_reply, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (original_subject, original_body, original_sender, approved_reply, now),
        )


def get_learned_replies(limit: int = 20, db_path=None) -> list:
    """Returnerar de senaste godkända svaren, nyast först."""
    with get_connection(db_path) as conn:
        return conn.execute(
            """SELECT original_subject, original_body, original_sender, approved_reply
               FROM learned_replies ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()


def save_flagged_notification(mail_id, notification_message_id, sender_email, db_path=None):
    """Sparar en flaggad notifiering som väntar på Fredriks VITLISTA/SVARTLISTA/BEHÅLL-svar."""
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO flagged_notifications
               (mail_id, notification_message_id, sender_email)
               VALUES (?, ?, ?)""",
            (mail_id, notification_message_id, sender_email.lower()),
        )


def get_pending_flagged_notifications(db_path=None) -> list:
    """Returnerar flaggade notifieringar som ännu inte besvarats."""
    with get_connection(db_path) as conn:
        return conn.execute(
            """SELECT id, mail_id, notification_message_id, sender_email
               FROM flagged_notifications
               WHERE responded_at IS NULL"""
        ).fetchall()


def record_flagged_response(notification_id, response, db_path=None):
    """Registrerar Fredriks svar på en flaggad notifiering."""
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE flagged_notifications SET responded_at = ?, response = ? WHERE id = ?",
            (now, response, notification_id),
        )


def add_to_blacklist(email, db_path=None):
    """Lägger till en adress i svartlistan. Ignorerar om den redan finns."""
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO blacklist (email, added_at) VALUES (?, ?)",
            (email.lower(), now),
        )


def is_blacklisted(email, db_path=None) -> bool:
    """Returnerar True om adressen finns i svartlistan."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM blacklist WHERE email = ?", (email.lower(),)
        ).fetchone()
        return row is not None


def get_all_mail_for_insights(limit: int = 200, db_path=None) -> list:
    """Returnerar mail-data för insiktsanalys (inga brödtexter — bara metadata)."""
    with get_connection(db_path) as conn:
        return conn.execute(
            """SELECT sender, subject, action, status, date_received
               FROM mail ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
