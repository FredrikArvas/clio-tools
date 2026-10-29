"""
embedder.py — Lokal embedding via Ollama (bge-m3, 1024 dims).

Används av relevance_filter.py och qdrant_indexer.py.
Ingen extern API-nyckel krävs — kräver att Ollama körs lokalt eller på servern.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "bge-m3"
VECTOR_SIZE = 1024

_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def embed(texts: list[str]) -> list[list[float]]:
    """
    Embeddar en lista texter med Ollama bge-m3.
    Returnerar en lista av 1024-dimensionella vektorer.
    Kastar RuntimeError om Ollama inte svarar.
    """
    import ollama

    client = ollama.Client(host=_OLLAMA_HOST)
    all_vectors: list[list[float]] = []

    for text in texts:
        try:
            resp = client.embeddings(model=EMBEDDING_MODEL, prompt=text)
            all_vectors.append(resp["embedding"])
        except Exception as e:
            raise RuntimeError(
                f"Ollama embedding misslyckades (host={_OLLAMA_HOST}, modell={EMBEDDING_MODEL}): {e}"
            ) from e

    return all_vectors
