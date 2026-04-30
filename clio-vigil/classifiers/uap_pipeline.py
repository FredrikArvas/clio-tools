"""
clio-vigil — classifiers/uap_pipeline.py
=========================================
Kör UAP-klassificerare på filtrerade vigil_items (UFO-domänen)
och skapar pending uap.encounter-poster i Odoo för manuellt godkännande.

Flöde:
  vigil_items (state=queued, domain=ufo) → classify() → if import_candidate → Odoo pending

Designbeslut:
  - Kör på "queued"-items som har title + description (ingen transkription krävs)
  - Sätter vigil_items.state → "uap_classified" efter körning (ny terminal state)
  - Skapar aldrig dubbletter i Odoo: kontrollerar url i research_notes
  - Confidence-tröskel: 0.70 (definierad i uap_classifier.py)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Optional

from classifiers.uap_classifier import classify, queue_for_approval

logger = logging.getLogger(__name__)

_NEW_STATE = "uap_classified"


def _ensure_state(conn: sqlite3.Connection) -> None:
    """Lägg till uap_classified som giltigt tillstånd om det saknas."""
    conn.execute(
        "UPDATE vigil_items SET state = state WHERE state = ?",
        (_NEW_STATE,),
    )


def _get_candidates(
    conn: sqlite3.Connection,
    max_items: int = 50,
) -> list[dict]:
    """Hämta queued UFO-items med title och description."""
    rows = conn.execute(
        """
        SELECT id, url, title, description, source_name, published_at
        FROM vigil_items
        WHERE domain = 'ufo'
          AND state = 'queued'
          AND title IS NOT NULL
        ORDER BY priority_score DESC
        LIMIT ?
        """,
        (max_items,),
    ).fetchall()
    return [
        {
            "id": r[0], "url": r[1], "title": r[2],
            "description": r[3] or "", "source_name": r[4] or "",
            "published_at": r[5] or "",
        }
        for r in rows
    ]


def _mark_classified(conn: sqlite3.Connection, item_id: int, odoo_id) -> None:
    # OdooRecordset / OdooRecord → extract integer ID
    if odoo_id is not None and not isinstance(odoo_id, int):
        try:
            if hasattr(odoo_id, "id"):
                odoo_id = int(odoo_id.id)
            elif hasattr(odoo_id, "ids") and odoo_id.ids:
                odoo_id = int(odoo_id.ids[0])
            else:
                odoo_id = int(odoo_id)
        except Exception:
            odoo_id = None
    conn.execute(
        """
        UPDATE vigil_items
        SET state = ?, state_updated_at = datetime('now'),
            raw_metadata = json_patch(COALESCE(raw_metadata, '{}'),
                           json_object('uap_odoo_id', ?))
        WHERE id = ?
        """,
        (_NEW_STATE, odoo_id, item_id),
    )
    conn.commit()


def run_uap_classifier(
    conn: sqlite3.Connection,
    odoo_env,
    max_items: int = 50,
    dry_run: bool = False,
) -> dict:
    """
    Klassificera queued UAP-items och skapa Odoo-poster för import-kandidater.

    Returns:
        dict med counts: classified, candidates, imported, skipped, errors
    """
    _ensure_state(conn)
    items = _get_candidates(conn, max_items)
    logger.info(f"[uap-classify] {len(items)} items att klassificera")

    counts = {"classified": 0, "candidates": 0, "imported": 0, "skipped": 0, "errors": 0}

    for item in items:
        title = item["title"]
        content = item["description"]
        url = item["url"]

        if dry_run:
            logger.info(f"  [DRY] {title[:60]}")
            counts["classified"] += 1
            continue

        try:
            result = classify(title=title, content=content)
        except Exception as e:
            logger.error(f"  Klassificeringsfel [{title[:40]}]: {e}")
            counts["errors"] += 1
            _mark_classified(conn, item["id"], None)
            continue

        counts["classified"] += 1

        if result.get("error"):
            logger.warning(f"  Klassificeringsvarning: {result['error']}")
            counts["errors"] += 1
            _mark_classified(conn, item["id"], None)
            continue

        conf = result.get("confidence", 0.0)
        enc_class = result.get("encounter_class") or "N"
        logger.info(
            f"  {enc_class} | conf={conf:.0%} | {title[:50]}"
        )

        if result.get("import_candidate"):
            counts["candidates"] += 1
            source_item = {
                "title": title,
                "url": url,
                "content": content[:2000],
                "published_at": item.get("published_at", ""),
            }
            try:
                odoo_id = queue_for_approval(odoo_env, result, source_item)
                if odoo_id:
                    counts["imported"] += 1
                    logger.info(f"    → Odoo pending encounter skapad: ID {odoo_id}")
                else:
                    counts["skipped"] += 1
            except Exception as e:
                logger.error(f"    Odoo-skrivfel: {e}")
                counts["errors"] += 1
                odoo_id = None

            _mark_classified(conn, item["id"], odoo_id)
        else:
            counts["skipped"] += 1
            _mark_classified(conn, item["id"], None)

    logger.info(
        f"[uap-classify] Klar: {counts['classified']} klassificerade, "
        f"{counts['candidates']} kandidater, {counts['imported']} importerade till Odoo"
    )
    return counts
