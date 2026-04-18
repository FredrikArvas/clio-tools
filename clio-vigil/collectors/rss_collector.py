"""
clio-vigil — collectors/rss_collector.py
=========================================
Hämtar nya poster från RSS-flöden definierade i domän-YAML.
Skriver discovered-poster till orchestrator (vigil_items).

Designbeslut:
  - feedparser som enda beroende (stdlib-nära, stabil)
  - Dubblettkontroll via upsert_item (URL som nyckel)
  - Beskrivning = title + description för filtrering
  - Publiceringstid normaliseras till ISO 8601 UTC
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import feedparser
except ImportError:
    feedparser = None


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _normalize_time(entry) -> Optional[str]:
    """Konverterar feedparser-tid till ISO 8601 UTC-sträng."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            pass
    return None


def _extract_description(entry) -> str:
    """Sammanfogar titel och summary för filtreringssyfte."""
    parts = []
    if hasattr(entry, "title") and entry.title:
        parts.append(entry.title)
    if hasattr(entry, "summary") and entry.summary:
        # Strippa HTML-taggar enkelt
        import re
        clean = re.sub(r"<[^>]+>", " ", entry.summary)
        parts.append(clean[:500])
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Huvud-collector
# ---------------------------------------------------------------------------

def collect_rss(conn, domain_config: dict) -> dict:
    """
    Hämtar alla RSS-källor definierade i domain_config.
    Returnerar räknare: {discovered: N, skipped: N, errors: N}
    """
    if feedparser is None:
        raise ImportError("feedparser saknas — kör: pip install feedparser")

    from orchestrator import upsert_item

    domain_id = domain_config["domain_id"]
    sources = domain_config.get("sources", {}).get("rss", [])
    counts = {"discovered": 0, "skipped": 0, "errors": 0}

    for source in sources:
        url = source["url"]
        name = source.get("name", url)
        maturity = source.get("maturity", "tidig")
        weight = source.get("weight", 1.0)

        logger.info(f"RSS: hämtar {name} ({url})")

        try:
            feed = feedparser.parse(url)

            if feed.bozo and not feed.entries:
                logger.warning(f"RSS-fel för {name}: {feed.bozo_exception}")
                counts["errors"] += 1
                continue

            for entry in feed.entries:
                item_url = getattr(entry, "link", None)
                if not item_url:
                    continue

                title = getattr(entry, "title", "")
                description = _extract_description(entry)
                published_at = _normalize_time(entry)

                item_id = upsert_item(
                    conn,
                    url=item_url,
                    domain=domain_id,
                    source_type="rss",
                    source_name=name,
                    source_maturity=maturity,
                    source_weight=weight,
                    title=title,
                    description=description,
                    published_at=published_at,
                    raw_metadata=json.dumps({
                        "feed_url": url,
                        "feed_title": feed.feed.get("title", ""),
                    })
                )

                if item_id:
                    counts["discovered"] += 1
                else:
                    counts["skipped"] += 1

        except Exception as e:
            logger.error(f"Fel vid hämtning av {name}: {e}")
            counts["errors"] += 1

    logger.info(
        f"RSS-insamling klar [{domain_id}]: "
        f"{counts['discovered']} nya, {counts['skipped']} kända, {counts['errors']} fel"
    )
    return counts
