"""media_coder.py — Kodar nyhetsartiklar per coding_scheme via Claude API."""

from __future__ import annotations

import json
import logging
import os
import re

MODEL_SONNET = "claude-sonnet-4-6"
BATCH_SIZE = 10
MAX_TOKENS = 2048

logger = logging.getLogger(__name__)


def code_articles(articles: list[dict], protocol: dict) -> list[dict]:
    """
    Koda varje artikel med protokollets coding_scheme.
    Returnerar artiklar med tillagda 'coding'-fält.
    """
    import anthropic

    coding_scheme = protocol.get("coding_scheme", {})
    temporal_markers = protocol.get("temporal_markers", {}).get("markers", [])
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    coded: list[dict] = []
    total = len(articles)

    for i in range(0, total, BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        results = _code_batch(client, batch, coding_scheme, temporal_markers)
        coded.extend(results)
        logger.info("[media_coder] Kodade %d/%d artiklar", min(i + BATCH_SIZE, total), total)

    return coded


def _code_batch(
    client,
    batch: list[dict],
    coding_scheme: dict,
    temporal_markers: list[dict],
) -> list[dict]:
    """Koda en batch med ett Claude-anrop."""
    prompt = _build_prompt(batch, coding_scheme, temporal_markers)
    try:
        msg = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        codings = _parse_response(msg.content[0].text)
    except Exception as e:
        logger.warning("[media_coder] Batch-kodning misslyckades: %s", e)
        codings = []

    return _merge_codings(batch, codings)


def _build_prompt(
    batch: list[dict],
    coding_scheme: dict,
    temporal_markers: list[dict],
) -> str:
    scheme_text = _format_scheme(coding_scheme)
    markers_text = "\n".join(f"{m['date']}: {m['label']}" for m in temporal_markers)
    articles_text = _format_articles(batch)

    return (
        "Du är en medieanalytiker. Koda varje artikel enligt kodningsschemat nedan.\n\n"
        f"KODNINGSSCHEMA:\n{scheme_text}\n\n"
        f"TIDSMARKÖRER (matcha om artikelns datum ligger ±30 dagar):\n{markers_text}\n\n"
        f"ARTIKLAR:\n{articles_text}\n\n"
        f"Svara ENBART med JSON-array (index 0–{len(batch) - 1}):\n"
        '[{"index": 0, "tone": "...", "article_type": "...", '
        '"cited_actors": [...], "thematic_frame": "...", '
        '"temporal_marker_match": "YYYY-MM-DD eller null"}, ...]\n\n'
        "Använd exakt de värden som anges i kodningsschemat."
    )


def _format_scheme(scheme: dict) -> str:
    parts = []
    if tone := scheme.get("tone"):
        parts.append(f"ton: {tone.get('values')} — {tone.get('definition', '')}")
    if atype := scheme.get("article_type"):
        parts.append(f"article_type: {atype.get('values')} — {atype.get('definition', '')}")
    if actors := scheme.get("cited_actors"):
        parts.append(f"cited_actors (lista, kan vara fler): {actors.get('categories')}")
    if frame := scheme.get("thematic_frame"):
        parts.append(f"thematic_frame (välj primär): {frame.get('values')}")
    return "\n".join(parts)


def _format_articles(batch: list[dict]) -> str:
    lines = []
    for i, a in enumerate(batch):
        lines.append(
            f"[{i}] Titel: {a.get('title', '?')}\n"
            f"    Källa: {a.get('outlet', '?')} ({a.get('country', '?')})\n"
            f"    Datum: {a.get('date', '?')}\n"
            f"    Utdrag: {(a.get('snippet') or '')[:300]}"
        )
    return "\n\n".join(lines)


def _parse_response(raw: str) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group())
    except json.JSONDecodeError as e:
        logger.warning("[media_coder] JSON-parsning misslyckades: %s", e)
        return []


def _merge_codings(batch: list[dict], codings: list[dict]) -> list[dict]:
    coding_map = {c.get("index"): c for c in codings}
    result = []
    for i, article in enumerate(batch):
        c = coding_map.get(i, {})
        merged = dict(article)
        merged["coding"] = {
            "tone": c.get("tone", "oklar"),
            "article_type": c.get("article_type", "oklar"),
            "cited_actors": c.get("cited_actors") or [],
            "thematic_frame": c.get("thematic_frame", "okategoriserad"),
            "temporal_marker_match": c.get("temporal_marker_match"),
        }
        result.append(merged)
    return result
