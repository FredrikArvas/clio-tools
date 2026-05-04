"""
sources/wikidata.py — WikidataSource: söker persondata via Wikidata SPARQL.

Rate limit: 1 req/sekund (ADR-010).
User-Agent: clio-research/1.0 (AIAB; fredrik@arvas.se)
Om > 1 kandidat returneras: multiple_candidates=True, ingen väljs automatiskt (ADR-004).
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "clio-research/1.0 (AIAB; fredrik@arvas.se)"
RATE_LIMIT_SLEEP = 1.0  # sekunder (ADR-010)

# SPARQL-fråga för sökning på namn + födelseår (från SPEC.md)
_SPARQL_SEARCH = """
SELECT DISTINCT ?person ?personLabel ?birthDate ?birthPlaceLabel
                ?deathDate ?occupationLabel ?wikipedia_en ?wikipedia_sv
WHERE {{
  ?person wdt:P31 wd:Q5 .
  {{
    ?person rdfs:label "{fornamn} {efternamn}"@sv .
  }} UNION {{
    ?person rdfs:label "{fornamn} {efternamn}"@en .
  }}
  OPTIONAL {{ ?person wdt:P569 ?birthDate }}
  OPTIONAL {{ ?person wdt:P19 ?birthPlace }}
  OPTIONAL {{ ?person wdt:P570 ?deathDate }}
  OPTIONAL {{ ?person wdt:P106 ?occupation }}
  OPTIONAL {{
    ?wikipedia_en schema:about ?person ;
                  schema:isPartOf <https://en.wikipedia.org/> .
  }}
  OPTIONAL {{
    ?wikipedia_sv schema:about ?person ;
                  schema:isPartOf <https://sv.wikipedia.org/> .
  }}
  FILTER(YEAR(?birthDate) = {fodelseår})
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "sv,en" }}
}}
LIMIT 5
"""

# SPARQL-fråga för direktuppslag via Q-ID
_SPARQL_BY_QID = """
SELECT DISTINCT ?person ?personLabel ?birthDate ?birthPlaceLabel
                ?deathDate ?occupationLabel ?wikipedia_en ?wikipedia_sv
WHERE {{
  BIND(wd:{qid} AS ?person)
  ?person wdt:P31 wd:Q5 .
  OPTIONAL {{ ?person wdt:P569 ?birthDate }}
  OPTIONAL {{ ?person wdt:P19 ?birthPlace }}
  OPTIONAL {{ ?person wdt:P570 ?deathDate }}
  OPTIONAL {{ ?person wdt:P106 ?occupation }}
  OPTIONAL {{
    ?wikipedia_en schema:about ?person ;
                  schema:isPartOf <https://en.wikipedia.org/> .
  }}
  OPTIONAL {{
    ?wikipedia_sv schema:about ?person ;
                  schema:isPartOf <https://sv.wikipedia.org/> .
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "sv,en" }}
}}
LIMIT 1
"""


@dataclass
class WikidataResult:
    found: bool = False
    multiple_candidates: bool = False       # ADR-004: > 1 kandidat → granskningskort
    candidates: list[dict] = field(default_factory=list)  # alla kandidater vid multipla
    wikidata_id: Optional[str] = None       # "Q5560391"
    wikidata_url: Optional[str] = None      # "https://www.wikidata.org/wiki/Q5560391"
    label: Optional[str] = None
    fodelsedag: Optional[str] = None        # ISO-format eller råvärde
    fodelseort: Optional[str] = None
    dodsdag: Optional[str] = None
    yrke: Optional[str] = None
    wikipedia_en: Optional[str] = None
    wikipedia_sv: Optional[str] = None
    error: Optional[str] = None


def _extract_qid(uri: str) -> str:
    """Extraherar Q-ID från Wikidata entity URI."""
    return uri.rstrip("/").split("/")[-1]


def _format_wikidata_date(raw: str) -> Optional[str]:
    """Konverterar Wikidata-datum ("+1913-09-22T00:00:00Z") till ISO-format."""
    if not raw:
        return None
    # Wikidata använder "+ÅÅÅÅ-MM-DDT00:00:00Z"
    clean = raw.lstrip("+").split("T")[0]  # "1913-09-22"
    # Hantera år med nolla-prefix som "+0032-..."
    parts = clean.split("-")
    if len(parts) >= 1 and len(parts[0]) > 4:
        parts[0] = parts[0][-4:]  # ta de sista 4 siffrorna
    return "-".join(parts) if len(parts) == 3 else clean


def _parse_result_row(row: dict) -> dict:
    """Tolkar en rad från SPARQL-resultatet till ett dict."""
    def val(key: str) -> Optional[str]:
        return row.get(key, {}).get("value")

    qid = _extract_qid(val("person") or "")
    raw_birth = val("birthDate")
    raw_death = val("deathDate")
    return {
        "wikidata_id": qid,
        "wikidata_url": f"https://www.wikidata.org/wiki/{qid}" if qid else None,
        "label": val("personLabel"),
        "fodelsedag": _format_wikidata_date(raw_birth) if raw_birth else None,
        "fodelseort": val("birthPlaceLabel"),
        "dodsdag": _format_wikidata_date(raw_death) if raw_death else None,
        "yrke": val("occupationLabel"),
        "wikipedia_en": val("wikipedia_en"),
        "wikipedia_sv": val("wikipedia_sv"),
    }


class WikidataSource:
    """
    Söker persondata i Wikidata via SPARQL.

    Användning:
        ws = WikidataSource()
        result = ws.get_by_q_id("Q5560391")
        result = ws.search_by_name_and_year("Dag", "Arvas", "1913")
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _sparql(self, query: str, max_retries: int = 3) -> Optional[dict]:
        """Kör SPARQL-fråga med retry och rate limit."""
        for attempt in range(max_retries):
            try:
                resp = self._session.get(
                    SPARQL_ENDPOINT,
                    params={"query": query, "format": "json"},
                    timeout=30,
                )
                resp.raise_for_status()
                time.sleep(RATE_LIMIT_SLEEP)  # ADR-010
                return resp.json()
            except requests.RequestException as exc:
                logger.warning("Wikidata-anrop misslyckades (försök %d/%d): %s", attempt + 1, max_retries, exc)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # exponentiell backoff
        return None

    def get_by_q_id(self, q_id: str) -> WikidataResult:
        """
        Direktuppslag via Wikidata Q-ID (t.ex. "Q5560391").
        Returnerar alltid exakt en post om den finns.
        """
        query = _SPARQL_BY_QID.format(qid=q_id)
        data = self._sparql(query)
        if data is None:
            return WikidataResult(error="Nätverksfel eller API ej tillgängligt")

        rows = data.get("results", {}).get("bindings", [])
        if not rows:
            return WikidataResult(found=False)

        parsed = _parse_result_row(rows[0])
        return WikidataResult(
            found=True,
            multiple_candidates=False,
            wikidata_id=parsed["wikidata_id"],
            wikidata_url=parsed["wikidata_url"],
            label=parsed["label"],
            fodelsedag=parsed["fodelsedag"],
            fodelseort=parsed["fodelseort"],
            dodsdag=parsed["dodsdag"],
            yrke=parsed["yrke"],
            wikipedia_en=parsed["wikipedia_en"],
            wikipedia_sv=parsed["wikipedia_sv"],
        )

    def search_by_name_and_year(
        self,
        fornamn: str,
        efternamn: str,
        fodelseår: str,
    ) -> WikidataResult:
        """
        Söker person på namn + födelseår.

        Om > 1 kandidat returneras: multiple_candidates=True (ADR-004).
        Om 0 kandidater: found=False.
        Om exakt 1: found=True med data.
        """
        try:
            year_int = int(fodelseår[:4])
        except (ValueError, TypeError):
            return WikidataResult(found=False, error=f"Ogiltigt födelseår: {fodelseår}")

        query = _SPARQL_SEARCH.format(
            fornamn=fornamn.replace('"', ""),
            efternamn=efternamn.replace('"', ""),
            fodelseår=year_int,
        )
        data = self._sparql(query)
        if data is None:
            return WikidataResult(error="Nätverksfel eller API ej tillgängligt")

        rows = data.get("results", {}).get("bindings", [])

        # Deduplicera på wikidata-ID (SPARQL kan returnera dubbletter pga UNION)
        seen_qids: set[str] = set()
        unique_rows = []
        for row in rows:
            qid = _extract_qid(row.get("person", {}).get("value", ""))
            if qid and qid not in seen_qids:
                seen_qids.add(qid)
                unique_rows.append(row)

        if not unique_rows:
            return WikidataResult(found=False)

        if len(unique_rows) > 1:
            # ADR-004: fler kandidater → granskningskort
            candidates = [_parse_result_row(r) for r in unique_rows]
            return WikidataResult(
                found=False,
                multiple_candidates=True,
                candidates=candidates,
            )

        parsed = _parse_result_row(unique_rows[0])
        return WikidataResult(
            found=True,
            multiple_candidates=False,
            wikidata_id=parsed["wikidata_id"],
            wikidata_url=parsed["wikidata_url"],
            label=parsed["label"],
            fodelsedag=parsed["fodelsedag"],
            fodelseort=parsed["fodelseort"],
            dodsdag=parsed["dodsdag"],
            yrke=parsed["yrke"],
            wikipedia_en=parsed["wikipedia_en"],
            wikipedia_sv=parsed["wikipedia_sv"],
        )
