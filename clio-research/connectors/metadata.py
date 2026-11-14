"""
connectors/metadata.py
Gemensam tolkning av metadata för connectorerna: källtyp, land och institution.

Principen är att bara återge det API:et säger. Saknas uppgiften blir svaret
None eller en tom lista, aldrig en gissning utifrån databas, språk eller titel.
"""

from __future__ import annotations

import re

# ── Källtyp ───────────────────────────────────────────────────────────────────

# OpenAlex `type` → kontraktets source_type. Typer som inte säger något om
# publiceringsformen (dataset, paratext, erratum, other …) ger None.
OPENALEX_TYPES: dict[str, str] = {
    "article": "peer-reviewed",
    "review": "peer-reviewed",
    "letter": "peer-reviewed",
    "preprint": "preprint",
    "book": "bok",
    "book-chapter": "bok",
    "reference-entry": "bok",
    "report": "rapport",
    "standard": "rapport",
    "dissertation": "rapport",
}

CROSSREF_TYPES: dict[str, str] = {
    "journal-article": "peer-reviewed",
    "proceedings-article": "konferens",
    "posted-content": "preprint",
    "book": "bok",
    "book-chapter": "bok",
    "book-section": "bok",
    "book-part": "bok",
    "monograph": "bok",
    "edited-book": "bok",
    "reference-book": "bok",
    "reference-entry": "bok",
    "report": "rapport",
    "report-component": "rapport",
    "standard": "rapport",
    "dissertation": "rapport",
}


def openalex_source_type(work_type: str | None, venue_type: str | None) -> str | None:
    """Källtyp ur OpenAlex `type` och `primary_location.source.type`.

    En artikel räknas som peer-reviewed bara när den ligger i en tidskrift. Ligger
    den i ett arkiv är den ett preprint, i en konferensserie ett konferensbidrag,
    och saknas publiceringsplatsen är typen okänd.
    """
    mapped = OPENALEX_TYPES.get((work_type or "").lower())
    if mapped != "peer-reviewed":
        return mapped
    venue = (venue_type or "").lower()
    if venue == "journal":
        return "peer-reviewed"
    if venue == "conference":
        return "konferens"
    if venue == "repository":
        return "preprint"
    return None


def crossref_source_type(work_type: str | None) -> str | None:
    """Källtyp ur CrossRef `type`. Okänd typ ger None."""
    return CROSSREF_TYPES.get((work_type or "").lower())


# ── Land och institution ──────────────────────────────────────────────────────

_CODE_RE = re.compile(r"^[A-Za-z]{2}$")

# Landsnamn så som de skrivs i affilieringssträngar. Namn som också är delstater,
# städer eller vanliga ord (Georgia, Jersey, Chad, Turkey …) är utelämnade med avsikt.
COUNTRY_NAMES: dict[str, str] = {
    "argentina": "AR", "australia": "AU", "austria": "AT", "belgium": "BE", "brazil": "BR",
    "brasil": "BR", "bulgaria": "BG", "canada": "CA", "chile": "CL", "china": "CN",
    "p.r. china": "CN", "pr china": "CN", "people's republic of china": "CN", "colombia": "CO",
    "croatia": "HR", "czech republic": "CZ", "czechia": "CZ", "denmark": "DK", "egypt": "EG",
    "estonia": "EE", "finland": "FI", "france": "FR", "germany": "DE", "deutschland": "DE",
    "greece": "GR", "hungary": "HU", "iceland": "IS", "india": "IN", "indonesia": "ID",
    "iran": "IR", "ireland": "IE", "israel": "IL", "italy": "IT", "italia": "IT", "japan": "JP",
    "latvia": "LV", "lithuania": "LT", "malaysia": "MY", "netherlands": "NL",
    "the netherlands": "NL", "new zealand": "NZ", "nigeria": "NG", "norway": "NO",
    "pakistan": "PK", "peru": "PE", "philippines": "PH", "poland": "PL", "portugal": "PT",
    "romania": "RO", "russia": "RU", "russian federation": "RU", "saudi arabia": "SA",
    "serbia": "RS", "singapore": "SG", "slovakia": "SK", "slovenia": "SI", "south africa": "ZA",
    "south korea": "KR", "republic of korea": "KR", "spain": "ES", "españa": "ES",
    "sweden": "SE", "sverige": "SE", "switzerland": "CH", "taiwan": "TW", "thailand": "TH",
    "ukraine": "UA", "united arab emirates": "AE", "united kingdom": "GB", "uk": "GB",
    "u.k.": "GB", "england": "GB", "scotland": "GB", "wales": "GB", "united states": "US",
    "united states of america": "US", "usa": "US", "u.s.a.": "US", "vietnam": "VN",
}

# Förkortningar som är entydiga även utan kommatecken före ("… Massachusetts USA").
_TRAILING_TOKENS: dict[str, str] = {"usa": "US", "u.s.a.": "US", "uk": "GB", "u.k.": "GB"}


def openalex_affiliations(authorships: list[dict] | None) -> tuple[list[str], list[str]]:
    """Landskoder och institutionsnamn ur OpenAlex `authorships`.

    Läser `institutions[].country_code`, `institutions[].display_name` och
    `countries`. Ordningen följer författarordningen, utan dubbletter.
    """
    codes: list[str] = []
    names: list[str] = []
    for authorship in authorships or []:
        if not isinstance(authorship, dict):
            continue
        for inst in authorship.get("institutions") or []:
            if not isinstance(inst, dict):
                continue
            _add(names, inst.get("display_name"))
            _add_code(codes, inst.get("country_code"))
        for code in authorship.get("countries") or []:
            _add_code(codes, code)
    return codes, names


def crossref_affiliations(authors: list[dict] | None) -> tuple[list[str], list[str]]:
    """Landskoder och institutionsnamn ur CrossRef `author[].affiliation`.

    CrossRef har inget landsfält. Land läses bara ur affilieringssträngen när
    den uttryckligen slutar med ett landsnamn (se `country_from_affiliation`).
    """
    codes: list[str] = []
    names: list[str] = []
    for author in authors or []:
        if not isinstance(author, dict):
            continue
        for aff in author.get("affiliation") or []:
            name = aff.get("name") if isinstance(aff, dict) else None
            if not isinstance(name, str) or not name.strip():
                continue
            _add(names, " ".join(name.split()))
            _add_code(codes, country_from_affiliation(name))
    return codes, names


def country_from_affiliation(affiliation: str) -> str | None:
    """Landskod när affilieringen uttryckligen namnger landet, annars None.

    Träff kräver att det sista kommaavgränsade ledet (utan postnummer) är ett
    landsnamn, eller att strängen slutar med en entydig förkortning (USA, UK).
    "University of New Mexico" eller "Kyoto" ger alltså inget land.
    """
    if not isinstance(affiliation, str):
        return None
    last = affiliation.split(",")[-1]
    # Postnummer ("02138", "T9S 3A3", "AB24 3UE") är led som innehåller siffror.
    last = " ".join(tok for tok in last.split() if not any(ch.isdigit() for ch in tok))
    last = last.strip(" .;").lower()
    if not last:
        return None
    if "," in affiliation and last in COUNTRY_NAMES:
        return COUNTRY_NAMES[last]
    final_token = last.split()[-1]
    return _TRAILING_TOKENS.get(final_token)


def _add(items: list[str], value) -> None:
    if isinstance(value, str) and value.strip() and value.strip() not in items:
        items.append(value.strip())


def _add_code(codes: list[str], value) -> None:
    if isinstance(value, str) and _CODE_RE.match(value.strip()) and value.strip().upper() not in codes:
        codes.append(value.strip().upper())
