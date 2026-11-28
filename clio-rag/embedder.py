"""
embedder.py — Lokal embedding via Ollama (bge-m3, 1024 dims).

Används av ingest-skript och query.py.
Ingen extern API-nyckel krävs — kräver att Ollama körs på OLLAMA_HOST.
SSH-tunnel om EliteDesk inte är direkt nåbar:
  ssh -L 11434:localhost:11434 clioadmin@100.107.127.104
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def embed(texts: list[str]) -> list[list[float]]:
    """
    Embeddar en lista texter med Ollama bge-m3.
    Returnerar en lista av 1024-dimensionella vektorer.
    Kastar RuntimeError om Ollama inte svarar.
    """
    import ollama
    from config import EMBEDDING_MODEL, OLLAMA_HOST

    client = ollama.Client(host=OLLAMA_HOST)
    all_vectors: list[list[float]] = []

    for text in texts:
        try:
            resp = client.embeddings(model=EMBEDDING_MODEL, prompt=text)
            all_vectors.append(resp["embedding"])
        except Exception as e:
            raise RuntimeError(
                f"Ollama embedding misslyckades (host={OLLAMA_HOST}, modell={EMBEDDING_MODEL}): {e}"
            ) from e

    return all_vectors
