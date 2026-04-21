"""
ingest_html.py — HTML-ingestion för clio-rag

Indexerar en mapp med HTML-filer (t.ex. nedladdad webbplats) i Qdrant.
Extraherar titel, URL (från meta/canonical), och brödtext via html.parser.
Chunkar text ~500 ord med 20% överlapp, precis som ingest.py.

Användning:
    python3 ingest_html.py --folder /sökväg/till/html --collection ssf_skidor_com
    python3 ingest_html.py --folder /mnt/dropbox-disk/mediaarkiv/skrapade_webbar/skidor/www.skidor.com --collection ssf_skidor_com

Kräver: qdrant-client, openai (för embeddings), python-dotenv
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import uuid
from html.parser import HTMLParser
from pathlib import Path

from dotenv import load_dotenv

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

sys.path.insert(0, str(_here))
from config import get_qdrant_client, EMBEDDING_MODEL, EMBEDDING_DIM
from qdrant_client.models import Distance, VectorParams, PointStruct

import openai

_client_openai = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── HTML-parser ───────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Enkel HTML-till-text. Hoppar över script/style/nav/footer."""
    SKIP_TAGS = {"script", "style", "nav", "footer", "head", "noscript", "iframe"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self._parts: list[str] = []
        self.title: str = ""
        self.canonical_url: str = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "link":
            d = dict(attrs)
            if d.get("rel") == "canonical":
                self.canonical_url = d.get("href", "")
        if tag == "meta":
            d = dict(attrs)
            if d.get("property") == "og:url":
                self.canonical_url = self.canonical_url or d.get("content", "")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        if tag == "title":
            self._in_title = False
        if tag in ("p", "h1", "h2", "h3", "h4", "li", "td", "th", "div"):
            self._parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped + " ")

    @property
    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        raw = re.sub(r" {2,}", " ", raw)
        return raw.strip()


def extract_html(path: Path) -> tuple[str, str, str]:
    """Returnerar (title, url, text) från en HTML-fil."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "", "", ""
    parser = _TextExtractor()
    parser.feed(content)
    return parser.title.strip(), parser.canonical_url.strip(), parser.text


# ── Chunkning ─────────────────────────────────────────────────────────────────

def _chunk_text(text: str, max_words: int = 500, overlap: int = 50) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    step = max_words - overlap
    for i in range(0, len(words), step):
        chunk = " ".join(words[i:i + max_words])
        if chunk.strip():
            chunks.append(chunk)
        if i + max_words >= len(words):
            break
    return chunks


# ── Embeddings ────────────────────────────────────────────────────────────────

def _embed_batch(texts: list[str]) -> list[list[float]]:
    resp = _client_openai.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in resp.data]


# ── Collection ────────────────────────────────────────────────────────────────

def ensure_collection(collection: str) -> None:
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        print(f"[ingest_html] Skapade collection: {collection}")
    else:
        print(f"[ingest_html] Collection finns: {collection}")


# ── Ingest ────────────────────────────────────────────────────────────────────

def ingest_folder(folder: Path, collection: str, force: bool = False,
                  min_words: int = 50) -> None:
    ensure_collection(collection)
    client = get_qdrant_client()

    html_files = sorted(folder.rglob("*.html"))
    print(f"[ingest_html] Hittade {len(html_files)} HTML-filer i {folder}")

    batch_points: list[PointStruct] = []
    batch_texts: list[str] = []
    processed = 0
    skipped = 0
    total_chunks = 0
    BATCH_SIZE = 50

    def flush_batch():
        nonlocal total_chunks
        if not batch_texts:
            return
        vectors = _embed_batch(batch_texts)
        for point, vec in zip(batch_points, vectors):
            point.vector = vec
        client.upsert(collection_name=collection, points=batch_points)
        total_chunks += len(batch_points)
        batch_points.clear()
        batch_texts.clear()

    for html_path in html_files:
        title, url, text = extract_html(html_path)
        words = text.split()

        if len(words) < min_words:
            skipped += 1
            continue

        chunks = _chunk_text(text)
        if not chunks:
            skipped += 1
            continue

        source_id = hashlib.md5(str(html_path).encode()).hexdigest()

        for ci, chunk in enumerate(chunks):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_id}:{ci}"))
            payload = {
                "title": title or html_path.stem,
                "url": url or "",
                "source_file": str(html_path.name),
                "source_id": source_id,
                "chunk_index": ci,
                "chunk_total": len(chunks),
                "content_type": "web_html",
                "language": "sv",
            }
            batch_points.append(PointStruct(id=point_id, vector=[], payload=payload))
            batch_texts.append(chunk)

            if len(batch_texts) >= BATCH_SIZE:
                flush_batch()

        processed += 1
        if processed % 200 == 0:
            print(f"[ingest_html] {processed}/{len(html_files)} filer | {total_chunks} chunks...")

    flush_batch()
    print(f"\n[ingest_html] Klar: {processed} filer | {skipped} hoppades over | {total_chunks} chunks -> {collection}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Indexera HTML-filer i Qdrant")
    parser.add_argument("--folder", required=True, help="Rotmapp med HTML-filer")
    parser.add_argument("--collection", default="ssf_skidor_com",
                        help="Qdrant collection-namn (default: ssf_skidor_com)")
    parser.add_argument("--force", action="store_true", help="Tvinga om-indexering")
    parser.add_argument("--min-words", type=int, default=50,
                        help="Min ord per sida for att indexera (default: 50)")
    args = parser.parse_args()

    ingest_folder(
        folder=Path(args.folder),
        collection=args.collection,
        force=args.force,
        min_words=args.min_words,
    )
