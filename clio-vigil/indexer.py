"""
clio-vigil — indexer.py
========================
Indexerar transkriberade bevakningsobjekt i Qdrant.

Embeddings: Ollama bge-m3 (1024 dim, cosine) — körs lokalt på EliteDesk GPU.
Ingen extern API-nyckel behövs.

Flöde:
  1. Hämta objekt med state=transcribed/captioned/uap_classified
  2. Läs transkript-JSON (segments med start/end/text) eller .txt
  3. Chunka i tidsfönster (~300 sekunder, 10% överlapp) eller ord
  4. Embed högst MAX_CHUNKS_PER_RUN nya chunks med Ollama bge-m3 (resten nästa körning
     via indexed_chunks-offset -- långa poddar hänger inte längre en hel körning)
  5. Upsert till Qdrant-collection för domänen
  6. Klart → state=indexed. Fel (t.ex. Ollama-timeout) → state=crashed +
     error_message, blockerar inte resten av kön.

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

# Max antal NYA chunks som embeddas per item och körning. Långa poddar (100+ chunks)
# skulle annars hänga en hel körning i väntan på Ollama — resten tas nästa körning
# via indexed_chunks-offset.
MAX_CHUNKS_PER_RUN = 24

# Antal texter per Ollama-anrop. Litet av flit: sparar indexed_chunks-progress
# EFTER varje lyckad delbatch (se index_item), så en trög/timeoutad batch bara
# kostar EMBED_BATCH_SIZE chunks nästa gång i stället för hela körningens arbete.
EMBED_BATCH_SIZE = 3


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

def _embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embeddar EN batch texter (max EMBED_BATCH_SIZE) via Ollama i ett enda anrop.
    Höjer undantag vid fel/timeout -- anroparen (index_item) ansvarar för att
    spara redan gjord progress innan den propagerar vidare.
    """
    resp = httpx.post(
        f"{OLLAMA_HOST}/api/embed",
        json={"model": EMBEDDING_MODEL, "input": texts},
        timeout=300.0,
    )
    resp.raise_for_status()
    data       = resp.json()
    embeddings = data.get("embeddings", [])
    if len(embeddings) != len(texts):
        raise ValueError(
            f"Ollama returnerade {len(embeddings)} vektorer för {len(texts)} texter"
        )
    return embeddings


# ---------------------------------------------------------------------------
# Indexering
# ---------------------------------------------------------------------------

def index_item(conn, item_id: int) -> str:
    """
    Indexerar (eller fortsätter indexera) ett transkriberat objekt i Qdrant.

    Embeddar högst MAX_CHUNKS_PER_RUN nya chunks per anrop -- långa poddar med
    många chunks fortsätter automatiskt över flera körningar via indexed_chunks-
    offset i stället för att hänga hela körningen. Fel (t.ex. Ollama-timeout)
    får propagera till anroparen, som ansvarar för att markera objektet 'crashed'.

    Returnerar "indexed" (klar), "partial" (fortsätter nästa körning) eller
    "skipped" (inget att indexera).
    """
    from qdrant_client.models import PointStruct

    item = conn.execute(
        "SELECT * FROM vigil_items WHERE id = ?", (item_id,)
    ).fetchone()

    if not item:
        logger.error("Item %d hittades inte", item_id)
        return "skipped"

    source_type = item["source_type"] or "rss"

    if not item["transcript_path"] or not Path(item["transcript_path"]).exists():
        fallback_parts = [p for p in [item["title"], item["description"]] if p]
        if not fallback_parts:
            logger.warning("Item %d saknar både transkript och text -- hoppas över", item_id)
            return "skipped"
        logger.info("Item %d saknar transkript -- indexerar rubrik+beskrivning", item_id)
        chunks = chunk_text(" ".join(fallback_parts))
    elif source_type in ("web", "pdf"):
        transcript_path = Path(item["transcript_path"])
        text   = transcript_path.read_text(encoding="utf-8")
        chunks = chunk_text(text)
    else:
        transcript_path = Path(item["transcript_path"])
        try:
            segments = json.loads(transcript_path.read_text(encoding="utf-8"))
            chunks   = chunk_segments(segments)
        except Exception:
            text   = transcript_path.read_text(encoding="utf-8")
            chunks = chunk_text(text)

    if not chunks:
        logger.warning("Item %d gav inga chunks", item_id)
        return "skipped"

    # Redan embeddade chunks från en tidigare (avbruten) körning på samma item.
    already = item["indexed_chunks"] or 0
    if already >= len(chunks):
        # Chunkningen gav färre chunks än tidigare (t.ex. omtranskriberat) -- börja om.
        already = 0

    pending = chunks[already:]
    window  = pending[:MAX_CHUNKS_PER_RUN]

    domain = item["domain"]
    col    = collection_name(domain)
    ensure_collection(domain)
    client = _get_client()

    base_meta = {
        "item_id":         item_id,
        "domain":          domain,
        "source_name":     item["source_name"] or "",
        "source_maturity": item["source_maturity"] or "tidig",
        "published_at":    item["published_at"] or "",
        "url":             item["url"],
        "title":           item["title"] or "",
    }

    progress = already

    # En delbatch i taget: upsert + spara indexed_chunks direkt efter varje lyckad
    # Ollama-anrop. Om ett senare anrop kraschar/timear ut går tidigare delbatcher
    # inte förlorade -- nästa körning fortsätter från senast sparade progress.
    for i in range(0, len(window), EMBED_BATCH_SIZE):
        sub_chunks = window[i : i + EMBED_BATCH_SIZE]
        texts      = [c["text"] for c in sub_chunks]
        vectors    = _embed_batch(texts)

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
            for c, vector in zip(sub_chunks, vectors)
        ]
        client.upsert(collection_name=col, points=points)

        progress += len(sub_chunks)
        conn.execute("UPDATE vigil_items SET indexed_chunks = ? WHERE id = ?",
                     (progress, item_id))
        conn.commit()

    if progress >= len(chunks):
        transition(conn, item_id, "indexed",
                   chroma_collection=col,
                   indexed_at=_now(),
                   error_message=None,
                   indexed_chunks=progress)
        logger.info("Item %d indexerad klart: %d/%d chunks → %s",
                     item_id, progress, len(chunks), col)
        return "indexed"

    logger.info("Item %d delvis indexerad: %d/%d chunks (fortsätter nästa körning) → %s",
                 item_id, progress, len(chunks), col)
    return "partial"


# ---------------------------------------------------------------------------
# Batchkörning
# ---------------------------------------------------------------------------

def run_indexer(conn, domain: Optional[str] = None, max_items: int = 20) -> dict:
    """
    Indexerar alla transcribed/captioned/uap_classified-objekt. Returnerar räknare.

    Objekt som kraschar (t.ex. Ollama-timeout, trasig transkript) markeras 'crashed'
    med felmeddelande och hoppas över i framtida körningar -- de blockerar inte
    resten av kön. 'partial' betyder att objektet är en lång post som fortsätter
    från sin chunk-offset nästa körning.
    """
    query = """
        SELECT id FROM vigil_items
        WHERE state IN ('transcribed', 'captioned', 'uap_classified')
          {}
        ORDER BY priority_score DESC
        LIMIT ?
    """.format("AND domain = ?" if domain else "")

    params = (domain, max_items) if domain else (max_items,)
    rows   = conn.execute(query, params).fetchall()

    counts = {"indexed": 0, "partial": 0, "crashed": 0, "skipped": 0, "failed": 0}
    for row in rows:
        item_id = row["id"]
        try:
            status = index_item(conn, item_id)
            counts[status] = counts.get(status, 0) + 1
            if status == "skipped":
                counts["failed"] += 1
        except Exception as exc:
            logger.exception("Item %d kraschade under indexering", item_id)
            transition(conn, item_id, "crashed", error_message=str(exc)[:2000])
            counts["crashed"] += 1
            counts["failed"] += 1

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
        try:
            status = index_item(conn, args.item)
            labels = {"indexed": "✓ Indexerad", "partial": "… Delvis (fortsätter nästa körning)", "skipped": "✗ Överhoppad"}
            print(labels.get(status, status))
        except Exception as exc:
            transition(conn, args.item, "crashed", error_message=str(exc)[:2000])
            print(f"✗ Kraschade: {exc}")

    elif args.run:
        counts = run_indexer(conn, domain=args.domain, max_items=args.max)
        print(f"\n✓ Indexering: {counts['indexed']} klara, {counts['partial']} delvis (fortsätter), "
              f"{counts['crashed']} kraschade, {counts['skipped']} överhoppade")

    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    _main()
