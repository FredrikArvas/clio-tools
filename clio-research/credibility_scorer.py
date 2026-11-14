"""
credibility_scorer.py
Källkvalitet: det som går att räkna (PLAN_research_pipeline_v2.md avsnitt 11 punkt 3).

Python räknar ålder och citeringar till `quality`. Land och institution ligger i
källans `country_codes` och `institutions`, hämtade ur metadata av connectorerna.
Metod, oberoende och falsifieringsförsök bedöms av analytikern, som fyller
`quality.assessment` med en motivering per källa. Här lämnas fältet `null`.

Den tidigare poängen (0–18) byggde på nyckelordsmatchning mot sammanfattningen och
gav 4–8 för alla källor i rapport 021. Den är borttagen. Geografisk konvergens
räknas inte längre per källa utan per påstående, över de källor som belägger det
(`geographic_spread`).

`score_all` finns kvar som tunn brygga för R1.x-flödet i main.py.
"""

from __future__ import annotations

import datetime
import logging

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "2.0.0"

logger = logging.getLogger(__name__)


# ── Källformatet (v2) ─────────────────────────────────────────────────────────

def assess(source: dict, current_year: int | None = None) -> dict:
    """Fyll `quality` på en källa i källformatet med det som går att räkna.

    `citations` behålls som den kom ur metadata (None om databasen inte anger den).
    `age_years` räknas ur `year`. En bedömning som analytikern redan skrivit i
    `quality.assessment` lämnas orörd; annars är den None.

    Returns:
        Källan (ändrad på plats).
    """
    current_year = current_year or datetime.date.today().year
    quality = source.get("quality") or {}
    citations = quality.get("citations")
    source["quality"] = {
        "citations": citations if _is_count(citations) else None,
        "age_years": age_years(source.get("year"), current_year),
        "assessment": quality.get("assessment"),
    }
    return source


def assess_all(sources: list[dict], current_year: int | None = None) -> list[dict]:
    """Kör `assess` på varje källa."""
    for source in sources:
        assess(source, current_year)
    return sources


def age_years(year, current_year: int) -> int | None:
    """Källans ålder i hela år. None när året saknas eller ligger i framtiden."""
    if isinstance(year, bool) or not isinstance(year, int):
        return None
    age = current_year - year
    return age if age >= 0 else None


def geographic_spread(sources: list[dict]) -> dict:
    """Länder bland en uppsättning källor, t.ex. de som belägger ett påstående.

    Returns:
        {"countries": {"FR": 2, "US": 1}, "known": 3, "unknown": 1}
        där `known` är antal källor med minst en landskod och `unknown` antal utan.
        Källor utan landskod får inte räknas som stöd för geografisk spridning.
    """
    countries: dict[str, int] = {}
    known = unknown = 0
    for source in sources:
        codes = source.get("country_codes") or []
        if not codes:
            unknown += 1
            continue
        known += 1
        for code in dict.fromkeys(codes):
            countries[code] = countries.get(code, 0) + 1
    return {"countries": dict(sorted(countries.items())), "known": known, "unknown": unknown}


# ── Äldre flöde (R1.x, main.py) ───────────────────────────────────────────────

def score_all(sources: list[dict], all_sources: list[dict] | None = None) -> list[dict]:
    """Brygga för R1.x-flödet: räknar kvalitet på råträffar.

    Lägger `quality` (citeringar, ålder) på varje råträff. `credibility_score` och
    `credibility_breakdown` sätts fortfarande eftersom citation_chaser och
    report_builder läser dem, men innehåller nu bara den räknebara dimensionen
    `temporal_stability` (0–3). Skalan 0–18 gäller inte längre.

    `all_sources` togs emot för den globala geografipoängen och används inte.
    """
    current_year = datetime.date.today().year
    for src in sources:
        citations = src.get("citation_count")
        citations = citations if _is_count(citations) else None
        age = age_years(src.get("year"), current_year)
        src["quality"] = {"citations": citations, "age_years": age, "assessment": None}
        temporal = _temporal_stability(age, citations)
        src["credibility_breakdown"] = {"temporal_stability": temporal}
        src["credibility_score"] = temporal
    return sources


def _temporal_stability(age: int | None, citations: int | None) -> int:
    """0=enstaka, 1=följdforskning finns, 2=håller över 10 år, 3=håller över 20 år."""
    citations = citations or 0
    if age is None:
        return 0
    if age >= 20 and citations >= 5:
        return 3
    if age >= 10 and citations >= 2:
        return 2
    if citations >= 1:
        return 1
    return 0


def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
