"""qdrant_index.py — Indexera UAP-encounters i Qdrant för semantisk sökning.

Collection: vigil_uap
Embeddings: OpenAI text-embedding-3-small
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))


COLLECTION_NAME = "vigil_uap"
VECTOR_SIZE     = 1536  # text-embedding-3-small


def _qdrant_client():
    import config
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        sys.exit("qdrant-client saknas. Kör: pip install qdrant-client")
    return QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)


def _embed(texts: list[str]) -> list[list[float]]:
    import config
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai saknas. Kör: pip install openai")
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.embeddings.create(model=config.EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def _ensure_collection(client) -> None:
    from qdrant_client.models import VectorParams, Distance
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        print(f"[qdrant] Collection '{COLLECTION_NAME}' skapad.")
    else:
        print(f"[qdrant] Collection '{COLLECTION_NAME}' finns redan.")


def index_all(dry_run: bool = False, batch_size: int = 50) -> None:
    from odoo_sync import get_env
    from qdrant_client.models import PointStruct

    env = get_env()
    encounters = env["uap.encounter"].search_read(
        [],
        ["id", "encounter_id", "title_en", "title_original",
         "description_en", "country_id", "encounter_class",
         "discourse_level", "status", "date_observed"],
    )
    print(f"[qdrant] {len(encounters)} encounters att indexera")

    if dry_run:
        print("[qdrant] Dry-run — ingenting skrivs till Qdrant")
        for e in encounters[:5]:
            title = e.get("title_en") or e.get("title_original") or e["encounter_id"]
            print(f"  → {e['encounter_id']} | {title[:60]}")
        return

    client = _qdrant_client()
    _ensure_collection(client)

    # Bygg text för indexering och metadata
    def _text(enc: dict) -> str:
        parts = [
            enc.get("title_en") or enc.get("title_original") or "",
            enc.get("description_en") or "",
        ]
        return "\n\n".join(p for p in parts if p).strip()

    total = 0
    for i in range(0, len(encounters), batch_size):
        batch = encounters[i : i + batch_size]
        texts = [_text(e) for e in batch]

        # Hoppa över tomma
        non_empty = [(j, e, t) for j, (e, t) in enumerate(zip(batch, texts)) if t]
        if not non_empty:
            continue

        embeddings = _embed([t for _, _, t in non_empty])

        points = []
        for (_, enc, _), vector in zip(non_empty, embeddings):
            country = enc["country_id"][1] if enc.get("country_id") else ""
            points.append(PointStruct(
                id     = enc["id"],
                vector = vector,
                payload = {
                    "encounter_id":    enc["encounter_id"],
                    "title":           enc.get("title_en") or enc.get("title_original") or "",
                    "country":         country,
                    "encounter_class": enc.get("encounter_class") or "",
                    "discourse_level": enc.get("discourse_level") or "",
                    "status":          enc.get("status") or "",
                    "date_observed":   str(enc.get("date_observed") or ""),
                },
            ))

        client.upsert(collection_name=COLLECTION_NAME, points=points)
        total += len(points)
        print(f"  Indexerade {total}/{len(encounters)}...")

    print(f"[qdrant] Indexering klar. {total} encounters i '{COLLECTION_NAME}'.")


def search(query: str, top_k: int = 5, filters: dict | None = None) -> list[dict]:
    """Semantisk sökning mot vigil_uap. Returnerar lista av payload-dicts."""
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    client = _qdrant_client()
    embedding = _embed([query])[0]

    qdrant_filter = None
    if filters:
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filters.items()
        ]
        qdrant_filter = Filter(must=conditions)

    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=embedding,
        limit=top_k,
        query_filter=qdrant_filter,
    )
    return [{"score": r.score, **r.payload} for r in results]


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--search", default=None, help="Testfråga mot index")
    args = p.parse_args()
    if args.search:
        hits = search(args.search)
        for h in hits:
            print(f"  [{h['score']:.3f}] {h['encounter_id']} — {h.get('title', '')}")
    else:
        index_all(dry_run=args.dry_run)
