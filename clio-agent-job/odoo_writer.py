"""
odoo_writer.py
Skriver körningsresultat från clio-agent-job till Odoo:
  - clio.job.match       — en post per matchad artikel per kandidat
  - clio.tool.heartbeat  — en post per körning (upsert på tool_name)

Kraschsäkert: Odoo är ett extra lager, inte ett hårdberoende.
Om anslutning saknas eller misslyckas loggas en varning och körningen fortsätter.

Kräver i .env: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)
log = _logger  # Bakåtkompatibelt alias

TOOL_NAME = "clio-agent-job"


def _utcnow_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_odoo_env():
    """Returnerar en ansluten OdooConnector, eller None vid fel."""
    try:
        from clio_odoo import connect
        return connect()
    except Exception as exc:
        _logger.warning("Odoo-anslutning misslyckades: %s", exc)
        return None


def write_matches_to_odoo(profile: dict, matches: list) -> None:
    """
    Skapar clio.job.match-poster i Odoo för varje matchad artikel.

    Args:
        profile: Profildict (från profile_loader.load_profile)
        matches: Lista av MatchedArticle-objekt (från reporter.py)
    """
    if not matches:
        return

    email = profile.get("email", "").strip()
    if not email:
        log.debug("odoo_writer: email saknas i profil — hoppar över Odoo-skrivning")
        return

    try:
        from clio_odoo import connect
    except ImportError:
        log.debug("odoo_writer: clio_odoo saknas — hoppar över Odoo-skrivning")
        return

    try:
        env = connect()
        Partner = env["res.partner"]

        partners = Partner.search_read(
            [("email", "=", email), ("clio_job_watch", "=", True)],
            ["clio_job_profile_ids"],
        )
        if not partners:
            log.debug(f"odoo_writer: ingen aktiv partner för {email} — hoppar över")
            return

        profile_ids = partners[0].get("clio_job_profile_ids") or []
        if not profile_ids:
            log.debug(f"odoo_writer: partner {email} saknar clio.job.profile — hoppar över")
            return

        profile_id = profile_ids[0]
        Match = env["clio.job.match"]
        sent_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        created = 0
        for m in matches:
            # MatchedArticle har .article (Article) och .result (AnalysisResult)
            article = m.article
            result  = m.result
            Match.create({
                "profile_id":         profile_id,
                "article_url":        getattr(article, "url", "") or "",
                "article_title":      getattr(article, "title", "") or "",
                "signal_type":        getattr(result, "signal_type", "") or "",
                "match_score":        int(getattr(result, "match_score", 0)),
                "sent_at":            sent_at,
                "recommended_action": getattr(result, "recommended_action", "") or "",
            })
            created += 1

        log.info(f"odoo_writer: {created} matchning(ar) sparade för {email}")

    except Exception as exc:  # noqa: BLE001
        # Aldrig krasch — Odoo är ett extra lager, inte ett hårdberoende
        _logger.warning("odoo_writer: kunde inte spara matchningar i Odoo: %s", exc)


def write_heartbeat(
    env,
    status: str,
    items_processed: int = 0,
    message: str = "",
) -> None:
    """
    Upsert: uppdaterar eller skapar clio.tool.heartbeat för clio-agent-job.

    Args:
        env:             OdooConnector (från get_odoo_env())
        status:          'ok', 'warning' eller 'error'
        items_processed: Antal artiklar/profiler som bearbetades
        message:         Kort sammanfattning av körningen
    """
    if env is None:
        return
    try:
        Heartbeat = env["clio.tool.heartbeat"]
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
        _logger.warning("Kunde inte skriva heartbeat: %s", exc)
