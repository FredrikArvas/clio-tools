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
    "downloaded",
    "uap_classified",
    "transcribing",
    "transcribed",
    "indexed",
    "notified",
    "crashed",
]


# ---------------------------------------------------------------------------
# Anslutning
# ---------------------------------------------------------------------------

def get_odoo_env():
    """
    Returnerar en ansluten OdooConnector mot vigil-databasen, eller None vid fel.
    Läser VIGIL_ODOO_URL / VIGIL_ODOO_DB från root-/.env (clio-tools/.env),
    annars ODOO_URL / ODOO_DB.
    """
    import os
    from pathlib import Path
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env", override=False)
    except Exception:
        pass
    try:
        from clio_odoo import connect
        return connect(
            url=os.environ.get("VIGIL_ODOO_URL") or None,
            db=os.environ.get("VIGIL_ODOO_DB") or None,
        )
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


def _read_transcript(row) -> str:
    """Laserna transkriptfilen och returnerar sammanfogad text, eller tom strang."""
    path = row["transcript_path"] if "transcript_path" in row.keys() else None
    if not path:
        return ""
    try:
        import json as _json
        from pathlib import Path as _Path
        p = _Path(path)
        if not p.exists():
            return ""
        segments = _json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(segments, list) or not segments:
            return ""
        return "\n".join(s.get("text", "").strip() for s in segments if s.get("text"))
    except Exception as exc:
        _logger.debug("_read_transcript: kunde inte lasa %s: %s", path, exc)
        return ""


def _item_to_vals(row) -> dict:
    """Konverterar en SQLite-rad (sqlite3.Row) till Odoo-faltvarden."""
    transcript = _read_transcript(row)
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
        "audio_path":          row["audio_path"] if "audio_path" in row.keys() else False,
        "transcript_snippet":  transcript[:1000] if transcript else False,
        # Sprint C
        "archive_downloaded":  bool(row["archive_downloaded"]) if "archive_downloaded" in row.keys() else False,
        "archive_path":        row["archive_path"] if "archive_path" in row.keys() else False,
        # Sprint E: kraschisolering
        "error_message":       row["error_message"] if "error_message" in row.keys() else False,
    }


# ---------------------------------------------------------------------------
# Källsynk
# ---------------------------------------------------------------------------


def build_sources_config(sources: list[dict]) -> dict:
    """
    Konverterar read_sources()-lista till det format collectors forvanter sig.
    rss/web -> result["rss"]
    youtube  -> result["youtube_channels"]
    google_news -> result["google_news"] (aggregerat)
    """
    rss     = [s for s in sources if s["source_type"] in ("rss", "web")]
    youtube = [s for s in sources if s["source_type"] == "youtube"]
    gn      = [s for s in sources if s["source_type"] == "google_news"]

    result: dict = {"rss": rss, "youtube_channels": youtube}

    if gn:
        result["google_news"] = {
            "lang":    gn[0].get("lang", "en"),
            "country": gn[0].get("country", "US"),
            "weight":  max(s.get("weight", 1.5) for s in gn),
            "queries": [s["query"] for s in gn if s.get("query")],
        }

    return result


def write_sources(odoo_env, sources: list[dict]) -> int:
    """
    Upsert bevakningskällor till clio.vigil.source.
    Nyckel: (domain, name). Stöder rss, youtube, google_news, web.
    Returnerar antal synkade källposter.
    """
    if odoo_env is None or not sources:
        return 0

    Source = odoo_env["clio.vigil.source"]
    synced = 0

    for s in sources:
        name   = (s.get("name") or "").strip()
        domain = s.get("domain", "")
        if not name or not domain:
            continue
        source_type = s.get("source_type", s.get("type", "rss"))
        try:
            vals = {
                "name":                    name[:200],
                "domain":                  domain,
                "source_type":             source_type,
                "maturity":                s.get("maturity", "tidig"),
                "weight":                  float(s.get("weight", 1.0)),
                "active":                  bool(s.get("active", True)),
                "notes":                   s.get("notes", "") or "",
                "archive_enabled":         bool(s.get("archive", False)),
                "auth_env":                s.get("auth_env") or "",
                "transcription_threshold": float(s.get("transcription_threshold") or 0.0),
            }
            if source_type == "youtube":
                vals["channel_id"] = s.get("channel_id", "")
                vals["url"]        = s.get("url", "") or ""
            elif source_type == "google_news":
                vals["google_news_query"] = s.get("query", s.get("google_news_query", ""))
                vals["lang"]    = s.get("lang", "en")
                vals["country"] = s.get("country", "US")
            else:
                vals["url"] = (s.get("url", "") or "").strip()

            existing = Source.search_read(
                [("domain", "=", domain), ("name", "=", name)], ["id"], limit=1
            )
            if existing:
                Source.write([existing[0]["id"]], vals)
            else:
                Source.create(vals)
            synced += 1
        except Exception as exc:
            _logger.warning("write_sources: fel för %s/%s: %s", domain, name[:40], exc)

    _logger.info("write_sources: %d källposter synkade", synced)
    return synced


def read_sources(odoo_env, domain: str) -> list[dict]:
    """
    Hämtar aktiva bevakningskällor för en domän från clio.vigil.source.
    Returnerar lista med dicts kompatibla med collector-interfacet.
    """
    if odoo_env is None:
        return []

    rows = odoo_env["clio.vigil.source"].search_read(
        [("domain", "=", domain), ("active", "=", True)],
        [
            "name", "source_type", "url", "channel_id",
            "google_news_query", "lang", "country",
            "maturity", "weight", "transcription_threshold",
            "auth_env", "archive_enabled",
        ],
    )

    sources = []
    for r in rows:
        s = {
            "name":        r["name"],
            "source_type": r["source_type"],
            "maturity":    r["maturity"] or "tidig",
            "weight":      r["weight"] or 1.0,
            "active":      True,
            "domain":      domain,
        }
        if r["transcription_threshold"]:
            s["transcription_threshold"] = r["transcription_threshold"]
        if r["auth_env"]:
            s["auth_env"] = r["auth_env"]
        if r["archive_enabled"]:
            s["archive"] = True

        if r["source_type"] == "youtube":
            s["channel_id"] = r["channel_id"] or ""
        elif r["source_type"] == "google_news":
            s["query"]   = r["google_news_query"] or ""
            s["lang"]    = r["lang"] or "en"
            s["country"] = r["country"] or "US"
        else:
            s["url"] = r["url"] or ""

        sources.append(s)

    _logger.info("read_sources: %d aktiva källor för domän=%s", len(sources), domain)
    return sources


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
    Läser objekt från SQLite och upsert:ar till clio.vigil.item.
    Returnerar antal synkade poster.

    states: lista av tillstånd att synka (default: SYNC_STATES).
    """
    if odoo_env is None:
        return 0

    states = states or SYNC_STATES
    placeholders = ",".join("?" * len(states))

    try:
        rows = conn.execute(
            f"SELECT * FROM vigil_items WHERE state IN ({placeholders})",
            states,
        ).fetchall()
    except Exception as exc:
        _logger.warning("sync_items_from_conn: SQLite-läsfel: %s", exc)
        return 0

    if not rows:
        return 0

    synced = sum(1 for row in rows if sync_item(odoo_env, row))
    _logger.info("sync_items_from_conn: %d/%d objekt synkade", synced, len(rows))
    return synced


def sync_journalists_from_conn(odoo_env, conn) -> int:
    """Upsert:ar journalister från SQLite till clio.lobbying.journalist."""
    if odoo_env is None:
        return 0
    try:
        rows = conn.execute("SELECT * FROM journalists").fetchall()
    except Exception as exc:
        _logger.warning("sync_journalists_from_conn: SQLite-läsfel: %s", exc)
        return 0
    if not rows:
        return 0

    Journalist = odoo_env["clio.lobbying.journalist"]
    synced = 0
    for row in rows:
        vals = {
            "name":          row["name"],
            "publication":   row["publication"],
            "domain":        row["domain"],
            "email":         row["email"] or False,
            "topics":        row["topics"] or False,
            "profile":       row["profile"] or False,
            "article_count": row["article_count"] or 0,
        }
        try:
            existing = Journalist.search([("name", "=", row["name"]), ("publication", "=", row["publication"])], limit=1)
            if existing:
                existing.write(vals)
            else:
                Journalist.create(vals)
            synced += 1
        except Exception as exc:
            _logger.warning("sync_journalists_from_conn: %s/%s fel: %s", row["name"], row["publication"], exc)

    _logger.info("sync_journalists_from_conn: %d/%d journalister synkade", synced, len(rows))
    return synced


# ---------------------------------------------------------------------------
# Sync till clio.media.article
# ---------------------------------------------------------------------------

_SOURCE_TYPE_TO_MEDIA = {
    "youtube": "video",
}


def _media_type_from_row(row) -> str:
    """Avgör media_type: youtube→video, rss med enclosure→podcast, annars article."""
    source_type = row["source_type"] or "rss"
    if source_type in _SOURCE_TYPE_TO_MEDIA:
        return _SOURCE_TYPE_TO_MEDIA[source_type]
    if source_type == "rss":
        try:
            import json
            meta = json.loads(row["raw_metadata"] or "{}")
            if meta.get("enclosure_url"):
                return "podcast"
        except Exception:
            pass
    return "article"


def sync_items_to_media(odoo_env, conn, states: list[str] | None = None) -> int:
    """
    Upsert vigil_items till clio.media.article (redaktionellt arkiv).
    Skriver bara basdata + vigil_item_id-länken.
    Vigil-specifik data (state, score, transkript) lasas via lanken.
    """
    if odoo_env is None:
        return 0

    sync_states = states or SYNC_STATES
    placeholders = ",".join("?" * len(sync_states))

    try:
        rows = conn.execute(
            f"SELECT * FROM vigil_items WHERE state IN ({placeholders})",
            sync_states,
        ).fetchall()
    except Exception as exc:
        _logger.warning("sync_items_to_media: SQLite-lasfel: %s", exc)
        return 0

    if not rows:
        return 0

    Article   = odoo_env["clio.media.article"]
    VigilItem = odoo_env["clio.vigil.item"]
    synced = 0

    for row in rows:
        url = row["url"] if hasattr(row, "__getitem__") else None
        if not url:
            continue
        try:
            # Hitta matchande clio.vigil.item
            vigil_recs = VigilItem.search_read([("url", "=", url)], ["id"], limit=1)
            vigil_id = vigil_recs[0]["id"] if vigil_recs else False

            transcript = _read_transcript(row)
            vals = {
                "url":         url,
                "title":       (row["title"] or "")[:500],
                "source":      (row["source_name"] or "")[:200],
                "media_type":  _media_type_from_row(row),
                "published":   _dt(row["published_at"]),
                "first_seen":  _dt(row["published_at"]) or _dt(row["created_at"]) or _utcnow_str(),
                "data_source": "vigil_%s" % row["domain"],
                "vigil_item_id": vigil_id,
            }
            if row["summary"]:
                vals["body_snippet"] = row["summary"]
            if transcript:
                vals["body"] = transcript

            existing = Article.search_read([("url", "=", url)], ["id"], limit=1)
            if existing:
                Article.write([existing[0]["id"]], vals)
            else:
                Article.create(vals)
            synced += 1
        except Exception as exc:
            _logger.warning("sync_items_to_media: fel for %s: %s", str(url)[:60], exc)

    _logger.info("sync_items_to_media: %d/%d objekt synkade", synced, len(rows))
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
