"""
connectors/cyberleninka.py — CyberLeninka (rysk open access).

R1.0 STATUS: CyberLeninka renderar sökresultat via JavaScript (SPA). Statisk BeautifulSoup-
scraping fungerar inte. Connectorn returnerar tomma resultat och loggar en tydlig varning.
R1.5: Implementera via Playwright/Selenium eller undersök inofficiell JSON-API-endpoint.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def search(query: str, max_results: int = 30) -> list[dict]:
    """
    Sök CyberLeninka.
    R1.0: Ej implementerat — CyberLeninka kräver JavaScript-rendering (SPA).
    Returnerar tom lista med varning.
    """
    logger.warning(
        "CyberLeninka: JS-rendering krävs — ej tillgänglig i R1.0. "
        "Implementeras med Playwright i R1.5."
    )
    return []


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
