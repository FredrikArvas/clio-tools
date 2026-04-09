"""
sources/source_familjesidan_rss.py — RSS-läsare för familjesidan.se

DEPRECATED 0.2.0
================
Verifiering 2026-04-08 visade att familjesidan.se inte exponerar publika
RSS-flöden. Denna adapter behålls för framtiden om RSS skulle dyka upp,
men den används inte längre i sources.yaml. Den primära familjesidan-
adaptern är nu source_familjesidan_html.FamiljesidanHtmlSource.

Om RSS_URLS sätts i .env och denna källa aktiveras manuellt i sources.yaml
fungerar den fortfarande.
"""

from __future__ import annotations

import os
from typing import Optional

try:
    import feedparser
except ImportError:
    raise ImportError("feedparser saknas. Kör: pip install feedparser")

from dotenv import load_dotenv
load_dotenv(override=True)

from matcher import Announcement
from sources.source_base import ObituarySource, SourceError
from sources.parsers import (
    extract_birth_year,
    extract_location,
    parse_publication_date,
    clean_name,
)


def _get_rss_urls() -> list[str]:
    raw = os.getenv("RSS_URLS", "")
    if raw.strip():
        return [u.strip() for u in raw.split(",") if u.strip()]
    return []


def _parse_entry(entry) -> Optional[Announcement]:
    try:
        title = getattr(entry, "title", "") or ""
        summary = getattr(entry, "summary", "") or ""
        link = getattr(entry, "link", "") or ""
        entry_id = getattr(entry, "id", link) or link

        if not title or not link:
            return None

        full_text = f"{title} {summary}"
        return Announcement(
            id=entry_id,
            namn=clean_name(title),
            fodelsear=extract_birth_year(full_text),
            hemort=extract_location(full_text),
            url=link,
            publiceringsdatum=parse_publication_date(entry),
            raw_title=title,
        )
    except Exception as e:
        print(f"[familjesidan-rss] Kunde inte parsa entry: {e}")
        return None


class FamiljesidanRssSource(ObituarySource):
    """DEPRECATED: RSS-läsare för familjesidan.se. Behålls för framtiden."""

    name = "familjesidan.se (RSS)"

    def __init__(self, rss_urls: Optional[list[str]] = None, **_unused):
        self.rss_urls = rss_urls or _get_rss_urls()

    def fetch(self) -> list[Announcement]:
        announcements: list[Announcement] = []
        for url in self.rss_urls:
            try:
                feed = feedparser.parse(url)
                status = getattr(feed, "status", 0)
                if status not in (0, 200, 301, 302):
                    raise SourceError(f"HTTP {status} från {url}")
                for entry in feed.entries:
                    ann = _parse_entry(entry)
                    if ann:
                        announcements.append(ann)
            except SourceError:
                raise
            except Exception as e:
                raise SourceError(f"Fel vid hämtning av {url}: {e}") from e
        return announcements


# Bakåtkompatibel alias så ev. gammal kod inte bryts
FamiljesidanSource = FamiljesidanRssSource
