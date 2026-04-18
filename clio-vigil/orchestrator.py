"""
clio-vigil — orchestrator.py
============================
Tillståndsmaskin och SQLite-nav för alla bevakningsobjekt.

Livscykel per objekt:
  discovered → filtered_in / filtered_out
             → queued
             → transcribing (med sparad position för preemptiv paus)
             → transcribed
             → indexed
             → notified

Designbeslut (ADD v0.2, 2026-04-18):
  - SQLite som tillståndslagring (stdlib, beprövat i clio-obit)
  - Preemptiv transkriptionskö: högre prio kan pausa pågående jobb
  - Prioritetstal = relevansscore × källvikt × (1 / längd_normaliserad)
  - Källmognad lagras som metadata, blockerar inte insamling
"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konstanter
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "data" / "vigil.db"

# Giltiga tillstånd i livscykeln
STATES = [
    "discovered",
    "filtered_in",
    "filtered_out",
    "queued",
    "transcribing",
    "transcribed",
    "indexed",
    "notified",
]

# Källmognadsklasser (ADD beslut: metadata, inte filter)
SOURCE_MATURITY = ["tidig", "etablerad", "akademisk"]

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS vigil_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Identifiering
    url                 TEXT NOT NULL UNIQUE,
    domain              TEXT NOT NULL,           -- t.ex. "ufo", "ai_models"
    source_type         TEXT NOT NULL,           -- "rss", "youtube", "web"
    source_name         TEXT,                    -- t.ex. "Vetenskapens Värld"
    source_maturity     TEXT DEFAULT 'tidig',    -- tidig | etablerad | akademisk

    -- Innehåll
    title               TEXT,
    description         TEXT,                    -- rubrik + ingress för filtrering
    published_at        TEXT,                    -- ISO 8601
    duration_seconds    INTEGER,                 -- None om okänd

    -- Poäng och prioritet
    relevance_score     REAL DEFAULT 0.0,        -- 0–1 från filtret
    priority_score      REAL DEFAULT 0.0,        -- relevansscore × källvikt × (1/längd)
    source_weight       REAL DEFAULT 1.0,        -- justeras per källa vid onboarding

    -- Tillstånd
    state               TEXT DEFAULT 'discovered',
    state_updated_at    TEXT,

    -- Transkription (preemptiv paus)
    transcript_path     TEXT,                    -- sökväg till färdig transkript
    whisper_segment     INTEGER DEFAULT 0,       -- senast färdigt segment vid paus
    whisper_model       TEXT DEFAULT 'medium',

    -- RAG
    chroma_collection   TEXT,                    -- t.ex. "vigil_ufo"
    indexed_at          TEXT,

    -- Notifiering
    summary             TEXT,                    -- 2-3 meningar (~8 ord/mening)
    notified_at         TEXT,

    -- Metadata
    created_at          TEXT DEFAULT (datetime('now')),
    raw_metadata        TEXT                     -- JSON-blob för källspecifika fält
);

CREATE INDEX IF NOT EXISTS idx_state      ON vigil_items(state);
CREATE INDEX IF NOT EXISTS idx_domain     ON vigil_items(domain);
CREATE INDEX IF NOT EXISTS idx_priority   ON vigil_items(priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_published  ON vigil_items(published_at DESC);

-- Källregister: onboarding-konfiguration per källa
CREATE TABLE IF NOT EXISTS vigil_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT NOT NULL,
    source_type     TEXT NOT NULL,           -- rss | youtube | web
    url             TEXT NOT NULL UNIQUE,
    name            TEXT,
    maturity        TEXT DEFAULT 'tidig',    -- tidig | etablerad | akademisk
    weight          REAL DEFAULT 1.0,        -- multiplikator för prioritetstal
    active          INTEGER DEFAULT 1,       -- 0 = pausad
    added_at        TEXT DEFAULT (datetime('now')),
    notes           TEXT
);

-- Kölogg: spårar preemptiva pauser
CREATE TABLE IF NOT EXISTS transcription_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER REFERENCES vigil_items(id),
    priority_score  REAL,
    queued_at       TEXT DEFAULT (datetime('now')),
    started_at      TEXT,
    paused_at       TEXT,
    completed_at    TEXT,
    pause_reason    TEXT                     -- t.ex. "preempted_by_item_42"
);
"""

# ---------------------------------------------------------------------------
# Databasinitiering
# ---------------------------------------------------------------------------

def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Initierar databasen och returnerar en anslutning."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    logger.info(f"vigil.db initierad: {db_path}")
    return conn


# ---------------------------------------------------------------------------
# Tillståndsövergångar
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def transition(conn: sqlite3.Connection, item_id: int, new_state: str, **kwargs) -> bool:
    """
    Övergår ett objekt till nytt tillstånd.
    Valfria kwargs skriver till motsvarande kolumner (t.ex. summary, transcript_path).
    Returnerar True om övergången lyckades.
    """
    if new_state not in STATES:
        raise ValueError(f"Ogiltigt tillstånd: {new_state}. Giltiga: {STATES}")

    updates = {"state": new_state, "state_updated_at": _now()}
    updates.update(kwargs)

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["item_id"] = item_id

    cur = conn.execute(
        f"UPDATE vigil_items SET {set_clause} WHERE id = :item_id",
        updates
    )
    conn.commit()

    if cur.rowcount == 0:
        logger.warning(f"Ingen rad uppdaterad för item_id={item_id}")
        return False

    logger.debug(f"Item {item_id} → {new_state}")
    return True


# ---------------------------------------------------------------------------
# Inläggning av nya objekt
# ---------------------------------------------------------------------------

def upsert_item(conn: sqlite3.Connection, url: str, domain: str,
                source_type: str, **fields) -> Optional[int]:
    """
    Lägger till ett nytt bevakningsobjekt eller ignorerar om URL redan finns.
    Returnerar item_id, eller None om objektet redan existerade.
    """
    try:
        cur = conn.execute(
            """
            INSERT INTO vigil_items (url, domain, source_type,
                source_name, source_maturity, title, description,
                published_at, duration_seconds, source_weight, raw_metadata)
            VALUES (:url, :domain, :source_type,
                :source_name, :source_maturity, :title, :description,
                :published_at, :duration_seconds, :source_weight, :raw_metadata)
            """,
            {
                "url": url,
                "domain": domain,
                "source_type": source_type,
                "source_name": fields.get("source_name"),
                "source_maturity": fields.get("source_maturity", "tidig"),
                "title": fields.get("title"),
                "description": fields.get("description"),
                "published_at": fields.get("published_at"),
                "duration_seconds": fields.get("duration_seconds"),
                "source_weight": fields.get("source_weight", 1.0),
                "raw_metadata": fields.get("raw_metadata"),
            }
        )
        conn.commit()
        logger.info(f"Nytt objekt: [{domain}] {fields.get('title', url)[:60]}")
        return cur.lastrowid

    except sqlite3.IntegrityError:
        # URL redan känd — ingen dubblett
        return None


# ---------------------------------------------------------------------------
# Prioritetsberäkning
# ---------------------------------------------------------------------------

def compute_priority(relevance_score: float, source_weight: float,
                     duration_seconds: Optional[int],
                     max_duration: int = 10800) -> float:
    """
    Prioritetstal = relevansscore × källvikt × (1 / längd_normaliserad)

    Längd normaliseras mot max_duration (default 3h).
    Okänd längd → neutral faktor 0.5.
    """
    if duration_seconds is None:
        length_factor = 0.5
    else:
        normalized = min(duration_seconds / max_duration, 1.0)
        length_factor = 1.0 - normalized  # kortare = högre prio

    return round(relevance_score * source_weight * length_factor, 4)


def update_priority(conn: sqlite3.Connection, item_id: int) -> float:
    """Räknar om och sparar prioritetstal för ett objekt."""
    row = conn.execute(
        "SELECT relevance_score, source_weight, duration_seconds FROM vigil_items WHERE id = ?",
        (item_id,)
    ).fetchone()

    if not row:
        raise ValueError(f"item_id {item_id} hittades inte")

    prio = compute_priority(row["relevance_score"], row["source_weight"], row["duration_seconds"])
    conn.execute("UPDATE vigil_items SET priority_score = ? WHERE id = ?", (prio, item_id))
    conn.commit()
    return prio


# ---------------------------------------------------------------------------
# Köhantering (preemptiv paus)
# ---------------------------------------------------------------------------

def get_next_queued(conn: sqlite3.Connection, domain: Optional[str] = None):
    """Hämtar nästa objekt i kön, sorterat på priority_score DESC."""
    query = """
        SELECT * FROM vigil_items
        WHERE state = 'queued'
        {}
        ORDER BY priority_score DESC
        LIMIT 1
    """.format("AND domain = ?" if domain else "")

    params = (domain,) if domain else ()
    return conn.execute(query, params).fetchone()


def preempt_current(conn: sqlite3.Connection, current_id: int,
                    reason: str, segment: int) -> bool:
    """
    Pausar pågående transkriptionsjobb vid aktuellt Whisper-segment.
    Sparar position så att jobbet kan återupptas.
    """
    ok = transition(conn, current_id, "queued",
                    whisper_segment=segment)
    conn.execute(
        """UPDATE transcription_queue
           SET paused_at = ?, pause_reason = ?
           WHERE item_id = ? AND completed_at IS NULL""",
        (_now(), reason, current_id)
    )
    conn.commit()
    logger.info(f"Item {current_id} pausad vid segment {segment}: {reason}")
    return ok


# ---------------------------------------------------------------------------
# Statistik (för CLI och framtida Odoo-vy)
# ---------------------------------------------------------------------------

def stats(conn: sqlite3.Connection) -> dict:
    """Returnerar en översikt över tillståndsfördelning."""
    rows = conn.execute(
        "SELECT state, COUNT(*) as n FROM vigil_items GROUP BY state"
    ).fetchall()
    return {row["state"]: row["n"] for row in rows}


def domain_stats(conn: sqlite3.Connection) -> dict:
    """Uppdelat per domän."""
    rows = conn.execute(
        "SELECT domain, state, COUNT(*) as n FROM vigil_items GROUP BY domain, state"
    ).fetchall()
    result = {}
    for row in rows:
        result.setdefault(row["domain"], {})[row["state"]] = row["n"]
    return result
