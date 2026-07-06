"""
clio-vigil — collectors/google_news_collector.py
=================================================
Hämtar trending-artiklar från Google News RSS för konfigurerade söktermer.
Används som prioriteringssignal, inte som primär datakälla.

Flöde:
  sökterm → Google News RSS → followad redirect-URL → upsert_item med google_trending=True

Designbeslut:
  - Följer Google-redirects med HEAD-request (timeout 5 s) för att få riktig URL
  - Om redirect misslyckas: sparas Google-URL:en som fallback (undviker datförlust)
  - Items markeras med "google_trending": True i raw_metadata
  - Dubbletter mot befintliga vigil_items ignoreras (upsert_item hanterar det)
  - Ingen author-extraktion — Google News-feed innehåller inte byline
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

try:
    import feedparser
except ImportError:
    feedparser = None

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"
REDIRECT_TIMEOUT = 5   # sekunder per HEAD-request


def _resolve_url(google_url: str) -> str:
    """Följer Google News-redirect och returnerar riktig artikel-URL."""
    if not _HAS_REQUESTS:
        return google_url
    try:
        r = requests.head(google_url, allow_redirects=True, timeout=REDIRECT_TIMEOUT)
        if r.url and r.url != google_url:
            return r.url
    except Exception:
        pass
    return google_url


def _google_news_url(query: str, lang: str = "en", country: str = "US") -> str:
    params = {
        "q":    query,
        "hl":   lang,
        "gl":   country,
        "ceid": f"{country}:{lang}",
    }
    return f"{GOOGLE_NEWS_RSS_BASE}?{urlencode(params)}"


def collect_google_news(conn, domain_config: dict) -> dict:
    """
    Hämtar Google News-trender för domänens konfigurerade queries.
    Returnerar counts: discovered / skipped / errors.

    Förväntat YAML-format under sources.google_news:
      google_news:
        lang: en
        country: US
        weight: 1.5
        queries:
          - "UAP disclosure"
          - "UFO military"
    """
    if feedparser is None:
        logger.error("feedparser saknas — google_news_collector kan inte köra")
        return {"discovered": 0, "skipped": 0, "errors": 1}

    gn_config = domain_config.get("sources", {}).get("google_news")
    if not gn_config:
        return {"discovered": 0, "skipped": 0, "errors": 0}

    from orchestrator import upsert_item

    queries  = gn_config.get("queries", [])
    lang     = gn_config.get("lang", "en")
    country  = gn_config.get("country", "US")
    weight   = float(gn_config.get("weight", 1.5))
    domain   = domain_config.get("domain_id", "unknown")

    counts = {"discovered": 0, "skipped": 0, "errors": 0}

    for query in queries:
        url = _google_news_url(query, lang, country)
        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            logger.error("Google News-hämtning misslyckades för '%s': %s", query, exc)
            counts["errors"] += 1
            continue

        for entry in feed.entries:
            try:
                google_url = entry.get("link", "")
                if not google_url:
                    counts["skipped"] += 1
                    continue

                real_url = _resolve_url(google_url)

                title       = getattr(entry, "title", "") or ""
                source_name = ""
                if hasattr(entry, "source") and entry.source:
                    source_name = entry.source.get("title", "") or ""
                if not source_name:
                    source_name = f"Google News ({query})"

                published_at: Optional[str] = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        published_at = dt.isoformat()
                    except Exception:
                        pass

                item_id = upsert_item(
                    conn,
                    url=real_url,
                    domain=domain,
                    source_type="google_news",
                    source_name=source_name,
                    source_maturity="etablerad",
                    source_weight=weight,
                    title=title,
                    description=title,
                    published_at=published_at,
                    raw_metadata=json.dumps({
                        "google_trending": True,
                        "google_query":    query,
                        "google_url":      google_url,
                        "source_name":     source_name,
                    }),
                )

                if item_id:
                    counts["discovered"] += 1
                else:
                    counts["skipped"] += 1

            except Exception as exc:
                logger.error("Fel vid Google News-post (query='%s'): %s", query, exc)
                counts["errors"] += 1

    logger.info(
        "Google News [%s]: %d nya, %d kända, %d fel (%d queries)",
        domain, counts["discovered"], counts["skipped"], counts["errors"], len(queries),
    )
    return counts
