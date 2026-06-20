"""
odoo_writer.py — clio-vigil
============================
Synkroniserar clio-vigils pipeline till Odoo:
  - clio.vigil.source   — bevakningskällor (från YAML-config)
  - clio.vigil.item     — pipeline-objekt (speglar vigil_items i SQLite)
  - clio.tool.heartbeat — agenthälsa (cockpit-vyn)

Kraschsäkert: Odoo är ett extra lager, inte ett hårdberoende.
Om anslutning saknas eller misslyckas loggas en varning och körningen fortsätter.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Lägg till clio-tools-roten i sys.path så att clio_odoo kan importeras
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_logger = logging.getLogger(__name__)

TOOL_NAME = "clio-vigil"

# Tillstånd som är värda att spegla till Odoo (discovered = för många)
SYNC_STATES = [
    "filtered_in",
    "filtered_out",
    "queued",
    "transcribing",
    "transcribed",
    "indexed",
    "notified",
]


# ---------------------------------------------------------------------------
# Anslutning
# ---------------------------------------------------------------------------

def get_odoo_env():
    """Returnerar en ansluten OdooConnector, eller None vid fel."""
    try:
        from clio_odoo import connect
        return connect()
    except Exception as exc:
        _logger.warning("Odoo-anslutning misslyckades: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _utcnow_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _dt(s) -> str | bool:
    """Normaliserar datum/tid-sträng till 'YYYY-MM-DD HH:MM:SS' eller False."""
    if not s:
        return False
    try:
        return str(s)[:19].replace("T", " ")
    except Exception:
        return False


def _item_to_vals(row) -> dict:
    """Konverterar en SQLite-rad (sqlite3.Row) till Odoo-fältvärden."""
    return {
        "url":              row["url"],
        "title":            (row["title"] or "")[:500],
        "domain":           row["domain"] or "",
        "source_type":      ("web" if row["source_type"] == "pdf" else row["source_type"]) or "web",
        "source_name":      (row["source_name"] or "")[:200],
        "source_maturity":  row["source_maturity"] or "tidig",
        "published_at":     _dt(row["published_at"]),
        "duration_seconds": row["duration_seconds"] or False,
        "relevance_score":  float(row["relevance_score"] or 0.0),
        "priority_score":   float(row["priority_score"] or 0.0),
        "state":               row["state"] or "discovered",
        "summary":             row["summary"] or False,
        "created_at":          _dt(row["created_at"]),
        "notified_at":         _dt(row["notified_at"]),
        # Sprint C
        "archive_downloaded":  bool(row["archive_downloaded"]) if "archive_downloaded" in row.keys() else False,
        "archive_path":        row["archive_path"] if "archive_path" in row.keys() else False,
    }


# ---------------------------------------------------------------------------
# Källsynk
# ---------------------------------------------------------------------------

def write_sources(odoo_env, sources: list[dict]) -> int:
    """
    Upsert bevakningskällor till clio.vigil.source.
    Nyckel: url. Returnerar antal synkade källposter.

    Varje post är en dict med nycklarna:
        name, domain, source_type, url, maturity, weight, active, notes
    """
    if odoo_env is None or not sources:
        return 0

    Source = odoo_env["clio.vigil.source"]
    synced = 0

    for s in sources:
        url = s.get("url", "").strip()
        if not url:
            continue
        try:
            vals = {
                "name":        (s.get("name") or url)[:200],
                "domain":      s.get("domain", ""),
                "source_type": s.get("source_type", s.get("type", "rss")),
                "url":         url,
                "maturity":    s.get("maturity", "tidig"),
                "weight":      float(s.get("weight", 1.0)),
                "active":      bool(s.get("active", True)),
                "notes":       s.get("notes", "") or "",
            }
            existing = Source.search_read([("url", "=", url)], ["id"], limit=1)
            if existing:
                Source.write([existing[0]["id"]], vals)
            else:
                Source.create(vals)
            synced += 1
        except Exception as exc:
            _logger.warning("write_sources: fel för %s: %s", url[:60], exc)

    _logger.info("write_sources: %d källposter synkade", synced)
    return synced


# ---------------------------------------------------------------------------
# Objektsynk
# ---------------------------------------------------------------------------

def sync_item(odoo_env, row) -> bool:
    """
    Upsert ett enskilt vigil_item (SQLite-rad) till clio.vigil.item.
    Nyckel: url. Returnerar True om lyckades.
    """
    if odoo_env is None:
        return False
    try:
        Item = odoo_env["clio.vigil.item"]
        vals = _item_to_vals(row)
        existing = Item.search_read([("url", "=", vals["url"])], ["id"], limit=1)
        if existing:
            Item.write([existing[0]["id"]], vals)
        else:
            Item.create(vals)
        return True
    except Exception as exc:
        url = row["url"] if hasattr(row, "__getitem__") else "?"
        _logger.warning("sync_item: fel för %s: %s", str(url)[:60], exc)
        return False


def sync_items_from_conn(odoo_env, conn, states: list[str] | None = None) -> int:
    """
    Delta-synkar vigil_items → clio.vigil.item.

    Synkar bara rader där odoo_synced_state saknas eller skiljer sig från
    aktuellt state. Batch-lookup + batch-create minskar Odoo-anrop från
    2N → 1 + N_changed + 1 (steady state ~50 anrop istället för ~3900).

    states: lista av tillstånd att synka (default: SYNC_STATES).
    """
    if odoo_env is None:
        return 0

    # Migrering: lägg till kolumn om den saknas (idempotent)
    try:
        conn.execute("ALTER TABLE vigil_items ADD COLUMN odoo_synced_state TEXT")
        conn.commit()
    except Exception:
        pass  # Kolumnen finns redan

    states = states or SYNC_STATES
    placeholders = ",".join("?" * len(states))

    try:
        rows = conn.execute(
            f"""SELECT * FROM vigil_items
                WHERE state IN ({placeholders})
                AND (odoo_synced_state IS NULL OR odoo_synced_state != state)""",
            states,
        ).fetchall()
    except Exception as exc:
        _logger.warning("sync_items_from_conn: SQLite-läsfel: %s", exc)
        return 0

    if not rows:
        _logger.info("sync_items_from_conn: inget att synka (ingen state-ändring)")
        return 0

    Item = odoo_env["clio.vigil.item"]

    # Batch-lookup: ett enda anrop för alla URL:er
    all_urls = [row["url"] for row in rows]
    try:
        existing = Item.search_read([("url", "in", all_urls)], ["id", "url"])
        url_to_id = {r["url"]: r["id"] for r in existing}
    except Exception as exc:
        _logger.warning("sync_items_from_conn: batch-lookup misslyckades: %s", exc)
        return 0

    to_create: list[dict] = []
    synced_urls: list[str] = []

    for row in rows:
        vals = _item_to_vals(row)
        url  = vals["url"]
        try:
            if url in url_to_id:
                Item.write([url_to_id[url]], vals)
            else:
                to_create.append(vals)
            synced_urls.append(url)
        except Exception as exc:
            _logger.warning("sync_items_from_conn: write-fel för %s: %s", url[:60], exc)

    # Batch-create för nya poster
    if to_create:
        try:
            Item.create(to_create)
        except Exception as exc:
            _logger.warning("sync_items_from_conn: batch-create misslyckades: %s", exc)
            synced_urls = [u for u in synced_urls if u not in {v["url"] for v in to_create}]

    # Markera synkade rader i SQLite
    if synced_urls:
        conn.executemany(
            "UPDATE vigil_items SET odoo_synced_state = state WHERE url = ?",
            [(u,) for u in synced_urls],
        )
        conn.commit()

    synced = len(synced_urls)
    _logger.info("sync_items_from_conn: %d/%d objekt synkade", synced, len(rows))
    return synced


# ---------------------------------------------------------------------------
# Leveransposter
# ---------------------------------------------------------------------------

def write_deliveries(odoo_env, deliveries: list[dict]) -> int:
    """
    Skapar leveransposter i clio.vigil.delivery.

    Varje dict ska ha:
        subscriber_odoo_id  — int, Odoo-id för prenumeranten
        item_url            — str, URL för bevakningsobjektet
        delivered_at        — str, ISO-tid
        digest_date         — str, YYYY-MM-DD (valfritt)

    Returnerar antal skapade poster.
    """
    if odoo_env is None or not deliveries:
        return 0

    Delivery = odoo_env["clio.vigil.delivery"]
    Item     = odoo_env["clio.vigil.item"]
    created  = 0

    for d in deliveries:
        try:
            item = Item.search_read([("url", "=", d["item_url"])], ["id"], limit=1)
            if not item:
                continue
            item_id       = item[0]["id"]
            subscriber_id = d["subscriber_odoo_id"]

            existing = Delivery.search_read(
                [("subscriber_id", "=", subscriber_id), ("item_id", "=", item_id)],
                ["id"],
                limit=1,
            )
            if existing:
                continue

            Delivery.create({
                "subscriber_id": subscriber_id,
                "item_id":       item_id,
                "delivered_at":  d.get("delivered_at") or _utcnow_str(),
                "digest_date":   d.get("digest_date") or False,
            })
            created += 1
        except Exception as exc:
            _logger.warning(
                "write_deliveries: fel för %s → sub %s: %s",
                d.get("item_url", "?")[:60], d.get("subscriber_odoo_id"), exc,
            )

    if created:
        _logger.info("write_deliveries: %d leveransposter skapade", created)
    return created


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

def write_heartbeat(
    odoo_env,
    status: str,
    items_processed: int = 0,
    message: str = "",
) -> None:
    """
    Upsert clio.tool.heartbeat för clio-vigil (cockpit-vyn).
    status: 'ok', 'warning' eller 'error'.
    """
    if odoo_env is None:
        return
    try:
        Heartbeat = odoo_env["clio.tool.heartbeat"]
        vals = {
            "last_run":        _utcnow_str(),
            "status":          status,
            "items_processed": int(items_processed),
            "message":         (message or "")[:255],
        }
        existing = Heartbeat.search_read(
            [("tool_name", "=", TOOL_NAME)], ["id"], limit=1
        )
        if existing:
            Heartbeat.write([existing[0]["id"]], vals)
        else:
            vals["tool_name"] = TOOL_NAME
            Heartbeat.create(vals)
        _logger.info("Heartbeat: %s → %s", TOOL_NAME, status)
    except Exception as exc:
        _logger.warning("write_heartbeat: %s", exc)
