"""
odoo_media_writer.py — Skriver kodade nyhetsartiklar till clio.media.article i Odoo.

Följer mönstret från clio-agent-job/odoo_writer.py:
  - load_known_article_ids() för bulk-dedup
  - write_media_articles() för att skriva kodade artiklar

Kräver i .env: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD
Kraschsäkert: Odoo är ett extra lager. Om anslutning saknas fortsätter körningen.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_logger = logging.getLogger(__name__)

_CLIO_ODOO_PATH = Path(__file__).parent.parent / "clio_core"


def _get_env():
    """Returnerar OdooConnector eller None."""
    try:
        sys.path.insert(0, str(_CLIO_ODOO_PATH))
        from clio_odoo import connect
        return connect()
    except Exception as exc:
        _logger.warning("[odoo_media_writer] Odoo-anslutning misslyckades: %s", exc)
        return None


def _utcnow_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def load_known_article_ids(env) -> set[str]:
    """Bulk-hämta kända article_id:n för deduplicering."""
    if env is None:
        return set()
    try:
        rows = env["clio.media.article"].search_read([], ["article_id"])
        ids = {r["article_id"] for r in rows if r.get("article_id")}
        _logger.info("[odoo_media_writer] %d kända artikel-IDs hämtade", len(ids))
        return ids
    except Exception as exc:
        _logger.warning("[odoo_media_writer] Kunde inte hämta artikel-IDs: %s", exc)
        return set()


def write_media_articles(
    coded_articles: list[dict],
    protocol_id: str,
    run_id: str,
) -> None:
    """
    Skriv kodade artiklar från clio-research till clio.media.article.

    Varje artikel är en dict med nycklarna från media_connector + coding-dict
    tillagd av media_coder.
    """
    env = _get_env()
    if env is None or not coded_articles:
        return

    known_ids = load_known_article_ids(env)
    Article = env["clio.media.article"]
    now = _utcnow_str()
    created = skipped = failed = 0

    for a in coded_articles:
        art_id = a.get("article_id") or ""
        if art_id in known_ids:
            skipped += 1
            continue

        coding = a.get("coding") or {}
        published = _parse_date(a.get("date"))

        try:
            Article.create({
                "article_id":           art_id,
                "url":                  (a.get("url") or "")[:500],
                "title":                (a.get("title") or "")[:500],
                "source":               (a.get("outlet") or "")[:255],
                "media_type":           "article",
                "published":            published,
                "first_seen":           now,
                "body_snippet":         (a.get("snippet") or "")[:1000],
                "match_score":          -1,
                "is_matched":           False,
                "country":              (a.get("country") or "")[:10],
                "language":             (a.get("language") or "")[:10],
                "author":               (a.get("author") or "")[:255],
                "tone":                 coding.get("tone") or False,
                "article_type":         coding.get("article_type") or False,
                "thematic_frame":       _map_thematic_frame(coding.get("thematic_frame")),
                "cited_actors":         _join_list(coding.get("cited_actors")),
                "temporal_marker_match": (coding.get("temporal_marker_match") or False),
                "data_source":          (a.get("source") or "")[:50],
                "protocol_id":          protocol_id,
                "run_id":               run_id,
            })
            known_ids.add(art_id)
            created += 1
        except Exception as exc:
            msg = str(exc).lower()
            if "unik" in msg or "unique" in msg or "uniq" in msg:
                skipped += 1
            else:
                failed += 1
                _logger.warning(
                    "[odoo_media_writer] Fel för %s: %s",
                    (a.get("url") or "")[:60], exc,
                )

    _logger.info(
        "[odoo_media_writer] %d skapade, %d skippade (dubblett), %d fel",
        created, skipped, failed,
    )


def _parse_date(date_str: str | None) -> str | bool:
    if not date_str:
        return False
    try:
        d = date_str[:10]
        datetime.strptime(d, "%Y-%m-%d")
        return f"{d} 00:00:00"
    except (ValueError, TypeError):
        return False


def _join_list(items) -> str:
    if not items:
        return ""
    if isinstance(items, list):
        return ", ".join(str(i) for i in items)
    return str(items)


def _map_thematic_frame(value: str | None) -> str | bool:
    """
    Mappar protokollets snake_case-värden till Odoo Selection-nycklar.
    Odoo lagrar nationell_sakerhet (utan ä) som nyckel.
    """
    if not value:
        return False
    mapping = {
        "nationell_säkerhet":   "nationell_sakerhet",
        "nationell_sakerhet":   "nationell_sakerhet",
        "vetenskap_astronomi":  "vetenskap_astronomi",
        "konspirationsteori":   "konspirationsteori",
        "folklig_kultur":       "folklig_kultur",
        "politisk_transparens": "politisk_transparens",
        "okategoriserad":       "okategoriserad",
    }
    return mapping.get(value, "okategoriserad")
