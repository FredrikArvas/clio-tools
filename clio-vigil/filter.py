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
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Nyckelordsmatchning
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercasar och normaliserar whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


def keyword_score(text: str, keywords: dict) -> float:
    """
    Beräknar relevansscore baserat på nyckelordsmatchning.

    keywords = {
        "primary": ["ufo", "uap", ...],    # tyngre vikt
        "secondary": ["skinwalker", ...]    # lägre vikt
    }

    Returvärde: 0.0–1.0
    """
    if not text:
        return 0.0

    normalized = _normalize(text)
    primary = keywords.get("primary", [])
    secondary = keywords.get("secondary", [])

    primary_hits = sum(1 for kw in primary if _normalize(kw) in normalized)
    secondary_hits = sum(1 for kw in secondary if _normalize(kw) in normalized)

    # Primary-träff = 0.4 per träff (max 1.0)
    # Secondary-träff = 0.15 per träff (max 0.3)
    primary_score = min(primary_hits * 0.4, 1.0)
    secondary_bonus = min(secondary_hits * 0.15, 0.3)

    return round(min(primary_score + secondary_bonus, 1.0), 3)


# ---------------------------------------------------------------------------
# Filterkörning mot databasen
# ---------------------------------------------------------------------------

def run_filter(conn, domain_config: dict) -> dict:
    """
    Kör relevansfilter på alla discovered-objekt i en domän.
    Uppdaterar state till filtered_in eller filtered_out.
    Returnerar räknare.
    """
    from orchestrator import transition, update_priority

    domain_id = domain_config["domain_id"]
    threshold = domain_config.get("relevance_threshold", 0.55)
    keywords = domain_config.get("keywords", {})
    counts = {"filtered_in": 0, "filtered_out": 0}

    rows = conn.execute(
        "SELECT id, title, description FROM vigil_items WHERE state = 'discovered' AND domain = ?",
        (domain_id,)
    ).fetchall()

    for row in rows:
        text = f"{row['title'] or ''} {row['description'] or ''}"
        score = keyword_score(text, keywords)

        if score >= threshold:
            new_state = "filtered_in"
            counts["filtered_in"] += 1
        else:
            new_state = "filtered_out"
            counts["filtered_out"] += 1

        # Spara score och övergå tillstånd
        conn.execute(
            "UPDATE vigil_items SET relevance_score = ? WHERE id = ?",
            (score, row["id"])
        )
        conn.commit()
        transition(conn, row["id"], new_state)

        # Beräkna prioritetstal för filtered_in-objekt
        if new_state == "filtered_in":
            prio = update_priority(conn, row["id"])
            # Lägg i kö direkt
            transition(conn, row["id"], "queued")
            conn.execute(
                """INSERT INTO transcription_queue (item_id, priority_score, queued_at)
                   VALUES (?, ?, datetime('now'))""",
                (row["id"], prio)
            )
            conn.commit()
            logger.debug(f"Item {row['id']} köad med prio {prio:.3f}: {row['title'][:50]}")

    logger.info(
        f"Filter klar [{domain_id}]: "
        f"{counts['filtered_in']} in, {counts['filtered_out']} ut "
        f"(tröskel={threshold})"
    )
    return counts
