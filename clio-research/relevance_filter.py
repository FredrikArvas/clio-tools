"""
relevance_filter.py
Relevans i två steg (PLAN_research_pipeline_v2.md avsnitt 11 punkt 5).

    1. Grovsållning: frågan och varje källa (titel + sammanfattning) embeddas, och
       källor under likhetsgränsen sorteras bort. Det fångar det uppenbart orelaterade
       men släpper igenom felträffar som delar ordförråd med frågan.
    2. Relevansbedömning: insamlarmodellen skriver en mening per källa om varför den
       hör till frågan (`relevance.role` och `relevance.why`) eller märker den
       `felträff`. Modellanropet görs i ett senare steg; här finns funktionen som tar
       emot svaret, validerar det och flyttar felträffarna.

Bortsorterade källor försvinner inte. De hamnar i `01_filtered.json` med skälet
bevarat, så att granskaren kan pröva om något sorterats bort i onödan (B11).

`filter_by_relevance` är den äldre funktionen som R1.x-flödet i main.py anropar.
"""

from __future__ import annotations

import json
import logging
import math
import re

import source_model
from embedder import embed

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "2.0.0"

DEFAULT_TOP_N = 60
MIN_SIMILARITY = 0.20
EMBED_ABSTRACT_CHARS = 400

logger = logging.getLogger(__name__)


class RelevanceError(ValueError):
    """Insamlarmodellens relevanssvar går inte att använda. `problems` listar varje fel."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("Ogiltigt relevanssvar: " + "; ".join(self.problems))


# ── Steg 1: grovsållning ──────────────────────────────────────────────────────

def coarse_filter(sources: list[dict], question: str, min_similarity: float = MIN_SIMILARITY,
                  embed_fn=None) -> tuple[list[dict], list[dict]]:
    """Grovsålla källor (i källformatet) på likhet med frågan.

    Sätter `relevance.similarity` på varje källa. Källor under gränsen får
    `filtered = {"stage": "likhet", "reason": …}` och returneras för sig.

    Går embeddningen inte att göra behålls alla källor med `similarity = None`.
    Inget påhittat likhetsvärde sätts.

    Args:
        sources:        Källor enligt source_model.
        question:       Frågeställningen i klartext.
        min_similarity: Gräns för cosinuslikhet.
        embed_fn:       Funktion `list[str] -> list[list[float]]`; standard är Ollama bge-m3.

    Returns:
        (behållna, bortsorterade)
    """
    if not sources:
        return [], []
    embed_fn = embed_fn or embed
    try:
        vectors = embed_fn([question] + [_source_text(s) for s in sources])
    except Exception as e:
        logger.warning("[relevance_filter] Embedding misslyckades (%s) – ingen grovsållning gjord, "
                       "similarity lämnas tom för %d källor", e, len(sources))
        for src in sources:
            src["relevance"]["similarity"] = None
        return list(sources), []

    kept, dropped = [], []
    for src, vec in zip(sources, vectors[1:]):
        sim = round(_cosine(vectors[0], vec), 4)
        src["relevance"]["similarity"] = sim
        if sim < min_similarity:
            src["filtered"] = {
                "stage": "likhet",
                "reason": f"Likhet {sim:.2f} med frågan, under gränsen {min_similarity:.2f}.",
            }
            dropped.append(src)
        else:
            kept.append(src)

    logger.info("[relevance_filter] Grovsållning: %d behålls, %d under gränsen %.2f",
                len(kept), len(dropped), min_similarity)
    if not kept:
        logger.warning("[relevance_filter] Ingen källa över likhetsgränsen – kontrollera söktermerna i protokollet")
    return kept, dropped


# ── Steg 2: relevansbedömning ─────────────────────────────────────────────────

def parse_verdicts(reply) -> list[dict]:
    """Läs insamlarmodellens svar: en JSON-lista med `n`, `role` och `why`.

    Tar emot en färdig lista eller modellens text, där listan får ligga i ett
    kodblock eller omges av annan text.

    Raises:
        RelevanceError: om ingen JSON-lista går att läsa ut.
    """
    if isinstance(reply, list):
        return reply
    if not isinstance(reply, str):
        raise RelevanceError([f"svaret är varken lista eller text utan {type(reply).__name__}"])
    text = reply.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    elif not text.startswith("["):
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            raise RelevanceError(["svaret innehåller ingen JSON-lista"])
        text = text[start:end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RelevanceError([f"svaret är inte giltig JSON: {e}"]) from e
    if not isinstance(data, list):
        raise RelevanceError(["svaret är inte en lista"])
    return data


def apply_verdicts(sources: list[dict], reply) -> tuple[list[dict], list[dict]]:
    """Ta emot relevansbedömningen och flytta felträffarna.

    Varje källa måste ha fått exakt en bedömning. Är svaret ogiltigt ändras ingen
    källa. Felträffar får `filtered = {"stage": "relevans", "reason": why}` och
    behåller sitt `n`.

    Args:
        sources: Källor enligt source_model, alla med `n`.
        reply:   Modellens svar: lista (eller text med en JSON-lista) av
                 `{"n": 3, "role": "direkt | analogi | bakgrund | felträff", "why": "en mening"}`.

    Returns:
        (behållna till 01_sources.json, felträffar till 01_filtered.json)

    Raises:
        RelevanceError: med en rad per fel i svaret.
    """
    verdicts = parse_verdicts(reply)
    by_n = {src.get("n"): src for src in sources}
    problems: list[str] = []
    if None in by_n:
        problems.append("en eller flera källor saknar n")
    seen: dict[int, dict] = {}

    for index, verdict in enumerate(verdicts):
        if not isinstance(verdict, dict):
            problems.append(f"rad {index}: är inte ett objekt")
            continue
        n, role, why = verdict.get("n"), verdict.get("role"), verdict.get("why")
        label = f"rad {index} (n={n!r})"
        if isinstance(n, bool) or not isinstance(n, int):
            problems.append(f"{label}: n måste vara ett heltal")
            continue
        if n not in by_n:
            problems.append(f"{label}: ingen källa har det numret")
        elif n in seen:
            problems.append(f"{label}: källan bedöms mer än en gång")
        if role not in source_model.ROLES:
            problems.append(f"{label}: role {role!r} är inte en av {', '.join(source_model.ROLES)}")
        if not isinstance(why, str) or not why.strip():
            problems.append(f"{label}: why saknas")
        seen.setdefault(n, verdict)

    missing = sorted(n for n in by_n if n is not None and n not in seen)
    if missing:
        problems.append("bedömning saknas för n=" + ", ".join(str(n) for n in missing))
    if problems:
        raise RelevanceError(problems)

    kept, mismatches = [], []
    for src in sources:
        verdict = seen[src["n"]]
        why = " ".join(verdict["why"].split())
        src["relevance"]["role"] = verdict["role"]
        src["relevance"]["why"] = why
        if verdict["role"] == source_model.ROLE_MISMATCH:
            src["filtered"] = {"stage": "relevans", "reason": why}
            mismatches.append(src)
        else:
            src.pop("filtered", None)
            kept.append(src)

    logger.info("[relevance_filter] Relevansbedömning: %d behålls, %d felträffar", len(kept), len(mismatches))
    return kept, mismatches


# ── Äldre flöde (R1.x, main.py) ───────────────────────────────────────────────

def filter_by_relevance(sources: list[dict], question: str, top_n: int = DEFAULT_TOP_N) -> list[dict]:
    """Filtrera råträffar till de top_n mest lika frågan. Används av R1.x-flödet.

    Lägger till `relevance_score` på varje källa och sorterar på den. (Tidigare
    vägdes trovärdighetspoängen in; den finns inte längre.)
    """
    if not sources:
        return []

    try:
        embeddings = embed([question] + [_source_text(s) for s in sources])
    except Exception as e:
        logger.warning("[relevance_filter] Embedding misslyckades: %s — returnerar alla källor", e)
        for s in sources:
            s.setdefault("relevance_score", 0.5)
        return sources[:top_n]

    for source, vec in zip(sources, embeddings[1:]):
        source["relevance_score"] = round(_cosine(embeddings[0], vec), 4)

    relevant = [s for s in sources if s["relevance_score"] >= MIN_SIMILARITY]
    relevant.sort(key=lambda s: s["relevance_score"], reverse=True)
    selected = relevant[:top_n]
    logger.info("[relevance_filter] Valde %d relevanta källor av %d totalt (top_n=%d, min_sim=%.2f)",
                len(selected), len(sources), top_n, MIN_SIMILARITY)
    if not selected:
        logger.warning("[relevance_filter] VARNING: Noll relevanta källor hittades. "
                       "Söktermer kanske inte matchade frågeställningen — kontrollera keywords i protokollet.")
    return selected


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _source_text(source: dict) -> str:
    """Kombinera titel + sammanfattning för embedding."""
    title = source.get("title") or ""
    abstract = (source.get("abstract") or "")[:EMBED_ABSTRACT_CHARS]
    return f"{title}. {abstract}".strip()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
