"""
clio-vigil — indexer.py
========================
Indexerar transkriberade bevakningsobjekt i Qdrant.

Embeddings: Ollama bge-m3 (1024 dim, cosine) — körs lokalt på EliteDesk GPU.
Ingen extern API-nyckel behövs.

Flöde:
  1. Hämta objekt med state=transcribed/captioned
  2. Läs transkript-JSON (segments med start/end/text) eller .txt
  3. Chunka i tidsfönster (~300 sekunder, 10% överlapp) eller ord
  4. Embed varje chunk med Ollama bge-m3
  5. Upsert till Qdrant-collection för domänen
  6. Uppdatera state → indexed

Körning:
  python indexer.py --run [--domain ufo] [--max 20]
  python indexer.py --item 42
  python indexer.py --ensure-collections   (skapa collections om de saknas)
  python indexer.py --recreate-collections (radera + återskapa, t.ex. vid dim-ändring)
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from orchestrator import init_db, transition

logger = logging.getLogger(__name__)

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

OLLAMA_HOST     = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("VIGIL_EMBED_MODEL", "bge-m3")
EMBEDDING_DIM   = 1024

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

# Tidsfönster per chunk (sekunder) och överlapp — audio/video
CHUNK_WINDOW_SEC  = 300
CHUNK_OVERLAP_SEC = 30

# Ordfönster per chunk — text (webb/rss)
CHUNK_WORDS         = 500
CHUNK_WORDS_OVERLAP = 100


# ---------------------------------------------------------------------------
# Qdrant-klient och collection-hantering
# ---------------------------------------------------------------------------

def _get_client():
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        raise ImportError("qdrant-client saknas — kör: pip install qdrant-client")
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def collection_name(domain: str) -> str:
    return f"vigil_{domain}"


def ensure_collection(domain: str) -> None:
    """Skapar Qdrant-collection för domänen om den inte finns."""
    from qdrant_client.models import Distance, VectorParams

    client   = _get_client()
    col      = collection_name(domain)
    existing = [c.name for c in client.get_collections().collections]

    if col not in existing:
        client.create_collection(
            collection_name=col,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info("Collection skapad: %s (%d dim)", col, EMBEDDING_DIM)
    else:
        logger.debug("Collection finns redan: %s", col)


def recreate_collection(domain: str) -> None:
    """Raderar och återskapar collection — används vid dim-byte."""
    from qdrant_client.models import Distance, VectorParams

    client   = _get_client()
    col      = collection_name(domain)
    existing = [c.name for c in client.get_collections().collections]

    if col in existing:
        client.delete_collection(col)
        logger.info("Collection raderad: %s", col)

    client.create_collection(
        collection_name=col,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )
    logger.info("Collection återskapad: %s (%d dim)", col, EMBEDDING_DIM)


# ---------------------------------------------------------------------------
# Chunkning
# ---------------------------------------------------------------------------

def chunk_segments(segments: list[dict],
                   window_sec: int = CHUNK_WINDOW_SEC,
                   overlap_sec: int = CHUNK_OVERLAP_SEC) -> list[dict]:
    """Delar Whisper-segment i tidsfönster med överlapp."""
    if not segments:
        return []

    chunks: list[dict]  = []
    chunk_start         = segments[0]["start"]
    chunk_end           = chunk_start + window_sec
    current_texts:      list[str] = []
    current_seg_start   = segments[0]["start"]

    for seg in segments:
        if seg["start"] >= chunk_end:
            if current_texts:
                chunks.append({
                    "text":          " ".join(current_texts),
                    "segment_start": current_seg_start,
                    "segment_end":   seg["start"],
                })
            chunk_start       = max(chunk_end - overlap_sec, seg["start"])
            chunk_end         = chunk_start + window_sec
            current_seg_start = seg["start"]
            current_texts     = []
        current_texts.append(seg["text"])

    if current_texts:
        chunks.append({
            "text":          " ".join(current_texts),
            "segment_start": current_seg_start,
            "segment_end":   segments[-1]["end"],
        })

    return chunks


def chunk_text(text: str,
               words_per_chunk: int = CHUNK_WORDS,
               overlap: int = CHUNK_WORDS_OVERLAP) -> list[dict]:
    """Delar fritext i ord-baserade fönster med överlapp."""
    words = text.split()
    if not words:
        return []

    chunks: list[dict] = []
    step = words_per_chunk - overlap
    i    = 0
    while i < len(words):
        end   = min(i + words_per_chunk, len(words))
        chunk = " ".join(words[i:end])
        chunks.append({"text": chunk, "segment_start": i, "segment_end": end})
        if end == len(words):
            break
        i += step

    return chunks


# ---------------------------------------------------------------------------
# Embeddings via Ollama
# ---------------------------------------------------------------------------

def _embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embeddar en lista med texter via Ollama (bge-m3 lokalt).
    Skickar max 32 texter per request.
    """
    BATCH = 32
    all_vectors: list[list[float]] = []

    for i in range(0, len(texts), BATCH):
        batch = texts[i : i + BATCH]
        resp = httpx.post(
            f"{OLLAMA_HOST}/api/embed",
            json={"model": EMBEDDING_MODEL, "input": batch},
            timeout=300.0,
        )
        resp.raise_for_status()
        data       = resp.json()
        embeddings = data.get("embeddings", [])
        if len(embeddings) != len(batch):
            raise ValueError(
                f"Ollama returnerade {len(embeddings)} vektorer för {len(batch)} texter"
            )
        all_vectors.extend(embeddings)

    return all_vectors


# ---------------------------------------------------------------------------
# Indexering
# ---------------------------------------------------------------------------

def index_item(conn, item_id: int) -> bool:
    """Indexerar ett transkriberat objekt i Qdrant. Returnerar True om det lyckades."""
    from qdrant_client.models import PointStruct

    item = conn.execute(
        "SELECT * FROM vigil_items WHERE id = ?", (item_id,)
    ).fetchone()

    if not item:
        logger.error("Item %d hittades inte", item_id)
        return False

    if not item["transcript_path"]:
        logger.warning("Item %d saknar transcript_path", item_id)
        return False

    transcript_path = Path(item["transcript_path"])
    if not transcript_path.exists():
        logger.error("Transkript saknas på disk: %s", transcript_path)
        return False

    source_type = item["source_type"] or "rss"

    if source_type in ("web", "pdf"):
        text   = transcript_path.read_text(encoding="utf-8")
        chunks = chunk_text(text)
    else:
        try:
            segments = json.loads(transcript_path.read_text(encoding="utf-8"))
            chunks   = chunk_segments(segments)
        except Exception:
            text   = transcript_path.read_text(encoding="utf-8")
            chunks = chunk_text(text)

    if not chunks:
        logger.warning("Item %d gav inga chunks", item_id)
        return False

    domain = item["domain"]
    col    = collection_name(domain)
    ensure_collection(domain)

    base_meta = {
        "item_id":         item_id,
        "domain":          domain,
        "source_name":     item["source_name"] or "",
        "source_maturity": item["source_maturity"] or "tidig",
        "published_at":    item["published_at"] or "",
        "url":             item["url"],
        "title":           item["title"] or "",
    }

    texts = [c["text"] for c in chunks]
    try:
        vectors = _embed_texts(texts)
    except Exception as exc:
        logger.error("Embedding-fel för item %d: %s", item_id, exc)
        return False

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                **base_meta,
                "segment_start": c["segment_start"],
                "segment_end":   c["segment_end"],
                "text":          c["text"],
            },
        )
        for c, vector in zip(chunks, vectors)
    ]

    client = _get_client()
    client.upsert(collection_name=col, points=points)

    transition(conn, item_id, "indexed",
               chroma_collection=col,
               indexed_at=_now())

    logger.info("Item %d indexerad: %d chunks → %s", item_id, len(points), col)
    return True


# ---------------------------------------------------------------------------
# Batchkörning
# ---------------------------------------------------------------------------

def run_indexer(conn, domain: Optional[str] = None, max_items: int = 20) -> dict:
    """Indexerar alla transcribed/captioned-objekt. Returnerar räknare."""
    query = """
        SELECT id FROM vigil_items
        WHERE state IN ('transcribed', 'captioned')
          {}
        ORDER BY priority_score DESC
        LIMIT ?
    """.format("AND domain = ?" if domain else "")

    params = (domain, max_items) if domain else (max_items,)
    rows   = conn.execute(query, params).fetchall()

    counts = {"indexed": 0, "failed": 0}
    for row in rows:
        ok = index_item(conn, row["id"])
        counts["indexed" if ok else "failed"] += 1

    return counts


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="clio-vigil indexer — Ollama bge-m3 + Qdrant"
    )
    parser.add_argument("--run",                  action="store_true", help="Kör batch-indexering")
    parser.add_argument("--item",                 type=int,            help="Indexera specifikt item-ID")
    parser.add_argument("--domain",               type=str,            help="Begränsa till domän")
    parser.add_argument("--max",                  type=int, default=20, help="Max antal objekt (default: 20)")
    parser.add_argument("--ensure-collections",   action="store_true", help="Skapa collections om de saknas")
    parser.add_argument("--recreate-collections", action="store_true", help="Radera + återskapa collections")
    args = parser.parse_args()

    conn = init_db()

    if args.recreate_collections:
        domains = [args.domain] if args.domain else ["ufo", "ai", "research"]
        for d in domains:
            recreate_collection(d)
            print(f"  ✓ vigil_{d} återskapad ({EMBEDDING_DIM} dim)")

    elif args.ensure_collections:
        domains = [args.domain] if args.domain else ["ufo", "ai", "research"]
        for d in domains:
            ensure_collection(d)
            print(f"  ✓ vigil_{d}")

    elif args.item:
        ok = index_item(conn, args.item)
        print("✓ Indexerad" if ok else "✗ Misslyckades")

    elif args.run:
        counts = run_indexer(conn, domain=args.domain, max_items=args.max)
        print(f"\n✓ Indexering: {counts['indexed']} indexerade, {counts['failed']} misslyckade")

    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    _main()
