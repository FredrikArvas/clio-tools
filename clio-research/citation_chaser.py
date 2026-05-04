"""citation_chaser.py — Forward + backward citation chasing via Semantic Scholar (depth 1)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from connectors import semantic_scholar


def chase(sources: list[dict], seen_ids: set, depth: int = 1) -> list[dict]:
    """
    Kör citation chasing från top-sources.
    R1.0: depth 1. Returnerar nya källor (ej i seen_ids).
    Uppdaterar seen_ids in-place.
    """
    if not sources:
        return []

    # Välj top-10 per fas baserat på credibility_score om den finns
    candidates = sorted(
        [s for s in sources if s.get("ss_paper_id")],
        key=lambda s: s.get("credibility_score", 0),
        reverse=True,
    )[:10]

    if not candidates:
        logger.info("[citation_chaser] Inga Semantic Scholar-IDs hittades — hoppar över")
        return []

    logger.info("[citation_chaser] Kör depth=%d från %d startkällor", depth, len(candidates))
    new_sources = []

    for source in candidates:
        paper_id = source["ss_paper_id"]
        title = source.get("title", paper_id)

        for direction in ("citations", "references"):
            try:
                ids = semantic_scholar.get_citations(paper_id, direction=direction)
            except Exception as e:
                logger.warning("[citation_chaser] %s för %s misslyckades: %s", direction, title, e)
                continue

            logger.info("[citation_chaser] %s → %d %s", title[:40], len(ids), direction)

            for pid in ids[:20]:
                try:
                    paper = semantic_scholar.get_paper(pid)
                except Exception as e:
                    logger.debug("[citation_chaser] get_paper(%s) misslyckades: %s", pid, e)
                    continue

                if not paper:
                    continue

                sid = paper.get("source_id")
                if not sid or sid in seen_ids:
                    continue

                seen_ids.add(sid)
                paper["phase_found"] = 5
                paper["via_citation"] = True
                paper["cited_from"] = title[:60]
                new_sources.append(paper)

    logger.info("[citation_chaser] Hittade %d nya källor via citation chasing", len(new_sources))
    return new_sources
