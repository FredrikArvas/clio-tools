"""
clio-vigil — indexer.py
========================
Indexerar transkriberade bevakningsobjekt i Qdrant.

Återanvänder samma Qdrant-infrastruktur som clio-rag:
  - Host/port från QDRANT_HOST / QDRANT_PORT (.env)
  - Embeddings: OpenAI text-embedding-3-small (1536 dim, cosine)
  - Separata collections per domän: vigil_ufo, vigil_ai_models, ...

Flöde:
  1. Hämta objekt med state=transcribed
  2. Läs transkript-JSON (segments med start/end/text)
  3. Chunka i tidsfönster (~300 sekunder, 10% överlapp)
  4. Embed varje chunk med OpenAI
  5. Upsert till Qdrant-collection för domänen
  6. Uppdatera state → indexed

Körning:
  python indexer.py --run [--domain ufo] [--max 20]
  python indexer.py --item 42
  python indexer.py --ensure-collections   (skapa collections om de saknas)
"""

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from orchestrator import init_db, transition

logger = logging.getLogger(__name__)

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
QDRANT_HOST     = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT     = int(os.getenv("QDRANT_PORT", "6333"))
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM   = 1536

# Tidsfönster per chunk (sekunder) och överlapp
CHUNK_WINDOW_SEC  = 300   # 5 minuter per chunk
CHUNK_OVERLAP_SEC = 30    # 30 sek överlapp


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
    """Returnerar Qdrant-collection-namn för en domän, t.ex. 'vigil_ufo'."""
    return f"vigil_{domain}"


def ensure_collection(domain: str) -> None:
    """Skapar Qdrant-collection för domänen om den inte finns."""
    from qdrant_client.models import Distance, VectorParams

    client  = _get_client()
    col     = collection_name(domain)
    existing = [c.name for c in client.get_collections().collections]

    if col not in existing:
        client.create_collection(
            collection_name=col,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info(f"Collection skapad: {col}")
    else:
        logger.debug(f"Collection finns redan: {col}")


# ---------------------------------------------------------------------------
# Chunkning
# ---------------------------------------------------------------------------

def chunk_segments(segments: list[dict],
                   window_sec: int = CHUNK_WINDOW_SEC,
                   overlap_sec: int = CHUNK_OVERLAP_SEC) -> list[dict]:
    """
    Delar Whisper-segment i tidsfönster med överlapp.
    Varje chunk innehåller: text, segment_start, segment_end.

    Returnerar lista med chunk-dicts.
    """
    if not segments:
        return []

    chunks = []
    chunk_start = segments[0]["start"]
    chunk_end   = chunk_start + window_sec
    current_texts: list[str] = []
    current_seg_start = segments[0]["start"]

    for seg in segments:
        if seg["start"] >= chunk_end:
            # Stäng chunk
            if current_texts:
                chunks.append({
                    "text":          " ".join(current_texts),
                    "segment_start": current_seg_start,
                    "segment_end":   seg["start"],
                })
            # Ny chunk med överlapp: backa overlap_sec
            chunk_start       = max(chunk_end - overlap_sec, seg["start"])
            chunk_end         = chunk_start + window_sec
            current_seg_start = seg["start"]
            current_texts     = []

        current_texts.append(seg["text"])

    # Sista chunk
    if current_texts:
        chunks.append({
            "text":          " ".join(current_texts),
            "segment_start": current_seg_start,
            "segment_end":   segments[-1]["end"],
        })

    return chunks


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embeddar en lista med texter via OpenAI. Returnerar lista med vektorer."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai saknas — kör: pip install openai")

    if not OPENAI_API_KEY:
        raise EnvironmentError("OPENAI_API_KEY saknas i .env")

    client   = OpenAI(api_key=OPENAI_API_KEY)
    response = client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
    return [item.embedding for item in response.data]


# ---------------------------------------------------------------------------
# Indexering
# ---------------------------------------------------------------------------

def index_item(conn, item_id: int) -> bool:
    """
    Indexerar ett transkriberat objekt i Qdrant.
    Returnerar True om det lyckades.
    """
    from qdrant_client.models import PointStruct

    item = conn.execute(
        "SELECT * FROM vigil_items WHERE id = ?", (item_id,)
    ).fetchone()

    if not item:
        logger.error(f"Item {item_id} hittades inte")
        return False

    if not item["transcript_path"]:
        logger.warning(f"Item {item_id} saknar transcript_path")
        return False

    transcript_path = Path(item["transcript_path"])
    if not transcript_path.exists():
        logger.error(f"Transkript saknas på disk: {transcript_path}")
        return False

    segments = json.loads(transcript_path.read_text(encoding="utf-8"))
    chunks   = chunk_segments(segments)

    if not chunks:
        logger.warning(f"Item {item_id} gav inga chunks")
        return False

    domain = item["domain"]
    col    = collection_name(domain)
    ensure_collection(domain)

    # Bygg metadata som sparas per chunk
    base_meta = {
        "item_id":       item_id,
        "domain":        domain,
        "source_name":   item["source_name"] or "",
        "source_maturity": item["source_maturity"] or "tidig",
        "published_at":  item["published_at"] or "",
        "url":           item["url"],
        "title":         item["title"] or "",
    }

    # Embed alla chunks i ett anrop (max ~2048 texter per request — chunkar om nödvändigt)
    texts = [c["text"] for c in chunks]
    try:
        vectors = _embed_texts(texts)
    except Exception as e:
        logger.error(f"Embedding-fel för item {item_id}: {e}")
        return False

    # Bygg Qdrant-punkter
    points = []
    for chunk, vector in zip(chunks, vectors):
        payload = {
            **base_meta,
            "segment_start": chunk["segment_start"],
            "segment_end":   chunk["segment_end"],
            "text":          chunk["text"],
        }
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload=payload,
        ))

    client = _get_client()
    client.upsert(collection_name=col, points=points)

    transition(conn, item_id, "indexed",
               chroma_collection=col,   # återanvänder kolumnen för collection-namn
               indexed_at=_now())

    logger.info(
        f"Item {item_id} indexerad: {len(points)} chunks → {col}"
    )
    return True


# ---------------------------------------------------------------------------
# Batchkörning
# ---------------------------------------------------------------------------

def run_indexer(conn, domain: Optional[str] = None, max_items: int = 20) -> dict:
    """Indexerar alla transcribed-objekt. Returnerar räknare."""
    query = """
        SELECT id FROM vigil_items
        WHERE state = 'transcribed'
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
        description="clio-vigil indexer — indexerar transkript i Qdrant"
    )
    parser.add_argument("--run", action="store_true",
                        help="Kör batch-indexering")
    parser.add_argument("--item", type=int,
                        help="Indexera specifikt item-ID")
    parser.add_argument("--domain", type=str,
                        help="Begränsa till domän")
    parser.add_argument("--max", type=int, default=20,
                        help="Max antal objekt (default: 20)")
    parser.add_argument("--ensure-collections", action="store_true",
                        help="Skapa collections för alla konfigurerade domäner")
    args = parser.parse_args()

    conn = init_db()

    if args.ensure_collections:
        from main import get_all_domains, load_domain_config
        for d in get_all_domains():
            cfg = load_domain_config(d)
            col = collection_name(cfg.get("domain_id", d))
            ensure_collection(cfg.get("domain_id", d))
            print(f"  ✓ {col}")

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
