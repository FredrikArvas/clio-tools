"""connectors/parapsychology.py — Söker parapsykologiska facktidskrifter via CrossRef ISSN-filter.

Täcker:
  - Journal of Scientific Exploration (JSE)        ISSN 0892-3310
  - Journal of Parapsychology                       ISSN 0022-3387
  - Journal of the Society for Psychical Research   ISSN 0037-1475
  - International Journal of Parapsychology         ISSN 0020-7179

CrossRef stöder ISSN-filter som ger hög precision; titelmatchning hoppar vi över.
"""

from __future__ import annotations

import logging
import time
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.crossref.org/works"
SLEEP = 0.4

JOURNALS = [
    {"name": "Journal of Scientific Exploration",      "issn": "0892-3310"},
    {"name": "Journal of Parapsychology",               "issn": "0022-3387"},
    {"name": "Journal of the Society for Psychical Research", "issn": "0037-1475"},
    {"name": "International Journal of Parapsychology", "issn": "0020-7179"},
]


def search(query: str, max_results: int = 30) -> list[dict]:
    """Sök parapsykologiska tidskrifter via CrossRef ISSN-filter."""
    all_results: list[dict] = []
    per_journal = max(max_results // len(JOURNALS), 5)

    for journal in JOURNALS:
        try:
            results = _search_journal(query, journal["issn"], journal["name"], per_journal)
            all_results.extend(results)
        except Exception as e:
            logger.warning("[parapsychology] %s — sökning misslyckades: %s", journal["name"], e)

    return all_results[:max_results]


def _search_journal(query: str, issn: str, journal_name: str, max_n: int) -> list[dict]:
    params = {
        "query": query,
        "filter": f"issn:{issn}",
        "rows": min(max_n, 50),
        "select": "DOI,title,author,published,abstract,container-title,URL,type",
    }

    resp = _get(BASE_URL, params)
    items = resp.get("message", {}).get("items", [])

    results = []
    for item in items:
        src = _normalize(item, journal_name)
        if src:
            results.append(src)
        if len(results) >= max_n:
            break

    if results:
        logger.info("[parapsychology] %s: %d träffar för '%s'", journal_name, len(results), query)

    return results


def _get(url: str, params: dict) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt * 10)
                continue
            r.raise_for_status()
            time.sleep(SLEEP)
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt * 3)
    return {}


def _normalize(item: dict, journal_name: str) -> dict | None:
    titles = item.get("title") or []
    title = titles[0] if titles else ""
    if not title:
        return None

    authors = []
    for a in item.get("author", [])[:5]:
        given = a.get("given", "")
        family = a.get("family", "")
        name = f"{given} {family}".strip()
        if name:
            authors.append(name)

    doi = item.get("DOI")

    year = None
    pub = item.get("published") or {}
    parts = pub.get("date-parts", [[]])[0]
    if parts:
        year = parts[0]

    from protocol_loader import source_id as make_id
    return {
        "source_id": make_id(title, year, doi),
        "title": title,
        "authors": authors,
        "year": year,
        "language": None,
        "database": "parapsychology",
        "region": None,
        "abstract": item.get("abstract"),
        "fulltext_url": item.get("URL"),
        "doi": doi,
        "journal": journal_name,
        "phase_found": None,
        "raw_score": None,
    }
