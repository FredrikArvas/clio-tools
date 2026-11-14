"""connectors/crossref.py — CrossRef REST API (gratis, ingen nyckel)."""

from __future__ import annotations

import sys
import time
import logging
from pathlib import Path

import requests

from .metadata import crossref_affiliations, crossref_source_type

sys.path.insert(0, str(Path(__file__).parent.parent))
from contact import contact_email, redact  # noqa: E402

BASE_URL = "https://api.crossref.org/works"
SLEEP = 0.3
USER_AGENT = "clio-research/2.0"
SELECT_FIELDS = "DOI,title,author,published,abstract,container-title,URL,type,is-referenced-by-count"

logger = logging.getLogger(__name__)


def search(query: str, max_results: int = 50) -> list[dict]:
    """Sök CrossRef. Returnerar normaliserade källobjekt."""
    params = {
        "query": query,
        "rows": min(max_results, 100),
        "select": SELECT_FIELDS,
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
        logger.warning("CrossRef sökning misslyckades: %s", redact(e))

    return results


def _headers() -> dict:
    """User-Agent för anropet. Kontaktadressen (polite pool) går i huvudet, aldrig i URL:en,
    så att den inte kan hamna i felmeddelanden. Saknas adressen skickas ingen."""
    email = contact_email()
    if not email:
        return {"User-Agent": USER_AGENT}
    return {"User-Agent": f"{USER_AGENT} (mailto:{email})"}


def _get(url: str, params: dict) -> dict:
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=_headers(), timeout=30)
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

    # CrossRef har inget landsfält; land läses bara ur en affiliering som namnger landet.
    country_codes, institutions = crossref_affiliations(item.get("author"))
    cited = item.get("is-referenced-by-count")

    from protocol_loader import source_id as make_id
    return {
        "source_id": make_id(title, year, doi),
        "title": title,
        "authors": authors,
        "year": year,
        "language": None,
        "database": "crossref",
        "external_id": doi.lower() if doi else None,
        "source_type": crossref_source_type(item.get("type")),
        "country_codes": country_codes,
        "institutions": institutions,
        "citation_count": cited if isinstance(cited, int) else None,
        "region": country_codes[0] if country_codes else None,
        "abstract": item.get("abstract"),
        "fulltext_url": item.get("URL"),
        "doi": doi,
        "journal": journal,
        "phase_found": None,
        "raw_score": None,
    }
