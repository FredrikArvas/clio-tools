"""
db.py — Database connection, migration, and audit helpers for clio-partnerdb.

Usage:
    from db import connect, audit

    conn = connect()                      # uses ~/.clio/partnerdb.sqlite
    conn = connect("/custom/path.sqlite") # explicit path
    conn = connect(":memory:")            # for tests

    with conn:                            # transaction
        conn.execute("INSERT INTO partner ...", (...))
        audit(conn, "partner", {"id": pid}, "insert", after={...}, actor="user@example.com")
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def get_db_path() -> str:
    """
    Resolve the DB path:
      1. CLIO_PARTNERDB environment variable (for tests / custom setups)
      2. Default: ~/.clio/partnerdb.sqlite
    """
    if custom := os.environ.get("CLIO_PARTNERDB"):
        return custom
    clio_dir = os.path.join(os.path.expanduser("~"), ".clio")
    os.makedirs(clio_dir, exist_ok=True)
    return os.path.join(clio_dir, "partnerdb.sqlite")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def connect(db_path: str = None) -> sqlite3.Connection:
    """
    Open (or create) the partnerdb SQLite file.
    Runs schema migration on first connection.
    Returns a connection with row_factory = sqlite3.Row.
    """
    if db_path is None:
        db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate(conn: sqlite3.Connection) -> None:
    """
    Apply schema migrations based on PRAGMA user_version.
    Version 0 → 1: initial schema (schema.sql).
    Future versions: add elif blocks, bump user_version at the end.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]

    if version == 0:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.execute("PRAGMA user_version = 1")
        conn.commit()

    # elif version == 1:
    #     conn.executescript("ALTER TABLE ...")
    #     conn.execute("PRAGMA user_version = 2")
    #     conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------

def audit(
    conn: sqlite3.Connection,
    table: str,
    row_key: dict,
    op: str,                          # 'insert'|'update'|'delete'
    after: Optional[dict] = None,
    before: Optional[dict] = None,
    actor: str = "system",
    reason: Optional[str] = None,
) -> None:
    """
    Append a row to audit_log within the current transaction.
    Must be called inside the same `with conn:` block as the main mutation.

    Example:
        with conn:
            conn.execute("INSERT INTO partner VALUES (?,?,?,?,?)", (...))
            audit(conn, "partner", {"id": pid}, "insert", after=row_dict, actor="user@x.se")
    """
    conn.execute(
        """
        INSERT INTO audit_log
            (table_name, row_key, operation, before_json, after_json,
             changed_at, changed_by, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            table,
            json.dumps(row_key, ensure_ascii=False),
            op,
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
            datetime.now(timezone.utc).isoformat(),
            actor,
            reason,
        ),
    )


# ---------------------------------------------------------------------------
# Generic helpers used by import_gedcom and cli
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_source(conn: sqlite3.Connection, src_type: str, reference: str,
                  actor: str) -> str:
    """Create a source record and return its id."""
    import uuid
    sid = str(uuid.uuid4())
    row = {
        "id": sid, "type": src_type, "reference": reference,
        "imported_at": now_iso(), "imported_by": actor,
    }
    with conn:
        conn.execute(
            "INSERT INTO source (id, type, reference, imported_at, imported_by) VALUES (?,?,?,?,?)",
            (row["id"], row["type"], row["reference"], row["imported_at"], row["imported_by"]),
        )
        audit(conn, "source", {"id": sid}, "insert", after=row, actor=actor,
              reason=f"source created for {src_type}")
    return sid


def get_or_create_partner(conn: sqlite3.Connection, ext_system: str, ext_id: str,
                           actor: str) -> tuple[str, bool]:
    """
    Look up partner via external_ref. If found, return (partner_id, False).
    If not found, create a new partner and return (partner_id, True).
    """
    import uuid, json
    row = conn.execute(
        "SELECT partner_id FROM external_ref WHERE system=? AND external_id=?",
        (ext_system, ext_id),
    ).fetchone()
    if row:
        return row["partner_id"], False

    pid = str(uuid.uuid4())
    ts = now_iso()
    partner_row = {
        "id": pid, "created_at": ts, "editors": json.dumps([actor]),
        "is_person": 1, "is_org": 0,
    }
    with conn:
        conn.execute(
            "INSERT INTO partner (id, created_at, editors, is_person, is_org) VALUES (?,?,?,?,?)",
            (pid, ts, partner_row["editors"], 1, 0),
        )
        audit(conn, "partner", {"id": pid}, "insert", after=partner_row, actor=actor)
        conn.execute(
            "INSERT INTO external_ref (system, external_id, partner_id) VALUES (?,?,?)",
            (ext_system, ext_id, pid),
        )
        audit(conn, "external_ref", {"system": ext_system, "external_id": ext_id},
              "insert", after={"partner_id": pid}, actor=actor)
    return pid, True


def upsert_claim(conn: sqlite3.Connection, partner_id: str, predicate: str,
                 value: Any, source_id: str, actor: str,
                 valid_from: str = None, valid_to: str = None,
                 is_primary: bool = True) -> str:
    """
    Insert a claim. Does not update existing claims — each import run
    creates a new claim row (claims are immutable once written).
    Returns the new claim id.
    """
    import uuid, json as _json
    cid = str(uuid.uuid4())
    value_json = _json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    ts = now_iso()
    row = {
        "id": cid, "partner_id": partner_id, "predicate": predicate,
        "value": value_json, "valid_from": valid_from, "valid_to": valid_to,
        "is_primary": int(is_primary), "source_id": source_id,
        "asserted_by": actor, "asserted_at": ts,
    }
    with conn:
        conn.execute(
            """INSERT INTO claim
               (id, partner_id, predicate, value, valid_from, valid_to,
                is_primary, source_id, asserted_by, asserted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, partner_id, predicate, value_json, valid_from, valid_to,
             int(is_primary), source_id, actor, ts),
        )
        audit(conn, "claim", {"id": cid}, "insert", after=row, actor=actor)
    return cid


def upsert_event(conn: sqlite3.Connection, partner_id: str, event_type: str,
                 source_id: str, actor: str,
                 date_from: str = None, date_precision: str = None,
                 place: str = None) -> str:
    """Insert an event record. Returns the new event id."""
    import uuid
    eid = str(uuid.uuid4())
    row = {
        "id": eid, "partner_id": partner_id, "type": event_type,
        "date_from": date_from, "date_precision": date_precision,
        "place": place, "source_id": source_id,
    }
    with conn:
        conn.execute(
            """INSERT INTO event
               (id, partner_id, type, date_from, date_precision, place, source_id)
               VALUES (?,?,?,?,?,?,?)""",
            (eid, partner_id, event_type, date_from, date_precision, place, source_id),
        )
        audit(conn, "event", {"id": eid}, "insert", after=row, actor=actor)
    return eid


def upsert_relationship(conn: sqlite3.Connection, from_id: str, to_id: str,
                         rel_type: str, source_id: str, actor: str) -> None:
    """Insert a relationship if it doesn't already exist."""
    import uuid
    exists = conn.execute(
        "SELECT 1 FROM relationship WHERE from_id=? AND to_id=? AND type=?",
        (from_id, to_id, rel_type),
    ).fetchone()
    if exists:
        return
    rid = str(uuid.uuid4())
    row = {"id": rid, "from_id": from_id, "to_id": to_id, "type": rel_type,
           "source_id": source_id}
    with conn:
        conn.execute(
            "INSERT INTO relationship (id, from_id, to_id, type, source_id) VALUES (?,?,?,?,?)",
            (rid, from_id, to_id, rel_type, source_id),
        )
        audit(conn, "relationship", {"id": rid}, "insert", after=row, actor=actor)


def upsert_watch(conn: sqlite3.Connection, owner_email: str, partner_id: str,
                 priority: str, source: str, actor: str) -> bool:
    """
    Add a watch row if it doesn't exist. Returns True if inserted, False if already present.
    added_at is set to now() on insert and never updated (first-run suppression depends on it).
    """
    exists = conn.execute(
        "SELECT 1 FROM watch WHERE owner_email=? AND partner_id=?",
        (owner_email, partner_id),
    ).fetchone()
    if exists:
        return False
    ts = now_iso()
    row = {"owner_email": owner_email, "partner_id": partner_id,
           "priority": priority, "source": source, "added_at": ts}
    with conn:
        conn.execute(
            "INSERT INTO watch (owner_email, partner_id, priority, source, added_at) VALUES (?,?,?,?,?)",
            (owner_email, partner_id, priority, source, ts),
        )
        audit(conn, "watch", {"owner_email": owner_email, "partner_id": partner_id},
              "insert", after=row, actor=actor,
              reason=f"watch added for {owner_email}")
    return True


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_partner_names(conn: sqlite3.Connection, partner_id: str) -> list[dict]:
    """Return all name claims for a partner (primary first)."""
    rows = conn.execute(
        "SELECT * FROM claim WHERE partner_id=? AND predicate='name' ORDER BY is_primary DESC",
        (partner_id,),
    ).fetchall()
    result = []
    for r in rows:
        try:
            v = json.loads(r["value"])
        except Exception:
            v = {"raw": r["value"]}
        result.append({**v, "is_primary": bool(r["is_primary"]),
                        "valid_from": r["valid_from"], "valid_to": r["valid_to"]})
    return result


def get_birth_year(conn: sqlite3.Connection, partner_id: str) -> Optional[int]:
    """Return the birth year from the partner's birth event, or None."""
    row = conn.execute(
        "SELECT date_from FROM event WHERE partner_id=? AND type='birth' LIMIT 1",
        (partner_id,),
    ).fetchone()
    if not row or not row["date_from"]:
        return None
    try:
        return int(row["date_from"][:4])
    except (ValueError, TypeError):
        return None


def list_watch_entries(conn: sqlite3.Connection, owner_email: str) -> list[dict]:
    """
    Return all watch entries for owner with resolved name and birth year.
    Each dict has: partner_id, priority, added_at, fornamn, efternamn,
                   birth_year, city, source.
    """
    watches = conn.execute(
        "SELECT * FROM watch WHERE owner_email=?", (owner_email,)
    ).fetchall()

    result = []
    for w in watches:
        pid = w["partner_id"]
        names = get_partner_names(conn, pid)
        primary_name = next((n for n in names if n.get("is_primary")), names[0] if names else {})

        birth_year = get_birth_year(conn, pid)

        # City from claim
        city_row = conn.execute(
            "SELECT value FROM claim WHERE partner_id=? AND predicate='city' AND is_primary=1 LIMIT 1",
            (pid,),
        ).fetchone()
        city = None
        if city_row:
            try:
                city = json.loads(city_row["value"])
            except Exception:
                city = city_row["value"]

        result.append({
            "partner_id": pid,
            "priority": w["priority"],
            "added_at": w["added_at"],
            "source": w["source"],
            "fornamn": primary_name.get("fornamn", ""),
            "efternamn": primary_name.get("efternamn", ""),
            "all_names": names,
            "birth_year": birth_year,
            "city": city,
        })
    return result


def partner_full_info(conn: sqlite3.Connection, partner_id: str) -> Optional[dict]:
    """Return all known data for a partner (for verify/show commands)."""
    p = conn.execute("SELECT * FROM partner WHERE id=?", (partner_id,)).fetchone()
    if not p:
        return None

    claims = conn.execute("SELECT * FROM claim WHERE partner_id=?", (partner_id,)).fetchall()
    events = conn.execute("SELECT * FROM event  WHERE partner_id=?", (partner_id,)).fetchall()
    rels_from = conn.execute("SELECT * FROM relationship WHERE from_id=?", (partner_id,)).fetchall()
    rels_to   = conn.execute("SELECT * FROM relationship WHERE to_id=?",   (partner_id,)).fetchall()
    ext_refs  = conn.execute("SELECT * FROM external_ref WHERE partner_id=?", (partner_id,)).fetchall()

    return {
        "partner": dict(p),
        "claims":  [dict(c) for c in claims],
        "events":  [dict(e) for e in events],
        "relationships_from": [dict(r) for r in rels_from],
        "relationships_to":   [dict(r) for r in rels_to],
        "external_refs": [dict(r) for r in ext_refs],
    }
