"""
events_db.py — SQLite event-loggning med trigger-baserad Odoo-synk

Design:
  - Alla events skrivs till SQLite omedelbart (synkront, aldrig blocking)
  - Trigger: varje ny event läggs direkt på en in-memory kö
  - En daemon-tråd tömmer kön och synkar till Odoo
  - Odoo nere → event stannar som synced_to_odoo=0 (pending)
  - Vid nästa lyckade anslutning hämtas och synkas alla pending automatiskt
  - Inget cron-jobb behövs — kön är källan till sanning

Schema (events.db):
  id              INTEGER PRIMARY KEY
  timestamp       TEXT
  sender          TEXT
  subject         TEXT
  klassificering  TEXT        -- intentionskategori
  utfall          TEXT        -- allowed | blocked | error
  pii_risk        TEXT
  block_reason    TEXT
  synced_to_odoo  INTEGER     -- 0=pending, 1=synced
"""

import sqlite3
import threading
import queue
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent / "events.db"

# ── Global synk-kö och worker-state ─────────────────────────────────────────
_sync_queue: queue.Queue = queue.Queue()
_worker_started: bool = False
_worker_lock: threading.Lock = threading.Lock()


# ═════════════════════════════════════════════════════════════════════════════
# Dataklasser
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class EventRow:
    sender: str
    subject: str
    klassificering: str
    utfall: str               # allowed | blocked | error
    pii_risk: str
    block_reason: Optional[str] = None


# ═════════════════════════════════════════════════════════════════════════════
# DB-hantering
# ═════════════════════════════════════════════════════════════════════════════

def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Skapar tabellen om den inte finns. Idempotent."""
    conn = _connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT NOT NULL,
            sender          TEXT NOT NULL,
            subject         TEXT,
            klassificering  TEXT,
            utfall          TEXT NOT NULL,
            pii_risk        TEXT,
            block_reason    TEXT,
            synced_to_odoo  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# Loggning + trigger
# ═════════════════════════════════════════════════════════════════════════════

def log_event(
    event: EventRow,
    db_path: Path = DEFAULT_DB_PATH,
    odoo_sync_fn: Optional[Callable] = None,
) -> int:
    """
    Skriver event till SQLite och triggar Odoo-synk om odoo_sync_fn ges.
    Returnerar det nya event-id:t.
    """
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()

    conn = _connect(db_path)
    cur = conn.execute(
        """INSERT INTO events
             (timestamp, sender, subject, klassificering, utfall, pii_risk, block_reason, synced_to_odoo)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (
            now,
            event.sender,
            event.subject,
            event.klassificering,
            event.utfall,
            event.pii_risk,
            event.block_reason,
        ),
    )
    event_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Trigger: lägg på kön om sync är konfigurerat
    if odoo_sync_fn is not None:
        _ensure_worker(db_path, odoo_sync_fn)
        _sync_queue.put(event_id)
        logger.debug("Event %d lagd på Odoo-synk-kön", event_id)

    return event_id


# ═════════════════════════════════════════════════════════════════════════════
# Worker-tråd (daemon, startas en gång)
# ═════════════════════════════════════════════════════════════════════════════

def _ensure_worker(db_path: Path, odoo_sync_fn: Callable) -> None:
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            t = threading.Thread(
                target=_worker_loop,
                args=(db_path, odoo_sync_fn),
                daemon=True,
                name="odoo-sync-worker",
            )
            t.start()
            _worker_started = True
            logger.info("Odoo-synk worker startad")


def _worker_loop(db_path: Path, odoo_sync_fn: Callable) -> None:
    """
    Tömmer synk-kön. Kör tills processen avslutas (daemon=True).
    Backoff vid fel: 2 s → 8 s → 30 s.
    """
    BACKOFF = [2, 8, 30]
    consecutive_failures = 0

    while True:
        # Vänta på nästa event-id, timeout=60 s → kontrollera pending
        try:
            event_id = _sync_queue.get(timeout=60)
        except queue.Empty:
            _requeue_pending(db_path)
            continue

        try:
            conn = _connect(db_path)
            row = conn.execute(
                "SELECT * FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            conn.close()

            if row is None:
                _sync_queue.task_done()
                continue

            odoo_sync_fn(dict(row))

            conn = _connect(db_path)
            conn.execute(
                "UPDATE events SET synced_to_odoo = 1 WHERE id = ?", (event_id,)
            )
            conn.commit()
            conn.close()

            consecutive_failures = 0
            logger.debug("Event %d synkad till Odoo", event_id)

        except Exception as exc:
            consecutive_failures += 1
            wait = BACKOFF[min(consecutive_failures - 1, len(BACKOFF) - 1)]
            logger.warning(
                "Odoo-synk misslyckades för event %d: %s — retry om %ds",
                event_id, exc, wait,
            )
            # Lägg tillbaka efter backoff
            threading.Timer(wait, lambda eid=event_id: _sync_queue.put(eid)).start()

        finally:
            _sync_queue.task_done()


def _requeue_pending(db_path: Path) -> None:
    """Hittar pending events i DB och lägger dem på kön igen."""
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT id FROM events WHERE synced_to_odoo = 0"
        ).fetchall()
        conn.close()
        for row in rows:
            _sync_queue.put(row["id"])
        if rows:
            logger.info("%d pending event(s) åter på synk-kön", len(rows))
    except Exception as exc:
        logger.warning("Kunde inte hämta pending events: %s", exc)


# ═════════════════════════════════════════════════════════════════════════════
# Hjälpfunktioner
# ═════════════════════════════════════════════════════════════════════════════

def get_pending_count(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Returnerar antal ej synkade events. -1 vid fel."""
    try:
        conn = _connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE synced_to_odoo = 0"
        ).fetchone()[0]
        conn.close()
        return count
    except Exception:
        return -1


def reset_worker_state() -> None:
    """Nollställer worker-state — används i tester."""
    global _worker_started
    with _worker_lock:
        _worker_started = False
    # Töm kön
    while not _sync_queue.empty():
        try:
            _sync_queue.get_nowait()
            _sync_queue.task_done()
        except queue.Empty:
            break
