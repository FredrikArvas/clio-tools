"""
relevance_filter.py — Embeddar frågeställning + källabstracts och filtrerar på cosine-similaritet.
Körs mellan fas 6 (credibility scoring) och fas 7 (rapport).
"""

from __future__ import annotations

import logging
import math
import os

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_TOP_N = 100
MIN_SIMILARITY = 0.20


def filter_by_relevance(sources: list[dict], question: str, top_n: int = DEFAULT_TOP_N) -> list[dict]:
    """
    Filtrera källor till de top_n mest relevanta för frågeställningen.
    Lägger till 'relevance_score' (0.0–1.0) på varje källa.
    Returnerar sorterat på relevance_score * credibility_score (kombinerat).
    """
    if not sources:
        return []

    texts = [_source_text(s) for s in sources]

    try:
        embeddings = _embed([question] + texts)
    except Exception as e:
        logger.warning("[relevance_filter] Embedding misslyckades: %s — returnerar alla källor", e)
        for s in sources:
            s.setdefault("relevance_score", 0.5)
        return sources[:top_n]

    question_vec = embeddings[0]
    source_vecs = embeddings[1:]

    for source, vec in zip(sources, source_vecs):
        sim = _cosine(question_vec, vec)
        source["relevance_score"] = round(sim, 4)

    below = [s for s in sources if s.get("relevance_score", 0) < MIN_SIMILARITY]
    if below:
        logger.info(
            "[relevance_filter] %d/%d källor under similaritetsgräns %.2f filtreras bort",
            len(below), len(sources), MIN_SIMILARITY,
        )

    relevant = [s for s in sources if s.get("relevance_score", 0) >= MIN_SIMILARITY]

    relevant.sort(
        key=lambda s: s.get("relevance_score", 0) * 0.6 + (s.get("credibility_score", 0) / 18) * 0.4,
        reverse=True,
    )

    selected = relevant[:top_n]
    logger.info(
        "[relevance_filter] Valde %d relevanta källor av %d totalt (top_n=%d, min_sim=%.2f)",
        len(selected), len(sources), top_n, MIN_SIMILARITY,
    )

    if not selected:
        logger.warning(
            "[relevance_filter] VARNING: Noll relevanta källor hittades. "
            "Söktermer kanske inte matchade frågeställningen — kontrollera keywords i protokollet."
        )

    return selected


def _source_text(source: dict) -> str:
    """Kombinera titel + abstract för embedding."""
    title = source.get("title") or ""
    abstract = (source.get("abstract") or "")[:400]
    return f"{title}. {abstract}".strip()


def _embed(texts: list[str]) -> list[list[float]]:
    """Batchad embedding med OpenAI."""
    import openai
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    all_vectors = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = client.embeddings.create(input=batch, model=EMBEDDING_MODEL)
        all_vectors.extend([d.embedding for d in resp.data])

    return all_vectors


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
