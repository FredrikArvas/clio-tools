"""
odoo_writer.py
Skriver matchningsresultat till Odoo (clio.job.match) efter att en rapport
har skickats till kandidaten.

Helt valfritt — om Odoo-anslutning saknas eller misslyckas loggas en varning
och körningen fortsätter normalt. Kraschsäkert.

Kräver i .env: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # Inga cykliska importer

log = logging.getLogger(__name__)


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
        log.warning(f"odoo_writer: kunde inte spara matchningar i Odoo: {exc}")
