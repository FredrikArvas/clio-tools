"""
source_rss.py
RSS-implementation för clio-agent-job.
Hämtar artiklar via feedparser och normaliserar till Article-dataklassen.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False

import sys as _sys
from pathlib import Path as _Path
_src = str(_Path(__file__).parent)
if _src not in _sys.path:
    _sys.path.insert(0, _src)
from source_base import Article, BaseSource, SourceError  # noqa: E402

_SNIPPET_MAX = 500  # tecken


def _parse_time(t) -> Optional[datetime]:
    """Konverterar feedparser time_struct till datetime (UTC)."""
    if not t:
        return None
    try:
        ts = time.mktime(t)
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def _snippet(entry) -> str:
    """Extraherar första _SNIPPET_MAX tecken ur artikeltext."""
    text = ""
    if hasattr(entry, "summary") and entry.summary:
        text = entry.summary
    elif hasattr(entry, "description") and entry.description:
        text = entry.description
    elif hasattr(entry, "content") and entry.content:
        text = entry.content[0].get("value", "")
    elif entry.get("preamble"):
        text = entry.get("preamble", "")
    elif entry.get("text"):
        text = entry.get("text", "")

    # Rensa enkel HTML
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_SNIPPET_MAX]


class RssSource(BaseSource):
    """Hämtar artiklar från ett RSS-flöde via feedparser."""

    def __init__(self, url: str, name: str = "", **kwargs):
        self.url = url
        self.name = name or url

    def fetch(self) -> list[Article]:
        if not _HAS_FEEDPARSER:
            raise SourceError("feedparser är inte installerat — kör: pip install feedparser")

        try:
            feed = feedparser.parse(self.url)
        except Exception as e:
            raise SourceError(f"Kunde inte hämta RSS från {self.url}: {e}") from e

        if feed.bozo and not feed.entries:
            raise SourceError(f"RSS-parsningsfel för {self.url}: {feed.bozo_exception}")

        articles = []
        for entry in feed.entries:
            url = (getattr(entry, "link", "") or getattr(entry, "id", "")
                   or entry.get("href", ""))
            if not url:
                continue
            title = (getattr(entry, "title", "") or entry.get("filetitle", "")
                     or "(ingen titel)")
            published = _parse_time(getattr(entry, "published_parsed", None))
            snippet = _snippet(entry)

            articles.append(Article(
                url=url,
                title=title,
                source=self.name,
                published=published,
                body_snippet=snippet,
            ))

        return articles
