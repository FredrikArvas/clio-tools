"""
state.py — SQLite-tillståndshantering för clio-agent-mail

Tabeller:
  mail                  — varje inkommande mail med status
  approvals             — väntande och besvarade godkännanden
  learned_replies       — Fredrik-godkända svar (few-shot)
  flagged_notifications — VITLISTA/SVARTLISTA/BEHÅLL-ärenden
  blacklist             — permanentblockerade adresser
  partners              — kontakter/partners med språkpreferens
                          (forward-compatible med clio-partnerdb)
  interview_sessions    — pågående intervjudialoger via e-post
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
STATUS_WAITING = "WAITING"  # Väntar på Fredriks vitlistningsbeslut


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
        ("mail",                 "thread_id",            "ALTER TABLE mail ADD COLUMN thread_id TEXT"),
        ("mail",                 "in_reply_to",          "ALTER TABLE mail ADD COLUMN in_reply_to TEXT"),
        ("mail",                 "direction",            "ALTER TABLE mail ADD COLUMN direction TEXT NOT NULL DEFAULT 'inbound'"),
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

            CREATE TABLE IF NOT EXISTS partners (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT UNIQUE NOT NULL,
                name        TEXT,
                language    TEXT,          -- 'sv','en','fr','de' etc. NULL = systemdefault
                role        TEXT,          -- 'contact','admin','external' etc.
                onboarded_at TEXT,         -- ISO datetime, NULL = ej onboardad
                notes       TEXT,
                external_id TEXT,          -- framtida clio-partnerdb sync-ID
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS interview_sessions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id        TEXT NOT NULL,
                participant_email TEXT NOT NULL,
                account_key      TEXT NOT NULL DEFAULT 'clio',
                system_prompt    TEXT,
                status           TEXT NOT NULL DEFAULT 'active',
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL
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


def resolve_thread_id(in_reply_to: str, references: str, db_path=None) -> str | None:
    """Slår upp thread_id för ett inkommande svar via In-Reply-To / References."""
    candidates = []
    if in_reply_to:
        candidates.append(in_reply_to.strip())
    if references:
        candidates.extend(references.split())
    for msg_id in candidates:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT thread_id FROM mail WHERE message_id = ?", (msg_id.strip(),)
            ).fetchone()
            if row and row["thread_id"]:
                return row["thread_id"]
    return None


def save_mail(message_id, account, sender, subject, body,
              date_received, status=STATUS_NEW, action=None,
              thread_id=None, in_reply_to=None, direction="inbound",
              db_path=None):
    """Sparar ett nytt mail. Ignorerar om message_id redan finns."""
    now = datetime.utcnow().isoformat()
    effective_thread_id = thread_id or message_id
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO mail
               (message_id, account, sender, subject, body,
                date_received, status, action, thread_id, in_reply_to,
                direction, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (message_id, account, sender, subject, body,
             date_received, status, action, effective_thread_id, in_reply_to,
             direction, now, now),
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


def get_mail_by_id(mail_id: int, db_path=None):
    """Hämtar ett mail-objekt ur databasen via internt id. Returnerar dict eller None."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM mail WHERE id = ?", (mail_id,)
        ).fetchone()
        return dict(row) if row else None


def get_waiting_mails_for_sender(sender_email: str, db_path=None) -> list:
    """Hämtar alla mail med STATUS_WAITING från en given avsändare."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM mail WHERE status = ? AND sender LIKE ?",
            (STATUS_WAITING, f"%{sender_email}%"),
        ).fetchall()
        return [dict(r) for r in rows]


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


# ── Partners ──────────────────────────────────────────────────────────────────

def get_partner(email: str, db_path=None) -> dict | None:
    """Hämtar en partner ur databasen via e-postadress."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM partners WHERE email = ?", (email.lower(),)
        ).fetchone()
        return dict(row) if row else None


def upsert_partner(email: str, name: str = None, language: str = None,
                   role: str = None, onboarded_at: str = None,
                   notes: str = None, external_id: str = None,
                   db_path=None) -> dict:
    """
    Skapar eller uppdaterar en partner. Returnerar det slutliga partner-objektet.
    Befintliga fält skrivs inte över om inget nytt värde skickas (None = behåll).
    """
    now = datetime.utcnow().isoformat()
    existing = get_partner(email, db_path)
    if not existing:
        with get_connection(db_path) as conn:
            conn.execute(
                """INSERT INTO partners
                   (email, name, language, role, onboarded_at, notes, external_id,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (email.lower(), name, language, role, onboarded_at,
                 notes, external_id, now, now),
            )
    else:
        updates = {
            "name":         name         if name         is not None else existing["name"],
            "language":     language     if language     is not None else existing["language"],
            "role":         role         if role         is not None else existing["role"],
            "onboarded_at": onboarded_at if onboarded_at is not None else existing["onboarded_at"],
            "notes":        notes        if notes        is not None else existing["notes"],
            "external_id":  external_id  if external_id  is not None else existing["external_id"],
            "updated_at":   now,
        }
        with get_connection(db_path) as conn:
            conn.execute(
                """UPDATE partners SET name=?, language=?, role=?, onboarded_at=?,
                   notes=?, external_id=?, updated_at=? WHERE email=?""",
                (updates["name"], updates["language"], updates["role"],
                 updates["onboarded_at"], updates["notes"], updates["external_id"],
                 updates["updated_at"], email.lower()),
            )
    return get_partner(email, db_path)


def get_partner_language(email: str, config, db_path=None) -> str:
    """
    Returnerar språkkod för en partner.
    Prioritet: partners.language → config default_language → 'sv'
    """
    partner = get_partner(email, db_path)
    if partner and partner.get("language"):
        return partner["language"]
    return config.get("mail", "default_language", fallback="sv")


def get_all_partners(db_path=None) -> list:
    """Returnerar alla partners, sorterade på e-post."""
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM partners ORDER BY email"
        ).fetchall()]


# ── Intervjusessioner ─────────────────────────────────────────────────────────

INTERVIEW_STATUS_ACTIVE  = "active"
INTERVIEW_STATUS_STOPPED = "stopped"

_DEFAULT_INTERVIEW_PROMPT = """Du är Clio, AI-medarbetare på Arvas International AB, och genomför en strukturerad intervjudialog via e-post.

Riktlinjer:
- Ställ EN fråga i taget. Vänta alltid på svar innan du går vidare.
- Bekräfta och resonera kring svaret — förklara varför det är intressant eller hur det hänger ihop med helheten.
- Håll en varm, nyfiken och professionell ton.
- Bygg vidare på vad personen berättat — referera till tidigare svar.
- Avsluta aldrig intervjun av dig själv — invänta signal från Fredrik."""


def create_interview_session(thread_id: str, participant_email: str,
                              account_key: str = "clio",
                              system_prompt: str = None,
                              db_path=None) -> dict:
    """Skapar en ny intervjusession. Returnerar det skapade objektet."""
    now = datetime.utcnow().isoformat()
    prompt = system_prompt or _DEFAULT_INTERVIEW_PROMPT
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO interview_sessions
               (thread_id, participant_email, account_key, system_prompt, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (thread_id, participant_email.lower(), account_key, prompt,
             INTERVIEW_STATUS_ACTIVE, now, now),
        )
    return get_active_interview(participant_email, db_path)


def get_active_interview(participant_email: str, db_path=None) -> dict | None:
    """Returnerar aktiv intervjusession för en given e-postadress, eller None."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM interview_sessions
               WHERE participant_email = ? AND status = ?
               ORDER BY created_at DESC LIMIT 1""",
            (participant_email.lower(), INTERVIEW_STATUS_ACTIVE),
        ).fetchone()
        return dict(row) if row else None


def stop_interview_session(thread_id: str, db_path=None):
    """Markerar en intervjusession som avslutad."""
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """UPDATE interview_sessions SET status = ?, updated_at = ?
               WHERE thread_id = ? AND status = ?""",
            (INTERVIEW_STATUS_STOPPED, now, thread_id, INTERVIEW_STATUS_ACTIVE),
        )


def get_thread_history(thread_id: str, db_path=None) -> list:
    """
    Returnerar alla mail i en tråd (inbound + outbound), sorterade kronologiskt.
    Varje rad är en dict med: direction, sender, body, date_received.
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT direction, sender, body, date_received
               FROM mail WHERE thread_id = ?
               ORDER BY date_received ASC, created_at ASC""",
            (thread_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def save_outbound_interview_reply(thread_id: str, account: str, sender: str,
                                   subject: str, body: str,
                                   message_id: str, db_path=None):
    """Sparar ett utgående intervjusvar i mail-tabellen för tråd-historik."""
    now = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO mail
               (message_id, account, sender, subject, body, date_received,
                status, action, thread_id, direction, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (message_id, account, sender, subject, body, now,
             STATUS_SENT, "INTERVIEW", thread_id, "outbound", now, now),
        )


# ── Insikter ──────────────────────────────────────────────────────────────────

def get_all_mail_for_insights(limit: int = 200, db_path=None) -> list:
    """Returnerar mail-data för insiktsanalys (inga brödtexter — bara metadata)."""
    with get_connection(db_path) as conn:
        return conn.execute(
            """SELECT sender, subject, action, status, date_received
               FROM mail ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
