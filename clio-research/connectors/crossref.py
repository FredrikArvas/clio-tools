"""connectors/crossref.py — CrossRef REST API (gratis, ingen nyckel)."""

from __future__ import annotations

import time
import logging
import requests

BASE_URL = "https://api.crossref.org/works"
SLEEP = 0.3

logger = logging.getLogger(__name__)


def search(query: str, max_results: int = 50) -> list[dict]:
    """Sök CrossRef. Returnerar normaliserade källobjekt."""
    params = {
        "query": query,
        "rows": min(max_results, 100),
        "select": "DOI,title,author,published,abstract,container-title,URL,type",
    }

    results = []
    try:
        resp = _get(BASE_URL, params)
        for item in resp.get("message", {}).get("items", []):
            src = _normalize(item)
            if src:
                results.append(src)
            if len(results) >= max_results:
                break
    except Exception as e:
        logger.warning("CrossRef sökning misslyckades: %s", e)

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


def _normalize(item: dict) -> dict | None:
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

    containers = item.get("container-title") or []
    journal = containers[0] if containers else None

    from protocol_loader import source_id as make_id
    return {
        "source_id": make_id(title, year, doi),
        "title": title,
        "authors": authors,
        "year": year,
        "language": None,
        "database": "crossref",
        "region": None,
        "abstract": item.get("abstract"),
        "fulltext_url": item.get("URL"),
        "doi": doi,
        "journal": journal,
        "phase_found": None,
        "raw_score": None,
    }
