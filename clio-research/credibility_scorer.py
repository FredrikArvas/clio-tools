"""credibility_scorer.py — Poängsätter källor på 6 dimensioner (0–3 var, max 18p)."""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

MAX_SCORE = 18
DIMENSIONS = [
    "methodological_rigor",
    "institutional_independence",
    "geographic_convergence",
    "internal_consistency",
    "falsification_attempts",
    "temporal_stability",
]


def score(source: dict) -> dict:
    """
    Beräkna credibility score för en källobjekt.
    Lägger till 'credibility_score' (0–18) och 'credibility_breakdown' (dict).
    Returnerar källobjektet (muterat in-place).
    """
    breakdown = {
        "methodological_rigor": _score_methodology(source),
        "institutional_independence": _score_independence(source),
        "geographic_convergence": _score_geography(source),
        "internal_consistency": _score_consistency(source),
        "falsification_attempts": _score_falsification(source),
        "temporal_stability": _score_temporal(source),
    }

    total = sum(breakdown.values())
    source["credibility_score"] = total
    source["credibility_breakdown"] = breakdown
    return source


def score_all(sources: list[dict], all_sources: list[dict] | None = None) -> list[dict]:
    """
    Poängsätt alla källor. Uppdaterar geographic_convergence baserat på alla källor.
    """
    if all_sources is not None:
        regions_with_sources = _count_regions(all_sources)
    else:
        regions_with_sources = _count_regions(sources)

    for src in sources:
        score(src)
        geo = _score_geography_global(src, regions_with_sources)
        src["credibility_breakdown"]["geographic_convergence"] = geo
        src["credibility_score"] = sum(src["credibility_breakdown"].values())

    return sources


def _score_methodology(src: dict) -> int:
    """0=Anekdot, 1=Observation, 2=Kontrollerad studie, 3=RCT/replikerad."""
    abstract = (src.get("abstract") or "").lower()
    title = (src.get("title") or "").lower()
    text = abstract + " " + title

    rct_terms = ["randomized", "randomised", "rct", "double-blind", "placebo-controlled",
                 "replication", "replicated", "meta-analysis", "systematic review"]
    controlled_terms = ["controlled", "control group", "experiment", "measurement",
                        "statistically significant", "p-value", "n="]
    observational_terms = ["observation", "case study", "survey", "questionnaire",
                           "interview", "reported", "anecdot"]

    for t in rct_terms:
        if t in text:
            return 3

    for t in controlled_terms:
        if t in text:
            return 2

    for t in observational_terms:
        if t in text:
            return 1

    return 1


def _score_independence(src: dict) -> int:
    """0=Stark intressekonflikt, 1=Oklar finansiering, 2=Oberoende, 3=Multi-institutionell."""
    journal = (src.get("journal") or "").lower()
    database = (src.get("database") or "").lower()

    conflict_terms = ["funded by", "supported by", "grant from", "sponsored"]
    abstract = (src.get("abstract") or "").lower()

    for t in conflict_terms:
        if t in abstract:
            return 0

    if database in ("openalex", "semantic_scholar", "core", "crossref"):
        return 2

    if database in ("cyberleninka", "jstage"):
        return 2

    return 1


def _score_geography(src: dict) -> int:
    """Enskild källa = 1 per default. Uppdateras globalt i score_all()."""
    return 1


def _score_geography_global(src: dict, regions_with_sources: dict) -> int:
    """0=Enskild källa, 1=2 regioner, 2=3–4 regioner, 3=5+ regioner."""
    num_regions = len(regions_with_sources)
    if num_regions >= 5:
        return 3
    if num_regions >= 3:
        return 2
    if num_regions >= 2:
        return 1
    return 0


def _score_consistency(src: dict) -> int:
    """0=Inre motsägelser, 1=Delvis konsistent, 2=Konsistent, 3=Konsistent+matematiskt."""
    abstract = (src.get("abstract") or "").lower()
    title = (src.get("title") or "").lower()
    text = abstract + " " + title

    math_terms = ["equation", "formula", "mathematical model", "теоретическая модель",
                  "数式", "モデル"]
    inconsistency_terms = ["contradiction", "inconsistent", "paradox", "conflicting"]

    for t in inconsistency_terms:
        if t in text:
            return 0

    for t in math_terms:
        if t in text:
            return 3

    if abstract:
        return 2

    return 1


def _score_falsification(src: dict) -> int:
    """0=Inga kända, 1=Informella, 2=Formella ej replikerade, 3=Formella replikerade."""
    abstract = (src.get("abstract") or "").lower()
    title = (src.get("title") or "").lower()
    text = abstract + " " + title

    formal_rep = ["failed replication", "replication failure", "could not replicate",
                  "no effect found", "null result"]
    formal = ["falsif", "refut", "debunk", "skeptic", "critique of"]
    informal = ["pseudoscience", "myth", "fraud"]

    for t in formal_rep:
        if t in text:
            return 3

    for t in formal:
        if t in text:
            return 2

    for t in informal:
        if t in text:
            return 1

    return 0


def _score_temporal(src: dict) -> int:
    """0=Enstaka, 1=Följdforskning, 2=Håller >10 år, 3=Håller >20 år."""
    year = src.get("year")
    citation_count = src.get("citation_count", 0) or 0

    if year is None:
        return 0

    import datetime
    current_year = datetime.date.today().year
    age = current_year - year

    if age >= 20 and citation_count >= 5:
        return 3
    if age >= 10 and citation_count >= 2:
        return 2
    if citation_count >= 1:
        return 1
    return 0


def _count_regions(sources: list[dict]) -> dict:
    """Räkna unika regioner bland källorna."""
    regions: dict[str, int] = {}
    for src in sources:
        region = src.get("region")
        if region:
            regions[region] = regions.get(region, 0) + 1
    return regions
