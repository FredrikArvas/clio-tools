"""
sources/wikipedia.py — WikipediaSource: hämtar personsammanfattning från Wikipedia.

Söker på sv.wikipedia.org först, sedan en.wikipedia.org.
Rate limit: 0.5 sek mellan anrop (ADR-010).
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "clio-research/1.0 (AIAB; fredrik@arvas.se)"
RATE_LIMIT_SLEEP = 0.5  # sekunder (ADR-010)

_SUMMARY_URL_SV = "https://sv.wikipedia.org/api/rest_v1/page/summary/{title}"
_SUMMARY_URL_EN = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_SEARCH_URL_SV = "https://sv.wikipedia.org/w/api.php"
_SEARCH_URL_EN = "https://en.wikipedia.org/w/api.php"


@dataclass
class WikipediaResult:
    found: bool = False
    language: Optional[str] = None          # "sv" eller "en"
    title: Optional[str] = None
    url: Optional[str] = None
    sammanfattning: Optional[str] = None    # extract från Wikipedia
    fodelsedag: Optional[str] = None        # om tillgänglig i summary
    dodsdag: Optional[str] = None
    error: Optional[str] = None


class WikipediaSource:
    """
    Söker och hämtar personsammanfattning från Wikipedia (sv + en).

    Användning:
        ws = WikipediaSource()
        result = ws.get_by_url("https://sv.wikipedia.org/wiki/Dag_Arvas")
        result = ws.search("Dag Arvas")
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _get(self, url: str, params: Optional[dict] = None, max_retries: int = 3) -> Optional[requests.Response]:
        """GET med retry och rate limit."""
        for attempt in range(max_retries):
            try:
                resp = self._session.get(url, params=params, timeout=15)
                time.sleep(RATE_LIMIT_SLEEP)  # ADR-010
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                logger.warning("Wikipedia-anrop misslyckades (försök %d/%d): %s", attempt + 1, max_retries, exc)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    def get_by_url(self, wikipedia_url: str) -> WikipediaResult:
        """
        Hämtar sammanfattning från en känd Wikipedia-URL.
        Fungerar för sv och en Wikipedia.
        """
        if "sv.wikipedia.org" in wikipedia_url:
            lang = "sv"
            title = wikipedia_url.rstrip("/").split("/wiki/")[-1]
            summary_url = _SUMMARY_URL_SV.format(title=title)
        elif "en.wikipedia.org" in wikipedia_url:
            lang = "en"
            title = wikipedia_url.rstrip("/").split("/wiki/")[-1]
            summary_url = _SUMMARY_URL_EN.format(title=title)
        else:
            return WikipediaResult(found=False, error=f"Okänd Wikipedia-URL: {wikipedia_url}")

        resp = self._get(summary_url)
        if resp is None:
            return WikipediaResult(found=False)

        data = resp.json()
        return self._parse_summary(data, lang)

    def search(self, name: str) -> WikipediaResult:
        """
        Söker en person på namn. Försöker sv.wikipedia.org först, sedan en.wikipedia.org.

        Returnerar WikipediaResult med found=False om ingen träff.
        """
        # Försök sv
        result = self._search_lang(name, "sv")
        if result.found:
            return result
        # Försök en
        return self._search_lang(name, "en")

    def _search_lang(self, name: str, lang: str) -> WikipediaResult:
        """Söker en person i en specifik språkversion av Wikipedia."""
        search_url = _SEARCH_URL_SV if lang == "sv" else _SEARCH_URL_EN
        params = {
            "action": "query",
            "list": "search",
            "srsearch": name,
            "format": "json",
            "srlimit": 3,
        }
        resp = self._get(search_url, params=params)
        if resp is None:
            return WikipediaResult(found=False, error="Nätverksfel")

        data = resp.json()
        hits = data.get("query", {}).get("search", [])
        if not hits:
            return WikipediaResult(found=False)

        # Kräv att artikelns titel innehåller åtminstone ett ord från söknamnet
        # (förhindrar falska träffar där en sökning ger en icke-personartikel)
        name_words = set(name.lower().split())
        for hit in hits:
            title = hit["title"]
            title_words = set(title.lower().split())
            if name_words & title_words:  # minst ett gemensamt ord
                summary_url = (_SUMMARY_URL_SV if lang == "sv" else _SUMMARY_URL_EN).format(
                    title=title.replace(" ", "_")
                )
                resp2 = self._get(summary_url)
                if resp2 is None:
                    continue
                result = self._parse_summary(resp2.json(), lang)
                if result.found:
                    return result

        return WikipediaResult(found=False)

    def _parse_summary(self, data: dict, lang: str) -> WikipediaResult:
        """Tolkar Wikipedia REST API summary-svar."""
        if data.get("type") == "disambiguation":
            return WikipediaResult(found=False)

        title = data.get("title")
        url = data.get("content_urls", {}).get("desktop", {}).get("page")
        extract = data.get("extract") or data.get("description")

        if not title:
            return WikipediaResult(found=False)

        # Extrahera ev. datum från summary (best-effort, Wikipedia API har inte strukturerade datum)
        result = WikipediaResult(
            found=True,
            language=lang,
            title=title,
            url=url,
            sammanfattning=extract,
        )
        return result
