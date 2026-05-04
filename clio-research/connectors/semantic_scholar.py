"""connectors/semantic_scholar.py — Semantic Scholar API."""

from __future__ import annotations

import os
import time
import logging
import requests

BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SLEEP = 1.0

logger = logging.getLogger(__name__)

FIELDS = "paperId,title,authors,year,externalIds,abstract,openAccessPdf,publicationVenue,citationCount"


def search(query: str, max_results: int = 50) -> list[dict]:
    """Sök Semantic Scholar. Returnerar normaliserade källobjekt."""
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {"x-api-key": api_key} if api_key else {}

    params = {
        "query": query,
        "limit": min(max_results, 100),
        "fields": FIELDS,
    }

    results = []
    try:
        resp = _get(BASE_URL, params, headers)
        for item in resp.get("data", []):
            src = _normalize(item)
            if src:
                results.append(src)
            if len(results) >= max_results:
                break
    except Exception as e:
        logger.warning("Semantic Scholar sökning misslyckades: %s", e)

    return results


def get_citations(paper_id: str, direction: str = "citations") -> list[str]:
    """Hämta forward (citations) eller backward (references) paper IDs."""
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {"x-api-key": api_key} if api_key else {}

    url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/{direction}"
    params = {"fields": "paperId,title", "limit": 100}

    ids = []
    try:
        resp = _get(url, params, headers)
        for item in resp.get("data", []):
            cited = item.get("citedPaper") or item.get("citingPaper") or {}
            pid = cited.get("paperId")
            if pid:
                ids.append(pid)
    except Exception as e:
        logger.warning("Citation-hämtning misslyckades (%s %s): %s", direction, paper_id, e)

    return ids


def get_paper(paper_id: str) -> dict | None:
    """Hämta ett specifikt paper med full metadata."""
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {"x-api-key": api_key} if api_key else {}

    url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
    params = {"fields": FIELDS}

    try:
        resp = _get(url, params, headers)
        return _normalize(resp)
    except Exception as e:
        logger.warning("Paper-hämtning misslyckades (%s): %s", paper_id, e)
        return None


def _get(url: str, params: dict, headers: dict) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 403:
                logger.warning(
                    "Semantic Scholar 403 — API-nyckel ogiltig eller saknas. "
                    "Registrera ny nyckel på semanticscholar.org/product/api"
                )
                return {}
            if r.status_code == 429:
                wait = 2 ** attempt * 10
                logger.info("Semantic Scholar rate limit — väntar %ds", wait)
                time.sleep(wait)
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

    authors = [a.get("name", "") for a in item.get("authors", [])[:5] if a.get("name")]
    doi = (item.get("externalIds") or {}).get("DOI")
    year = item.get("year")

    pdf = item.get("openAccessPdf") or {}
    venue = item.get("publicationVenue") or {}

    from protocol_loader import source_id as make_id
    return {
        "source_id": make_id(title, year, doi),
        "ss_paper_id": item.get("paperId"),
        "title": title,
        "authors": authors,
        "year": year,
        "language": None,
        "database": "semantic_scholar",
        "region": None,
        "abstract": item.get("abstract"),
        "fulltext_url": pdf.get("url"),
        "doi": doi,
        "journal": venue.get("name"),
        "citation_count": item.get("citationCount"),
        "phase_found": None,
        "raw_score": None,
    }
