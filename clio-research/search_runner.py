"""search_runner.py — Dispatchar sökningar per fas, deduplicerar och normaliserar."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from connectors import openalex, semantic_scholar, core_api, crossref, cyberleninka, jstage

CONNECTOR_MAP: dict[str, Callable] = {
    "openalex": openalex.search,
    "semantic_scholar": semantic_scholar.search,
    "core": core_api.search,
    "crossref": crossref.search,
    "cyberleninka": cyberleninka.search,
    "jstage": jstage.search,
}

REGION_FOR_DB: dict[str, str] = {
    "cyberleninka": "RU",
    "elibrary": "RU",
    "jstage": "JP",
    "cinii": "JP",
    "scielo": "LATAM",
    "redalyc": "LATAM",
}


def run_phase(phase_def: dict, protocol: dict, seen_ids: set) -> list[dict]:
    """
    Kör en fas från protokollet. Returnerar nya (ej tidigare sedda) källobjekt.
    Uppdaterar seen_ids in-place.
    """
    phase_num = phase_def["phase"]
    databases = phase_def.get("databases", [])
    max_results = phase_def.get("max_results", 50)
    label = phase_def.get("label", f"Fas {phase_num}")

    if isinstance(databases, dict):
        # Regional fas — dict med region → list av databaser
        return _run_regional(databases, phase_def, protocol, seen_ids, phase_num, label)

    keywords = _build_keywords(protocol, phase_def)
    new_sources = []

    for db_name in databases:
        fn = CONNECTOR_MAP.get(db_name)
        if not fn:
            logger.warning("[%s] Okänd databas: %s — hoppas över", label, db_name)
            continue

        logger.info("[%s] Söker %s (%d söktermer)", label, db_name, len(keywords))
        region = REGION_FOR_DB.get(db_name)

        for kw in keywords:
            try:
                results = fn(kw, max_results=min(max_results // max(len(keywords), 1) + 5, 50))
            except Exception as e:
                logger.warning("[%s] %s misslyckades för '%s': %s", label, db_name, kw, e)
                results = []

            for src in results:
                sid = src.get("source_id")
                if not sid or sid in seen_ids:
                    continue
                seen_ids.add(sid)
                src["phase_found"] = phase_num
                if region and not src.get("region"):
                    src["region"] = region
                new_sources.append(src)

    logger.info("[%s] Hittade %d nya källor", label, len(new_sources))
    return new_sources


def _run_regional(db_dict: dict, phase_def: dict, protocol: dict, seen_ids: set,
                  phase_num: int, label: str) -> list[dict]:
    """Hantera regional fas där databaser är uppdelade per region."""
    max_per_region = phase_def.get("max_results_per_region", 30)
    new_sources = []

    keywords_by_lang = protocol["question"].get("keywords_primary", {})

    for region, dbs in db_dict.items():
        if isinstance(dbs, str):
            dbs = [dbs]

        lang_keywords = keywords_by_lang.get(region.lower(), [])
        if not lang_keywords:
            lang_keywords = keywords_by_lang.get("en", [])

        for db_name in dbs:
            fn = CONNECTOR_MAP.get(db_name)
            if not fn:
                logger.warning("[%s] Okänd databas: %s — hoppas över", label, db_name)
                continue

            logger.info("[%s] Region %s: söker %s", label, region, db_name)

            for kw in lang_keywords[:3]:
                try:
                    results = fn(kw, max_results=max_per_region)
                except Exception as e:
                    logger.warning("[%s] %s/%s misslyckades: %s", label, region, db_name, e)
                    results = []

                for src in results:
                    sid = src.get("source_id")
                    if not sid or sid in seen_ids:
                        continue
                    seen_ids.add(sid)
                    src["phase_found"] = phase_num
                    if not src.get("region"):
                        src["region"] = region
                    new_sources.append(src)

    logger.info("[%s] Regional fas: %d nya källor", label, len(new_sources))
    return new_sources


def _build_keywords(protocol: dict, phase_def: dict) -> list[str]:
    """Bygg söktermslista för fasen."""
    q = protocol["question"]
    label = phase_def.get("label", "")

    if label == "Adversarial":
        adversarial = q.get("keywords_adversarial", {})
        terms = []
        for lang_terms in adversarial.values():
            terms.extend(lang_terms)
        return terms[:6] if terms else q.get("keywords_primary", {}).get("en", [])[:3]

    primary = q.get("keywords_primary", {})
    terms = list(primary.get("en", []))

    if label in ("Scoping",):
        researchers = q.get("key_researchers", [])
        terms = researchers[:3] + terms[:2]

    return terms[:5] if terms else []
