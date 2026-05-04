"""connectors/core_api.py — CORE API (open access fulltext)."""

from __future__ import annotations

import os
import time
import logging
import requests

BASE_URL = "https://api.core.ac.uk/v3/search/works"
SLEEP = 0.5

logger = logging.getLogger(__name__)


def search(query: str, max_results: int = 50) -> list[dict]:
    """Sök CORE. Returnerar normaliserade källobjekt."""
    api_key = os.getenv("CORE_API_KEY", "")
    if not api_key:
        logger.warning("CORE_API_KEY saknas — CORE-sökning hoppas över")
        return []

    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "q": query,
        "limit": min(max_results, 100),
        "stats": "false",
    }

    results = []
    try:
        resp = _get(BASE_URL, params, headers)
        for item in resp.get("results", []):
            src = _normalize(item)
            if src:
                results.append(src)
            if len(results) >= max_results:
                break
    except Exception as e:
        logger.warning("CORE sökning misslyckades: %s", e)

    return results


def _get(url: str, params: dict, headers: dict) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
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
    title = item.get("title") or ""
    if not title:
        return None

    authors = []
    for a in item.get("authors", [])[:5]:
        name = a.get("name") if isinstance(a, dict) else str(a)
        if name:
            authors.append(name)

    doi = item.get("doi")
    year = item.get("yearPublished")
    if isinstance(year, str):
        year = int(year) if year.isdigit() else None

    from protocol_loader import source_id as make_id
    return {
        "source_id": make_id(title, year, doi),
        "title": title,
        "authors": authors,
        "year": year,
        "language": item.get("language", {}).get("name") if isinstance(item.get("language"), dict) else item.get("language"),
        "database": "core",
        "region": None,
        "abstract": item.get("abstract"),
        "fulltext_url": item.get("downloadUrl") or item.get("sourceFulltextUrls", [None])[0],
        "doi": doi,
        "journal": item.get("journals", [{}])[0].get("title") if item.get("journals") else None,
        "phase_found": None,
        "raw_score": None,
    }
