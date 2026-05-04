"""connectors/cyberleninka.py — CyberLeninka (rysk open access). BeautifulSoup scraping."""

from __future__ import annotations

import time
import logging
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://cyberleninka.ru/search"
SLEEP = 2.0

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; clio-research/1.0; mailto:fredrik@arvas.se)",
    "Accept-Language": "ru,en;q=0.9",
}


def search(query: str, max_results: int = 30) -> list[dict]:
    """Sök CyberLeninka. Returnerar normaliserade källobjekt."""
    results = []
    page = 1

    while len(results) < max_results:
        params = {"q": query, "page": page}
        try:
            html = _get(BASE_URL, params)
            items = _parse(html)
            if not items:
                break
            for item in items:
                results.append(item)
                if len(results) >= max_results:
                    break
            page += 1
        except Exception as e:
            logger.warning("CyberLeninka sökning misslyckades (sida %d): %s", page, e)
            break

    return results


def _get(url: str, params: dict) -> str:
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt * 15)
                continue
            r.raise_for_status()
            time.sleep(SLEEP)
            return r.text
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt * 5)
    return ""


def _parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    articles = soup.select("li.search-result")
    results = []

    for art in articles:
        title_tag = art.select_one("h2 a, .title a")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        url = f"https://cyberleninka.ru{href}" if href.startswith("/") else href

        authors_tag = art.select_one(".authors, .author")
        authors = []
        if authors_tag:
            authors = [a.strip() for a in authors_tag.get_text().split(",") if a.strip()][:5]

        year = None
        meta_tag = art.select_one(".meta, .year, time")
        if meta_tag:
            text = meta_tag.get_text()
            import re
            m = re.search(r"\b(19|20)\d{2}\b", text)
            if m:
                year = int(m.group())

        abstract_tag = art.select_one(".abstract, .annotation, p")
        abstract = abstract_tag.get_text(strip=True)[:500] if abstract_tag else None

        journal_tag = art.select_one(".journal, .source")
        journal = journal_tag.get_text(strip=True) if journal_tag else None

        from protocol_loader import source_id as make_id
        results.append({
            "source_id": make_id(title, year, None),
            "title": title,
            "authors": authors,
            "year": year,
            "language": "ru",
            "database": "cyberleninka",
            "region": "RU",
            "abstract": abstract,
            "fulltext_url": url,
            "doi": None,
            "journal": journal,
            "phase_found": None,
            "raw_score": None,
        })

    return results
