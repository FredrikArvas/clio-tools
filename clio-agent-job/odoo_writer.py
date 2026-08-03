"""
odoo_writer.py
Skriver korningsresultat fran clio-agent-job till Odoo:
  - clio.job.match       -- en post per matchad artikel per kandidat (jobbsokarläge)
  - clio.recruiter.match -- en post per matchad artikel per rekryterarprofil
  - clio.tool.heartbeat  -- en post per korning (upsert pa tool_name)
  - clio.recruiter.article_analysis -- analyscache per artikel x profil

Kraschsakert: Odoo ar ett extra lager, inte ett hardberoende.
Om anslutning saknas eller misslyckas loggas en varning och korningen fortsatter.

Kraver i .env: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)
log = _logger  # Bakatkompatiibelt alias

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
    Hamtar alla kanda artikel-IDs fran Odoo i en enda bulk-fraga.
    Returnerar ett tomt set om Odoo inte ar tillgangligt.

    Anvands i run.py for att filtrera redan-sedda artiklar INNAN analysen --
    ett anrop istallet for N individuella is_seen()-kontroller.
    """
    if env is None:
        return set()
    try:
        rows = env["clio.job.article"].search_read([], ["article_id"])
        ids = {r["article_id"] for r in rows}
        _logger.debug("load_known_article_ids: %d kanda artikel-IDs hamtade", len(ids))
        return ids
    except Exception as exc:
        _logger.warning("Kunde inte hamta artikel-IDs fran Odoo: %s", exc)
        return set()


def write_articles_to_odoo(env, articles: list[dict]) -> None:
    """
    Skriver analyserade artiklar till clio.job.article i Odoo.

    Varje artikel ar en dict med nycklarna:
        article_id, url, title, source, match_score, is_matched,
        published (ISO-str, valfri), body_snippet (str, valfri)

    Kraschsakert -- Odoo ar ett extra lager.
    """
    if env is None or not articles:
        return

    Article = env["clio.job.article"]
    now = _utcnow_str()
    created = skipped = failed = 0

    for a in articles:
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
                skipped += 1
                _logger.debug("write_articles_to_odoo: skip duplicate %s", a.get("article_id", "")[:12])
            else:
                failed += 1
                _logger.warning("write_articles_to_odoo: fel for %s: %s", a.get("url", "")[:60], exc)

    _logger.info(
        "write_articles_to_odoo: %d skapade, %d skippad (dubblett), %d fel",
        created, skipped, failed,
    )
    if skipped:
        print(f"[clio-job] Artiklar till Odoo: {created} nya, {skipped} redan inlagda av parallell korning.")


_RECRUITER_SIGNAL_MAP = {
    "plattformsbyte":   "outsourcing",
    "outsourcing":      "outsourcing",
    "varsel":           "varsel",
    "forvärv":          "artikel_generell",
    "s4hana_migration": "s4hana_migration",
    "cio_byte":         "cio_byte",
    "besparingspaket":  "artikel_generell",
    "ovrigt":           "artikel_generell",
    "ingen":            "artikel_generell",
}


def write_recruiter_matches_to_odoo(profile: dict, matches: list) -> None:
    """
    Skapar clio.recruiter.match-poster for varje matchad artikel.
    Kraver att profilen har _odoo_id (satts av load_recruiter_profiles).
    """
    if not matches:
        return

    profile_id = profile.get("_odoo_id")
    if not profile_id:
        _logger.debug("write_recruiter_matches: _odoo_id saknas i profil -- hoppar over")
        return

    try:
        from clio_odoo import connect
        env = connect()
    except Exception as exc:
        _logger.warning("write_recruiter_matches: Odoo-anslutning misslyckades: %s", exc)
        return

    Match = env["clio.recruiter.match"]
    sent_at = _utcnow_str()
    created = 0

    for m in matches:
        result = m.result
        raw_signal = getattr(result, "signal_type", "ovrigt") or "ovrigt"
        mapped_signal = _RECRUITER_SIGNAL_MAP.get(raw_signal, "artikel_generell")

        try:
            Match.create({
                "profile_id":         profile_id,
                "signal_type":        mapped_signal,
                "match_score":        int(getattr(result, "match_score", 0)),
                "recommended_action": getattr(result, "recommended_action", "") or "",
                "contact_hint":       getattr(result, "contact_hint", "") or "",
                "sent_at":            sent_at,
            })
            created += 1
        except Exception as exc:
            _logger.warning("write_recruiter_matches: fel vid skapande: %s", exc)

    _logger.info("write_recruiter_matches: %d post(er) sparade for profil %d", created, profile_id)


def write_matches_to_odoo(profile: dict, matches: list) -> None:
    """
    Dispatcher: recruiter-profiler -> clio.recruiter.match,
    jobbsokar-profiler -> clio.job.match.
    """
    if not matches:
        return

    if profile.get("profile_type") == "recruiter":
        write_recruiter_matches_to_odoo(profile, matches)
        return

    email = profile.get("email", "").strip()
    if not email:
        log.debug("odoo_writer: email saknas i profil -- hoppar over Odoo-skrivning")
        return

    try:
        from clio_odoo import connect
    except ImportError:
        log.debug("odoo_writer: clio_odoo saknas -- hoppar over Odoo-skrivning")
        return

    try:
        env = connect()
        Partner = env["res.partner"]

        partners = Partner.search_read(
            [("email", "=", email), ("clio_job_watch", "=", True)],
            ["clio_job_profile_ids"],
        )
        if not partners:
            log.debug(f"odoo_writer: ingen aktiv partner for {email} -- hoppar over")
            return

        profile_ids = partners[0].get("clio_job_profile_ids") or []
        if not profile_ids:
            log.debug(f"odoo_writer: partner {email} saknar clio.job.profile -- hoppar over")
            return

        profile_id = profile_ids[0]
        Match = env["clio.job.match"]
        sent_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        created = 0
        for m in matches:
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

        log.info(f"odoo_writer: {created} matchning(ar) sparade for {email}")

    except Exception as exc:  # noqa: BLE001
        _logger.warning("odoo_writer: kunde inte spara matchningar i Odoo: %s", exc)


def write_heartbeat(
    env,
    status: str,
    items_processed: int = 0,
    message: str = "",
) -> None:
    """
    Upsert: uppdaterar eller skapar clio.tool.heartbeat for clio-agent-job.
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
        _logger.info("Heartbeat: %s -> %s", TOOL_NAME, status)
    except Exception as exc:
        _logger.warning("Kunde inte skriva heartbeat: %s", exc)


# ---------------------------------------------------------------------------
# Analyscache per artikel x profil (clio.recruiter.article_analysis)
# ---------------------------------------------------------------------------

def get_cached_analysis(env, article_id: str, profile_id: int):
    """
    Soker clio.recruiter.article_analysis pa (article_id, profile_id).
    Returnerar ett AnalysisResult-kompatibelt objekt, eller None vid cache-miss.
    """
    if env is None:
        return None
    try:
        rows = env["clio.recruiter.article_analysis"].search_read(
            [("article_id", "=", article_id), ("profile_id", "=", profile_id)],
            ["match_score", "signal_type", "recommended_action", "contact_hint"],
            limit=1,
        )
        if not rows:
            return None
        r = rows[0]
        from analyzer import AnalysisResult
        return AnalysisResult(
            article_id         = article_id,
            signal_type        = r.get("signal_type") or "ingen",
            match_score        = int(r.get("match_score") or 0),
            recommended_action = r.get("recommended_action") or "avsta",
            contact_hint       = r.get("contact_hint") or "",
        )
    except Exception as exc:
        _logger.debug("get_cached_analysis: miss/fel for %s: %s", article_id[:12], exc)
        return None


def write_analysis_cache(env, article_id: str, profile_id: int, result) -> None:
    """
    Sparar ett AnalysisResult till clio.recruiter.article_analysis.
    Kraschsakert -- hoppar over tyst vid fel (inklusive dubbletter).
    """
    if env is None:
        return
    try:
        env["clio.recruiter.article_analysis"].create({
            "article_id":         article_id,
            "profile_id":         profile_id,
            "match_score":        int(getattr(result, "match_score", 0)),
            "signal_type":        getattr(result, "signal_type", "") or "",
            "recommended_action": getattr(result, "recommended_action", "") or "",
            "contact_hint":       getattr(result, "contact_hint", "") or "",
            "analyzed_at":        _utcnow_str(),
        })
    except Exception as exc:
        msg = str(exc).lower()
        if "unik" in msg or "unique" in msg or "uniq" in msg:
            _logger.debug(
                "write_analysis_cache: dubblett for %s/profil %d -- ignoreras",
                article_id[:12], profile_id,
            )
        else:
            _logger.warning("write_analysis_cache: fel for %s: %s", article_id[:12], exc)
