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


def load_known_article_ids(env) -> set[str]:
    """
    Hämtar alla kända artikel-IDs från Odoo i en enda bulk-fråga.
    Returnerar ett tomt set om Odoo inte är tillgängligt.

    Används i run.py för att filtrera redan-sedda artiklar INNAN analysen —
    ett anrop istället för N individuella is_seen()-kontroller.
    """
    if env is None:
        return set()
    try:
        rows = env["clio.job.article"].search_read([], ["article_id"])
        ids = {r["article_id"] for r in rows}
        _logger.debug("load_known_article_ids: %d kända artikel-IDs hämtade", len(ids))
        return ids
    except Exception as exc:
        _logger.warning("Kunde inte hämta artikel-IDs från Odoo: %s", exc)
        return set()


def write_articles_to_odoo(env, articles: list[dict]) -> None:
    """
    Skriver analyserade artiklar till clio.job.article i Odoo.

    Varje artikel är en dict med nycklarna:
        article_id, url, title, source, match_score, is_matched,
        published (ISO-str, valfri), body_snippet (str, valfri)

    Kraschsäkert — Odoo är ett extra lager.
    """
    if env is None or not articles:
        return

    Article = env["clio.job.article"]
    now = _utcnow_str()
    created = skipped = failed = 0

    for a in articles:
        # Publicerat datum — konvertera till "YYYY-MM-DD HH:MM:SS" om satt
        published = a.get("published")
        if published:
            try:
                if hasattr(published, "strftime"):
                    published = published.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    published = str(published)[:19].replace("T", " ")
            except Exception:
                published = False

        try:
            Article.create({
                "article_id":   a.get("article_id", ""),
                "url":          a.get("url", ""),
                "title":        (a.get("title", "") or "")[:500],
                "source":       a.get("source", ""),
                "published":    published or False,
                "first_seen":   now,
                "body_snippet": (a.get("body_snippet", "") or "")[:1000],
                "match_score":  int(a.get("match_score", -1)),
                "is_matched":   bool(a.get("is_matched", False)),
            })
            created += 1
        except Exception as exc:
            msg = str(exc).lower()
            if "unik" in msg or "unique" in msg or "uniq" in msg:
                # Parallel körning — annan profil hann skriva artikeln först
                skipped += 1
                _logger.debug("write_articles_to_odoo: skip duplicate %s", a.get("article_id", "")[:12])
            else:
                failed += 1
                _logger.warning("write_articles_to_odoo: fel för %s: %s", a.get("url", "")[:60], exc)

    _logger.info(
        "write_articles_to_odoo: %d skapade, %d skippad (dubblett), %d fel",
        created, skipped, failed,
    )
    if skipped:
        print(f"[clio-job] Artiklar till Odoo: {created} nya, {skipped} redan inlagda av parallell körning.")


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


def write_recruiter_match(profile: dict, matches: list) -> None:
    """
    Skapar clio.recruiter.match-poster i Odoo för rekryterarläge.

    Letar upp clio.recruiter.profile på name — skapar profilen om den saknas.
    Skriver recruiter-specifika fält: target_company, candidate_profile,
    estimated_timeline, contact_hint.

    Args:
        profile: Profildict (från profile_loader.load_profile), profile_type=recruiter
        matches: Lista av MatchedArticle-objekt (från reporter.py)
    """
    if not matches:
        return

    profile_name = (profile.get("name") or "").strip()
    if not profile_name:
        _logger.debug("write_recruiter_match: profile.name saknas — hoppar över")
        return

    try:
        from clio_odoo import connect
    except ImportError:
        _logger.debug("write_recruiter_match: clio_odoo saknas — hoppar över")
        return

    try:
        env = connect()
        Profile = env["clio.recruiter.profile"]
        Match   = env["clio.recruiter.match"]

        existing = Profile.search_read([("name", "=", profile_name)], ["id"], limit=1)
        if existing:
            profile_id = existing[0]["id"]
        else:
            target = profile.get("target_candidate") or {}
            signals = profile.get("trigger_signals") or {}
            profile_id = Profile.create({
                "name":                    profile_name,
                "email":                   profile.get("email", ""),
                "language":                profile.get("language", "sv"),
                "target_role":             target.get("role", ""),
                "target_seniority":        target.get("seniority", ""),
                "target_characteristics":  "\n".join(target.get("characteristics") or []),
                "target_avoid":            "\n".join(target.get("avoid") or []),
                "target_industries":       "\n".join(profile.get("target_industries") or []),
                "trigger_signals_high":    "\n".join(signals.get("high_value") or []),
                "trigger_signals_medium":  "\n".join(signals.get("medium_value") or []),
                "confidential_client":     bool(profile.get("confidential_client", True)),
                "client_hint":             profile.get("client_hint", ""),
            })
            _logger.info("write_recruiter_match: skapade ny profil '%s' (id=%s)", profile_name, profile_id)

        sent_at = _utcnow_str()
        created = 0
        for m in matches:
            article = m.article
            result  = m.result
            Match.create({
                "profile_id":         profile_id,
                "article_url":        getattr(article, "url", "") or "",
                "article_title":      (getattr(article, "title", "") or "")[:500],
                "target_company":     (getattr(result, "target_company", "") or "")[:255],
                "candidate_profile":  (getattr(result, "candidate_profile", "") or "")[:255],
                "signal_type":        (getattr(result, "signal_type", "") or "")[:100],
                "match_score":        int(getattr(result, "match_score", 0)),
                "estimated_timeline": (getattr(result, "estimated_timeline", "") or "")[:100],
                "contact_hint":       (getattr(result, "contact_hint", "") or "")[:255],
                "recommended_action": (getattr(result, "recommended_action", "") or "")[:100],
                "sent_at":            sent_at,
            })
            created += 1

        _logger.info("write_recruiter_match: %d matchning(ar) sparade för '%s'", created, profile_name)

    except Exception as exc:
        _logger.warning("write_recruiter_match: kunde inte spara i Odoo: %s", exc)


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
