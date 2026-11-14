"""
clio-vigil — classifiers/uap_classifier.py
===========================================
Klassificerar UAP-innehåll med Claude Sonnet via prenumerationen (`claude -p`,
se claude_backend.py). Vid kvotgräns kastas SubscriptionLimitError och posten
väntar till nästa körning — kvalitet går före tid, ingen lokal fallback.

Returnerar:
    encounter_class   : "1"–"4" (eller None om ej applicerbart)
    discourse_level   : "1"–"5"
    official_response : "A"–"E"
    confidence        : 0.0–1.0
    summary           : kort beskrivning (2-3 meningar)
    import_candidate  : True om confidence > CONFIDENCE_THRESHOLD

Objekt med import_candidate=True läggs i Odoo approval-kö (status=pending).
Fredrik godkänner manuellt innan auto-import sker.
"""

from __future__ import annotations

import json
import logging
import os
import re

import claude_backend

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.70
CLASSIFIER_MODEL = os.getenv("UAP_CLASSIFIER_MODEL", claude_backend.MODEL_SONNET)
MAX_CONTENT_CHARS = 2000

_SYSTEM_PROMPT = """\
Du är UAP-analytiker och klassificerar innehåll enligt ett fastställt system.

Encounter Classification:
  1 = Sighting (observasjon utan fysiska spår)
  2 = Close Encounter (interaktion / reaktion hos vittne/fordon)
  3 = Physical Evidence (spår, foto, radar, mätdata)
  4 = Abduction / Contact (direkt kontakt med icke-mänsklig intelligens)
  N = Ej tillämpbart (debatt, nyhetsanalys, historik utan ny incident)

Discourse Level:
  1 = Fringe / Unknown
  2 = Limited Public Awareness
  3 = Active Public Debate
  4 = Official Acknowledgement
  5 = Confirmed / Declassified

Official Response:
  A = No Response
  B = Denial
  C = Acknowledgement
  D = Investigation
  E = Confirmation

Svara ENBART med giltig JSON, inget annat.
"""

_USER_TEMPLATE = """\
Klassificera följande UAP-innehåll:

TITEL: {title}

INNEHÅLL:
{content}

Svara med JSON:
{{
  "encounter_class": "1"|"2"|"3"|"4"|"N",
  "discourse_level": "1"|"2"|"3"|"4"|"5",
  "official_response": "A"|"B"|"C"|"D"|"E",
  "confidence": 0.0–1.0,
  "summary": "2-3 meningar på svenska",
  "reasoning": "kort motivering på svenska"
}}
"""


def classify(title: str, content: str, model: str = CLASSIFIER_MODEL) -> dict:
    """
    Klassificera UAP-innehåll.

    Returns:
        dict med encounter_class, discourse_level, official_response,
        confidence, summary, reasoning, import_candidate, error.
        error sätts när svaret inte gick att tolka.

    Raises:
        claude_backend.SubscriptionLimitError: kvoten är nådd.
        RuntimeError: claude -p misslyckades (timeout, fel, tomt svar).
    """
    user_message = _USER_TEMPLATE.format(title=title, content=content[:MAX_CONTENT_CHARS])
    raw = claude_backend.call_subscription(_SYSTEM_PROMPT, user_message, model)
    result = _parse_json(raw)
    if result is None:
        return _error_result(f"Inget giltigt JSON i svar: {raw[:200]}")
    return _normalize(result)


def _parse_json(raw: str) -> dict | None:
    """Tolkar svaret som JSON, eller det första {...}-blocket i det."""
    for candidate in (raw, *re.findall(r"\{.*\}", raw, re.DOTALL)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize(result: dict) -> dict:
    """Begränsar fälten till giltiga värden."""
    enc_class = str(result.get("encounter_class", "N"))
    if enc_class not in ("1", "2", "3", "4", "N"):
        enc_class = "N"

    disc = str(result.get("discourse_level", "1"))
    if disc not in ("1", "2", "3", "4", "5"):
        disc = "1"

    off = result.get("official_response", "A")
    if off not in ("A", "B", "C", "D", "E"):
        off = "A"

    confidence = float(result.get("confidence", 0.0))
    confidence = max(0.0, min(1.0, confidence))

    return {
        "encounter_class":   enc_class if enc_class != "N" else False,
        "discourse_level":   disc,
        "official_response": off,
        "confidence":        confidence,
        "summary":           result.get("summary", ""),
        "reasoning":         result.get("reasoning", ""),
        "import_candidate":  confidence >= CONFIDENCE_THRESHOLD and enc_class != "N",
        "error":             None,
    }


def _error_result(msg: str) -> dict:
    return {
        "encounter_class":   False,
        "discourse_level":   "1",
        "official_response": "A",
        "confidence":        0.0,
        "summary":           "",
        "reasoning":         "",
        "import_candidate":  False,
        "error":             msg,
    }


def queue_for_approval(odoo_env, classification: dict, source_item: dict) -> int | None:
    """
    Skapa en uap.encounter i Odoo med status=pending för manuellt godkännande.

    Args:
        odoo_env:       clio_odoo connector
        classification: Resultat från classify()
        source_item:    Dict med title, url, content, published_at

    Returns:
        Odoo record ID eller None vid fel
    """
    if not classification.get("import_candidate"):
        return None

    import re
    title = source_item.get("title", "")[:255]

    # Auto-generera encounter_id: AUTO_YYYY_NNNN
    # I praktiken bör Fredrik tilldela ett riktigt ID vid godkännande
    import datetime
    year = datetime.date.today().year
    auto_id = f"AUTO_{year}_{abs(hash(title)) % 9999:04d}"

    vals = {
        "encounter_id":    auto_id,
        "title_en":        title,
        "description_en":  source_item.get("content", "")[:2000],
        "research_notes":  (
            f"[SRC] {source_item.get('url', '')}\n"
            f"[AUTO] Klassificerat {datetime.date.today()} av clio-vigil\n"
            f"Confidence: {classification['confidence']:.0%}\n"
            f"Reasoning: {classification.get('reasoning', '')}"
        ),
        "encounter_class":   classification.get("encounter_class") or False,
        "discourse_level":   classification.get("discourse_level"),
        "official_response": classification.get("official_response"),
        "status":            "pending",
    }

    try:
        return odoo_env["uap.encounter"].create(vals)
    except Exception as e:
        logger.error(f"Odoo-skrivfel: {e}")
        return None
