"""
clio-vigil — filter.py
=======================
Relevansfilter för insamlade objekt.

MVP: nyckelordsmatchning med viktade primary/secondary-ord.
Release 1.5: semantisk bedömning via embedding-modell.

Designbeslut (ADD v0.2):
  - Filter körs på title + description INNAN transkription
  - Resulterar i filtered_in eller filtered_out
  - filtered_out sparas i DB — blockeras inte, utvärderas ej vidare
  - Relevansscore 0.0–1.0 sparas för framtida kalibrering
  - Källkvalitet påverkar INTE filtret — bara prioritetstalet

Nyckelord matchar hela ord (2026-11-08). Tidigare räckte en delsträng, så
"nde" träffade "under" och "aaro" träffade "Aaron". Vanliga böjningsändelser
(KEYWORD_SUFFIXES) tillåts: "abduct" fångar "abduction", "alien" fångar "aliens".
"""

import re
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

PRIMARY_WEIGHT     = 0.4
PRIMARY_MAX        = 1.0
SECONDARY_WEIGHT   = 0.15
SECONDARY_MAX      = 0.3
DEFAULT_THRESHOLD  = 0.55
KEYWORD_SUFFIXES   = ("s", "es", "ed", "ee", "ees", "ion", "ions", "ing")


# ---------------------------------------------------------------------------
# Nyckelordsmatchning
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercasar och normaliserar whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


@lru_cache(maxsize=1024)
def _keyword_pattern(keyword: str) -> re.Pattern:
    """Regex som matchar nyckelordet som helt ord, med tillåtna böjningsändelser."""
    suffixes = "|".join(KEYWORD_SUFFIXES)
    return re.compile(rf"(?<!\w){re.escape(_normalize(keyword))}(?:{suffixes})?(?!\w)")


def _count_hits(normalized: str, keywords: list) -> int:
    return sum(1 for kw in keywords if kw and _keyword_pattern(kw).search(normalized))


def keyword_score(text: str, keywords: dict) -> float:
    """
    Beräknar relevansscore baserat på nyckelordsmatchning (hela ord).

    keywords = {
        "primary": ["ufo", "uap", ...],    # tyngre vikt
        "secondary": ["skinwalker", ...]    # lägre vikt
    }

    Returvärde: 0.0–1.0
    """
    if not text:
        return 0.0

    normalized = _normalize(text)
    primary_hits = _count_hits(normalized, keywords.get("primary", []))
    secondary_hits = _count_hits(normalized, keywords.get("secondary", []))

    primary_score = min(primary_hits * PRIMARY_WEIGHT, PRIMARY_MAX)
    secondary_bonus = min(secondary_hits * SECONDARY_WEIGHT, SECONDARY_MAX)

    return round(min(primary_score + secondary_bonus, 1.0), 3)


# ---------------------------------------------------------------------------
# Filterkörning mot databasen
# ---------------------------------------------------------------------------

def _build_source_thresholds(domain_config: dict) -> dict:
    """
    A2: Bygg dict source_name → transcription_threshold från YAML-konfiguration.
    Används för att ge enskilda källor en lägre/högre tröskel än domänstandarden.
    """
    thresholds = {}
    sources = domain_config.get("sources", {})
    for src in sources.get("rss", []):
        name = src.get("name")
        if name and "transcription_threshold" in src:
            thresholds[name] = float(src["transcription_threshold"])
    for src in sources.get("youtube_channels", []):
        name = src.get("name") or src.get("channel_id")
        if name and "transcription_threshold" in src:
            thresholds[name] = float(src["transcription_threshold"])
    return thresholds


def _length_verdict(duration, domain_config: dict):
    """A1: Returnerar 'för kort'/'för lång' om duration ligger utanför gränserna, annars None."""
    if duration is None:
        return None
    min_dur = domain_config.get("min_duration_sec", None)
    max_dur = domain_config.get("max_duration_sec", None)
    if min_dur is not None and duration < min_dur:
        return "för kort"
    if max_dur is not None and duration > max_dur:
        return "för lång"
    return None


def _score_rows(conn, rows, keywords: dict) -> list:
    """
    Räknar score för varje rad och sparar relevance_score. Returnerar (row, score).
    Oförändrade score skrivs inte, så att Odoo-synken inte ser raden som ändrad.
    """
    scored = [
        (row, keyword_score(f"{row['title'] or ''} {row['description'] or ''}", keywords))
        for row in rows
    ]
    conn.executemany(
        "UPDATE vigil_items SET relevance_score = ? WHERE id = ? AND relevance_score IS NOT ?",
        [(score, row["id"], score) for row, score in scored],
    )
    conn.commit()
    return scored


def _queue_item(conn, item_id: int, title: str, threshold: float) -> None:
    """filtered_in → queued med prioritetstal och plats i transkriptionskön."""
    from orchestrator import transition, update_priority

    transition(conn, item_id, "filtered_in")
    prio = update_priority(conn, item_id)
    transition(conn, item_id, "queued")
    conn.execute(
        """INSERT OR IGNORE INTO transcription_queue (item_id, priority_score, queued_at)
           VALUES (?, ?, datetime('now'))""",
        (item_id, prio),
    )
    logger.debug(f"Item {item_id} köad (prio {prio:.3f}, tröskel {threshold}): {(title or '')[:50]}")


def _select_rows(conn, state: str, domain_id: str) -> list:
    return conn.execute(
        """SELECT id, title, description, duration_seconds, source_name
           FROM vigil_items WHERE state = ? AND domain = ?""",
        (state, domain_id),
    ).fetchall()


def run_filter(conn, domain_config: dict) -> dict:
    """
    Kör relevansfilter på alla discovered-objekt i en domän.
    Uppdaterar state till filtered_in (→ queued) eller filtered_out.

    Filterordning:
      1. A1 Längdfilter  — hoppa över objekt utanför min/max_duration_sec
      2. A2 Nyckelordsfilter — relevansscore mot käll-/domäntröskel
    Returnerar räknare.
    """
    from orchestrator import transition

    domain_id = domain_config["domain_id"]
    threshold = domain_config.get("relevance_threshold", DEFAULT_THRESHOLD)
    source_thresholds = _build_source_thresholds(domain_config)
    counts = {"filtered_in": 0, "filtered_out": 0, "length_filtered": 0}

    rows = _select_rows(conn, "discovered", domain_id)
    for row, score in _score_rows(conn, rows, domain_config.get("keywords", {})):
        verdict = _length_verdict(row["duration_seconds"], domain_config)
        if verdict:
            transition(conn, row["id"], "filtered_out")
            counts["filtered_out"] += 1
            counts["length_filtered"] += 1
            logger.debug(f"Längdfilter ({verdict} {row['duration_seconds']}s): {(row['title'] or '')[:50]}")
            continue

        effective_threshold = source_thresholds.get(row["source_name"] or "", threshold)
        if score >= effective_threshold:
            _queue_item(conn, row["id"], row["title"], effective_threshold)
            counts["filtered_in"] += 1
        else:
            transition(conn, row["id"], "filtered_out")
            counts["filtered_out"] += 1

    conn.commit()
    logger.info(
        f"Filter klar [{domain_id}]: "
        f"{counts['filtered_in']} in, {counts['filtered_out']} ut "
        f"({counts['length_filtered']} längdfiltrerade, tröskel={threshold})"
    )
    return counts


def refilter_filtered_out(conn, domain_config: dict, is_dry_run: bool = False) -> dict:
    """
    Poängsätter om filtered_out-objekt med aktuella nyckelord.
    Objekt som nu klarar tröskeln (och längdfiltret) köas som vid vanlig filtrering.
    Övriga ligger kvar i filtered_out med uppdaterad relevance_score.

    is_dry_run=True räknar bara — ingenting skrivs.
    Returnerar {"checked", "requeued", "per_source"}.
    """
    domain_id = domain_config["domain_id"]
    threshold = domain_config.get("relevance_threshold", DEFAULT_THRESHOLD)
    keywords = domain_config.get("keywords", {})
    source_thresholds = _build_source_thresholds(domain_config)
    rows = _select_rows(conn, "filtered_out", domain_id)

    if is_dry_run:
        scored = [(r, keyword_score(f"{r['title'] or ''} {r['description'] or ''}", keywords)) for r in rows]
    else:
        scored = _score_rows(conn, rows, keywords)

    counts = {"checked": len(rows), "requeued": 0, "per_source": {}}
    for row, score in scored:
        source = row["source_name"] or ""
        effective_threshold = source_thresholds.get(source, threshold)
        if _length_verdict(row["duration_seconds"], domain_config) or score < effective_threshold:
            continue
        counts["requeued"] += 1
        counts["per_source"][source] = counts["per_source"].get(source, 0) + 1
        if not is_dry_run:
            _queue_item(conn, row["id"], row["title"], effective_threshold)

    conn.commit()
    logger.info(
        f"Omfiltrering [{domain_id}]: {counts['requeued']} av {counts['checked']} "
        f"filtered_out köade{' (torrkörning)' if is_dry_run else ''}"
    )
    return counts
