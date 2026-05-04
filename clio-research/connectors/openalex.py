"""connectors/openalex.py — OpenAlex REST API (gratis, ingen nyckel)."""

from __future__ import annotations

import os
import time
import logging
import requests

BASE_URL = "https://api.openalex.org/works"
SLEEP = 0.1

logger = logging.getLogger(__name__)


def search(query: str, max_results: int = 50, language: str | None = None) -> list[dict]:
    """Sök OpenAlex. Returnerar normaliserade källobjekt."""
    email = os.getenv("OPENALEX_EMAIL", "")
    params = {
        "search": query,
        "per-page": min(max_results, 200),
        "select": "id,title,authorships,publication_year,language,doi,abstract_inverted_index,primary_location",
    }
    if email:
        params["mailto"] = email

    results = []
    try:
        resp = _get(BASE_URL, params)
        for item in resp.get("results", []):
            src = _normalize(item)
            if src:
                results.append(src)
            if len(results) >= max_results:
                break
    except Exception as e:
        logger.warning("OpenAlex sökning misslyckades: %s", e)

    return results


def _get(url: str, params: dict) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt * 5)
                continue
            r.raise_for_status()
            time.sleep(SLEEP)
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt * 2)
    return {}


def _normalize(item: dict) -> dict | None:
    title = item.get("title") or ""
    if not title:
        return None

    authors = []
    for a in item.get("authorships", [])[:5]:
        name = a.get("author", {}).get("display_name")
        if name:
            authors.append(name)

    doi = (item.get("doi") or "").replace("https://doi.org/", "")
    abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))

    location = item.get("primary_location") or {}
    source = location.get("source") or {}

    from protocol_loader import source_id as make_id
    return {
        "source_id": make_id(title, item.get("publication_year"), doi),
        "title": title,
        "authors": authors,
        "year": item.get("publication_year"),
        "language": item.get("language"),
        "database": "openalex",
        "region": None,
        "abstract": abstract,
        "fulltext_url": location.get("landing_page_url"),
        "doi": doi or None,
        "journal": source.get("display_name"),
        "phase_found": None,
        "raw_score": None,
    }


def _reconstruct_abstract(inverted: dict | None) -> str | None:
    if not inverted:
        return None
    try:
        max_pos = max(pos for positions in inverted.values() for pos in positions)
        words = [""] * (max_pos + 1)
        for word, positions in inverted.items():
            for pos in positions:
                words[pos] = word
        return " ".join(w for w in words if w)
    except Exception:
        return None
