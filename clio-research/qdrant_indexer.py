"""qdrant_indexer.py — Indexerar rapport-chunks i Qdrant collection vigil_research."""

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


def index_report(protocol: dict, sources: list[dict], report_path: Path, run_id: str) -> None:
    """Indexera rapport och källsammanfattningar i Qdrant."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct
    except ImportError:
        logger.warning("qdrant-client ej installerat — indexering hoppas över")
        return

    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))

    try:
        client = QdrantClient(host=host, port=port)
        _ensure_collection(client, VectorParams, Distance)
    except Exception as e:
        logger.warning("Qdrant ej tillgänglig (%s:%s): %s — indexering hoppas över", host, port, e)
        return

    chunks = _build_chunks(protocol, sources, report_path, run_id)
    if not chunks:
        logger.warning("[qdrant_indexer] Inga chunks att indexera")
        return

    texts = [c["text"] for c in chunks]
    try:
        vectors = _embed(texts)
    except Exception as e:
        logger.warning("[qdrant_indexer] Embedding misslyckades: %s", e)
        return

    points = []
    for chunk, vector in zip(chunks, vectors):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=chunk["payload"],
            )
        )

    batch_size = 50
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        try:
            client.upsert(collection_name=COLLECTION_NAME, points=batch)
        except Exception as e:
            logger.warning("[qdrant_indexer] Upsert misslyckades (batch %d): %s", i, e)

    logger.info("[qdrant_indexer] Indexerade %d chunks i %s", len(points), COLLECTION_NAME)


def _ensure_collection(client, VectorParams, Distance) -> None:
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("[qdrant_indexer] Skapade collection: %s", COLLECTION_NAME)


def _build_chunks(protocol: dict, sources: list[dict], report_path: Path, run_id: str) -> list[dict]:
    """Bygg text-chunks med metadata för indexering."""
    chunks = []
    q_summary = protocol["question"]["natural_language"][:100]

    if report_path and report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")
        words = report_text.split()
        for i in range(0, len(words), CHUNK_SIZE):
            chunk_text = " ".join(words[i:i + CHUNK_SIZE])
            chunks.append({
                "text": chunk_text,
                "payload": {
                    "protocol_id": protocol["protocol_id"],
                    "run_id": run_id,
                    "question_summary": q_summary,
                    "chunk_type": "report",
                    "chunk_index": i // CHUNK_SIZE,
                    "date": protocol.get("created", ""),
                },
            })

    top_sources = sorted(sources, key=lambda s: s.get("credibility_score", 0), reverse=True)[:20]
    for src in top_sources:
        abstract = src.get("abstract") or ""
        if not abstract:
            continue
        chunks.append({
            "text": f"{src.get('title', '')} {abstract}",
            "payload": {
                "protocol_id": protocol["protocol_id"],
                "run_id": run_id,
                "question_summary": q_summary,
                "chunk_type": "source_abstract",
                "source_title": src.get("title", ""),
                "region": src.get("region"),
                "phase": src.get("phase_found"),
                "database": src.get("database"),
                "year": src.get("year"),
                "credibility_score": src.get("credibility_score"),
                "date": protocol.get("created", ""),
            },
        })

    return chunks


def _embed(texts: list[str]) -> list[list[float]]:
    """Embedda texter med OpenAI text-embedding-3-small."""
    import openai
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    all_embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(input=batch, model=EMBEDDING_MODEL)
        all_embeddings.extend([d.embedding for d in response.data])

    return all_embeddings
