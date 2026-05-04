"""connectors/jstage.py — J-STAGE (japansk vetenskaplig plattform). REST API, ingen nyckel."""

from __future__ import annotations

import time
import logging
import requests
import xml.etree.ElementTree as ET

BASE_URL = "https://api.jstage.jst.go.jp/searchapi/do"
SLEEP = 1.0

logger = logging.getLogger(__name__)


def search(query: str, max_results: int = 30, lang: str = "ja") -> list[dict]:
    """Sök J-STAGE via Opensearch API. Returnerar normaliserade källobjekt."""
    params = {
        "global_id": "JST.JSTAGE",
        "text": query,
        "count": min(max_results, 100),
        "lang": lang,
    }

    results = []
    try:
        xml_text = _get(BASE_URL, params)
        results = _parse(xml_text, max_results)
    except Exception as e:
        logger.warning("J-STAGE sökning misslyckades: %s", e)

    return results


def _get(url: str, params: dict) -> str:
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt * 10)
                continue
            r.raise_for_status()
            time.sleep(SLEEP)
            return r.text
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt * 3)
    return ""


def _parse(xml_text: str, max_results: int) -> list[dict]:
    if not xml_text:
        return []

    results = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns):
            title = _text(entry, "atom:title", ns) or ""
            if not title:
                continue

            authors = []
            for author in entry.findall("atom:author", ns):
                name = _text(author, "atom:name", ns)
                if name:
                    authors.append(name)

            link_el = entry.find("atom:link[@rel='alternate']", ns)
            url = link_el.get("href") if link_el is not None else None

            year = None
            published = _text(entry, "atom:published", ns) or ""
            if published:
                year_str = published[:4]
                year = int(year_str) if year_str.isdigit() else None

            summary = _text(entry, "atom:summary", ns)

            from protocol_loader import source_id as make_id
            results.append({
                "source_id": make_id(title, year, None),
                "title": title,
                "authors": authors[:5],
                "year": year,
                "language": "ja",
                "database": "jstage",
                "region": "JP",
                "abstract": summary,
                "fulltext_url": url,
                "doi": None,
                "journal": None,
                "phase_found": None,
                "raw_score": None,
            })

            if len(results) >= max_results:
                break

    except ET.ParseError as e:
        logger.warning("J-STAGE XML-parsning misslyckades: %s", e)

    return results


def _text(el: ET.Element, tag: str, ns: dict) -> str | None:
    child = el.find(tag, ns)
    return child.text.strip() if child is not None and child.text else None
