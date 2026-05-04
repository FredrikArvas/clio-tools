"""
sources/libris.py — LibrisSource: söker publikationer via Libris SRU API.

Returnerar MARCXML, parsat med xml.etree.ElementTree (stdlib, inga externa beroenden).
Rate limit: ingen explicit, men vi respekterar god sed med 0.5s sleep.
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

SRU_ENDPOINT = "https://libris.kb.se/api/sru"
USER_AGENT = "clio-research/1.0 (AIAB; fredrik@arvas.se)"
RATE_LIMIT_SLEEP = 0.5

# MARCXML namespaces
_MARC_NS = "http://www.loc.gov/MARC21/slim"
_SRU_NS = "http://www.loc.gov/zing/srw/"


@dataclass
class Publikation:
    titel: Optional[str] = None
    roll: Optional[str] = None      # t.ex. "author", "editor"
    utgivare: Optional[str] = None
    år: Optional[str] = None
    isbn: Optional[str] = None
    libris_url: Optional[str] = None


@dataclass
class LibrisResult:
    found: bool = False
    publikationer: list[Publikation] = field(default_factory=list)
    antal_träffar: int = 0
    error: Optional[str] = None


def _marc_subfield(record: ET.Element, tag: str, code: str) -> Optional[str]:
    """Hämtar subfield ur MARC21 datafield."""
    df = record.find(f".//{{{_MARC_NS}}}datafield[@tag='{tag}']")
    if df is None:
        return None
    sf = df.find(f"{{{_MARC_NS}}}subfield[@code='{code}']")
    return sf.text.strip() if sf is not None and sf.text else None


def _marc_all_subfields(record: ET.Element, tag: str, code: str) -> list[str]:
    """Hämtar alla subfields med givet tag och code."""
    results = []
    for df in record.findall(f".//{{{_MARC_NS}}}datafield[@tag='{tag}']"):
        sf = df.find(f"{{{_MARC_NS}}}subfield[@code='{code}']")
        if sf is not None and sf.text:
            results.append(sf.text.strip())
    return results


def _parse_record(record: ET.Element) -> Publikation:
    """Parsar ett MARC21-record till Publikation."""
    pub = Publikation()

    # Titel (245$a)
    pub.titel = _marc_subfield(record, "245", "a")
    if pub.titel:
        pub.titel = pub.titel.rstrip(" /").strip()

    # Roll (100$e = huvudsaklig upphovsman, 700$e = bifogad upphovsman)
    roll_100 = _marc_subfield(record, "100", "e")
    roll_700 = _marc_subfield(record, "700", "e")
    pub.roll = (roll_100 or roll_700 or "").strip().rstrip(",").strip() or None

    # Utgivare (260$b eller 264$b)
    pub.utgivare = _marc_subfield(record, "260", "b") or _marc_subfield(record, "264", "b")
    if pub.utgivare:
        pub.utgivare = pub.utgivare.rstrip(",").strip()

    # År (260$c eller 264$c)
    raw_år = _marc_subfield(record, "260", "c") or _marc_subfield(record, "264", "c")
    if raw_år:
        # Rensa bort icke-siffror (t.ex. "[1976]" → "1976")
        import re
        m = re.search(r"\d{4}", raw_år)
        pub.år = m.group(0) if m else raw_år.strip()

    # ISBN (020$a)
    pub.isbn = _marc_subfield(record, "020", "a")

    return pub


class LibrisSource:
    """
    Söker publikationer i Libris SRU API.

    Användning:
        ls = LibrisSource()
        result = ls.search_by_creator("Arvas", "Birgitta")
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _get_sru(self, query: str, max_records: int = 10, max_retries: int = 3) -> Optional[str]:
        """Kör SRU-sökning och returnerar råa XML-strängen."""
        params = {
            "version": "1.1",
            "operation": "searchRetrieve",
            "query": query,
            "maximumRecords": str(max_records),
            "recordSchema": "marcxml",
        }
        for attempt in range(max_retries):
            try:
                resp = self._session.get(SRU_ENDPOINT, params=params, timeout=20)
                resp.raise_for_status()
                time.sleep(RATE_LIMIT_SLEEP)
                return resp.text
            except requests.RequestException as exc:
                logger.warning("Libris-anrop misslyckades (försök %d/%d): %s", attempt + 1, max_retries, exc)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    def search_by_creator(self, efternamn: str, fornamn: str = "") -> LibrisResult:
        """
        Söker på upphovsman med efternamn (och valfritt förnamn).

        Libris SRU-format: "EFTERNAMN" AND "FÖRNAMN" (fungerar i Libris XL).
        OBS: dc.creator-syntaxen returnerar 0 träffar i nuvarande Libris API.
        """
        if fornamn:
            query = f'"{efternamn}" AND "{fornamn}"'
        else:
            query = f'"{efternamn}"'

        xml_text = self._get_sru(query)
        if xml_text is None:
            return LibrisResult(error="Nätverksfel eller API ej tillgängligt")

        return self._parse_sru_response(xml_text)

    def _parse_sru_response(self, xml_text: str) -> LibrisResult:
        """Parsar SRU/MARCXML-svar."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.error("XML-parsning misslyckades: %s", exc)
            return LibrisResult(error=f"XML-parsfel: {exc}")

        # Antal träffar — Libris returnerar utan SRU-namespace, sök med wildcard
        # OBS: ET-element är falsy om de saknar barn — använd explicit is not None-check
        antal_el = root.find(".//numberOfRecords")
        if antal_el is None:
            antal_el = root.find(f".//{{{_SRU_NS}}}numberOfRecords")
        antal = int(antal_el.text) if antal_el is not None and antal_el.text else 0

        # Hämta alla records
        publikationer: list[Publikation] = []
        for record_el in root.findall(f".//{{{_MARC_NS}}}record"):
            pub = _parse_record(record_el)
            if pub.titel:  # filtrera bort tomma poster
                publikationer.append(pub)

        return LibrisResult(
            found=len(publikationer) > 0,
            publikationer=publikationer,
            antal_träffar=antal,
        )
