"""
ingest_html.py — HTML-ingestion för clio-rag

Indexerar en mapp med HTML-filer (t.ex. nedladdad webbplats) i Qdrant.
Extraherar titel, URL (från meta/canonical), och brödtext via html.parser.
Chunkar text ~500 ord med 20% överlapp, precis som ingest.py.

Användning:
    # Simulera (visa vad som skulle indexeras, inget skrivs):
    python3 ingest_html.py --folder /path/to/html --simulate

    # Indexera med URL-filter (standard):
    python3 ingest_html.py --folder /path/to/html --collection ssf_skidor_com

    # Indexera ALLT (ej rekommenderat):
    python3 ingest_html.py --folder /path/to/html --collection ssf_skidor_com --no-filter

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

# ── URL-filter: sektioner som är relevanta för IAF-analys ────────────────────
# Matchar mot canonical URL. Lägg till mönster efter behov.

RELEVANT_URL_PATTERNS: list[str] = [
    "/om-forbundet/",
    "/om-forbundet",
    "/vara-idrotter/",
    "/vara-idrotter",
    "/utbildning/",
    "/utbildning",
    "/strategi",
    "/historia",
    "/samarbetspartners",
    "/forbundsstamma",
    "/idrott-och-halsa",
    "/antidoping",
    "/miljo",
    "/hallbarhet",
    "/policy",
    "/stadgar",
    "/vision",
]

# Sidor som matchar ovan men ändå ska uteslutas (brus/paginering/dubletter)
EXCLUDE_URL_PATTERNS: list[str] = [
    "hitta-forening",
    "hitta-klubb",
    "/styrelse",        # distrikts-styrelser, inte förbundsstyrelsen
    "/kansli",          # distrikts-kansli
    "/kontakta-oss-",   # distriktssidor
    "/om-distriktet/",
    "/kontakt/",
]


def url_is_relevant(url: str) -> bool:
    """Returnerar True om URL matchar relevant sektion och inte är exkluderad."""
    if not url:
        return False
    url_lower = url.lower()
    if any(exc in url_lower for exc in EXCLUDE_URL_PATTERNS):
        return False
    return any(pat in url_lower for pat in RELEVANT_URL_PATTERNS)


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
    import openai
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in resp.data]


# ── Collection ────────────────────────────────────────────────────────────────

def ensure_collection(collection: str) -> None:
    from config import get_qdrant_client, EMBEDDING_DIM
    from qdrant_client.models import Distance, VectorParams
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


# ── Simulering ────────────────────────────────────────────────────────────────

def simulate(folder: Path, min_words: int = 50, use_filter: bool = True) -> None:
    """Visar vad som SKULLE indexeras utan att skriva något till Qdrant."""
    html_files = sorted(folder.rglob("*.html"))
    print(f"\n[SIMULERING] {len(html_files)} HTML-filer totalt i {folder}\n")

    matched: list[tuple[str, str, int]] = []   # (title, url, word_count)
    no_url: list[str] = []
    filtered_out: int = 0
    too_short: int = 0
    total_chunks_est: int = 0

    for path in html_files:
        title, url, text = extract_html(path)
        words = text.split()

        if len(words) < min_words:
            too_short += 1
            continue

        if use_filter:
            if not url:
                no_url.append(path.name)
                continue
            if not url_is_relevant(url):
                filtered_out += 1
                continue

        chunks = _chunk_text(text)
        total_chunks_est += len(chunks)
        matched.append((title or path.stem, url, len(words)))

    print(f"{'Fil':50s} {'Ord':>6s}  URL")
    print("-" * 100)
    for title, url, wc in sorted(matched, key=lambda x: x[1]):
        short_url = url.replace("https://www.skidor.com", "") if url else "(ingen URL)"
        print(f"  {title[:48]:48s} {wc:>6d}  {short_url}")

    print(f"\n{'─'*100}")
    print(f"  Matchade sidor:          {len(matched):>5d}")
    print(f"  Filtrerade bort:         {filtered_out:>5d}  (ej relevanta URL-mönster)")
    print(f"  Saknar canonical URL:    {len(no_url):>5d}")
    print(f"  För korta (< {min_words} ord):  {too_short:>5d}")
    print(f"  Uppskattade chunks:      {total_chunks_est:>5d}  (~{total_chunks_est * 0.0001:.2f} USD embedding-kostnad)")
    print(f"\n  URL-filter aktivt: {use_filter}")
    if use_filter:
        print(f"  Mönster: {', '.join(RELEVANT_URL_PATTERNS[:6])} ...")


# ── Ingest ────────────────────────────────────────────────────────────────────

def ingest_folder(folder: Path, collection: str, force: bool = False,
                  min_words: int = 50, use_filter: bool = True) -> None:
    from config import get_qdrant_client, EMBEDDING_MODEL
    from qdrant_client.models import PointStruct

    ensure_collection(collection)
    client = get_qdrant_client()

    html_files = sorted(folder.rglob("*.html"))
    print(f"[ingest_html] {len(html_files)} HTML-filer | filter: {use_filter} | collection: {collection}")

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

        if use_filter and not url_is_relevant(url):
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
        if processed % 100 == 0:
            print(f"[ingest_html] {processed} filer | {total_chunks} chunks...")

    flush_batch()
    print(f"\n[ingest_html] Klar: {processed} filer | {skipped} hoppades over | {total_chunks} chunks -> {collection}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Indexera HTML-filer i Qdrant")
    parser.add_argument("--folder", required=True, help="Rotmapp med HTML-filer")
    parser.add_argument("--collection", default="ssf_skidor_com",
                        help="Qdrant collection-namn (default: ssf_skidor_com)")
    parser.add_argument("--simulate", action="store_true",
                        help="Simulera: visa vad som skulle indexeras, skriv inget")
    parser.add_argument("--no-filter", action="store_true",
                        help="Indexera ALLA sidor (ej rekommenderat)")
    parser.add_argument("--force", action="store_true", help="Tvinga om-indexering")
    parser.add_argument("--min-words", type=int, default=50,
                        help="Min ord per sida (default: 50)")
    args = parser.parse_args()

    use_filter = not args.no_filter

    if args.simulate:
        simulate(
            folder=Path(args.folder),
            min_words=args.min_words,
            use_filter=use_filter,
        )
    else:
        sys.path.insert(0, str(_here))
        from config import EMBEDDING_MODEL
        ingest_folder(
            folder=Path(args.folder),
            collection=args.collection,
            force=args.force,
            min_words=args.min_words,
            use_filter=use_filter,
        )
