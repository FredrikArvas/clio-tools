"""qdrant_indexer.py — Indexerar rapport och ALLA relevanta källor i Qdrant vigil_research."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

COLLECTION_NAME = "vigil_research"
VECTOR_SIZE = 1536
EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 400
CACHE_SIMILARITY_THRESHOLD = 0.78


def index_report(protocol: dict, sources: list[dict], report_path: Path, run_id: str) -> None:
    """
    Indexera rapport-chunks + ALLA relevanta källor i Qdrant.
    sources ska vara relevansfiltrerade (relevance_score finns).
    """
    client, PointStruct = _connect()
    if client is None:
        return

    chunks = []
    q_summary = protocol["question"]["natural_language"][:100]

    # Rapport-chunks
    if report_path and report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")
        words = report_text.split()
        for i in range(0, len(words), CHUNK_SIZE):
            chunks.append({
                "text": " ".join(words[i:i + CHUNK_SIZE]),
                "payload": {
                    "type": "report_chunk",
                    "protocol_id": protocol["protocol_id"],
                    "run_id": run_id,
                    "question": q_summary,
                    "chunk_index": i // CHUNK_SIZE,
                    "date": protocol.get("created", ""),
                },
            })

    # Alla relevanta källobjekt (ej bara top-20)
    for src in sources:
        abstract = src.get("abstract") or ""
        title = src.get("title") or ""
        if not (abstract or title):
            continue
        text = f"{title}. {abstract}"[:600]
        chunks.append({
            "text": text,
            "payload": {
                "type": "source",
                "source_id": src.get("source_id", ""),
                "protocol_id": protocol["protocol_id"],
                "run_id": run_id,
                "question": q_summary,
                "title": title,
                "authors": src.get("authors", [])[:3],
                "year": src.get("year"),
                "region": src.get("region"),
                "database": src.get("database"),
                "doi": src.get("doi"),
                "fulltext_url": src.get("fulltext_url"),
                "credibility_score": src.get("credibility_score"),
                "relevance_score": src.get("relevance_score"),
                "date": protocol.get("created", ""),
            },
        })

    if not chunks:
        logger.warning("[qdrant_indexer] Inga chunks att indexera")
        return

    try:
        vectors = _embed([c["text"] for c in chunks])
    except Exception as e:
        logger.warning("[qdrant_indexer] Embedding misslyckades: %s", e)
        return

    points = [
        PointStruct(id=str(uuid.uuid4()), vector=v, payload=c["payload"])
        for c, v in zip(chunks, vectors)
    ]

    batch_size = 50
    indexed = 0
    for i in range(0, len(points), batch_size):
        try:
            client.upsert(collection_name=COLLECTION_NAME, points=points[i:i + batch_size])
            indexed += len(points[i:i + batch_size])
        except Exception as e:
            logger.warning("[qdrant_indexer] Upsert misslyckades (batch %d): %s", i, e)

    logger.info("[qdrant_indexer] Indexerade %d chunks (%d källobjekt + rapport) i %s",
                indexed, len(sources), COLLECTION_NAME)


def load_cached_sources(question: str, top_k: int = 30) -> list[dict]:
    """
    Hämta relevanta källobjekt från tidigare körningar.
    Returnerar lista av source-dicts markerade med from_cache=True.
    Anropas i fas 1 innan API-sökningar startar.
    """
    client, _ = _connect()
    if client is None:
        return []

    try:
        q_vector = _embed([question])[0]
    except Exception as e:
        logger.warning("[qdrant_indexer] Cache-embedding misslyckades: %s", e)
        return []

    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        result = client.query_points(
            collection_name=COLLECTION_NAME,
            query=q_vector,
            limit=top_k,
            score_threshold=CACHE_SIMILARITY_THRESHOLD,
            query_filter=Filter(
                must=[FieldCondition(key="type", match=MatchValue(value="source"))]
            ),
        )
        hits = result.points
    except Exception as e:
        logger.warning("[qdrant_indexer] Cache-sökning misslyckades: %s", e)
        return []

    sources = []
    for hit in hits:
        p = hit.payload
        sources.append({
            "source_id": p.get("source_id", ""),
            "title": p.get("title", ""),
            "authors": p.get("authors", []),
            "year": p.get("year"),
            "region": p.get("region"),
            "database": p.get("database"),
            "doi": p.get("doi"),
            "fulltext_url": p.get("fulltext_url"),
            "credibility_score": p.get("credibility_score"),
            "relevance_score": round(hit.score, 4),
            "abstract": None,
            "phase_found": 0,
            "from_cache": True,
        })

    if sources:
        logger.info("[qdrant_indexer] Laddade %d cachade källor (sim >= %.2f)",
                    len(sources), CACHE_SIMILARITY_THRESHOLD)

    return sources


def _connect():
    """Returnerar (QdrantClient, PointStruct) eller (None, None) om ej tillgänglig."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct
    except ImportError:
        logger.warning("qdrant-client ej installerat")
        return None, None

    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))
    url = f"http://{host}:{port}"

    try:
        client = QdrantClient(url=url, check_compatibility=False)
        _ensure_collection(client, VectorParams, Distance)
        return client, PointStruct
    except Exception as e:
        logger.warning("Qdrant ej tillgänglig (%s): %s — indexering hoppas över", url, e)
        return None, None


def _ensure_collection(client, VectorParams, Distance) -> None:
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("[qdrant_indexer] Skapade collection: %s", COLLECTION_NAME)


def _embed(texts: list[str]) -> list[list[float]]:
    import openai
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    all_vecs = []
    for i in range(0, len(texts), 100):
        resp = client.embeddings.create(input=texts[i:i + 100], model=EMBEDDING_MODEL)
        all_vecs.extend([d.embedding for d in resp.data])
    return all_vecs
