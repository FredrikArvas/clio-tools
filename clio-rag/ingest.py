"""
Ingestion-pipeline för clio-rag MVP (ADD v1.0 §5).

Steg:
  1. Docling konverterar PDF → strukturerad text med sidnummer
  2. HybridChunker delar texten i semantiska chunks (~500 ord, 20% överlapp)
  3. SHA-256 beräknas på chunktexten (source_hash)
  4. Omindexeringskontroll: skippa oförändrade chunks
  5. OpenAI text-embedding-3-small genererar vektor per chunk
  6. Vektor + payload upsert:as i Qdrant collection clio_books
  7. Loggutskrift

Körning:
  python ingest.py                          # alla böcker i CORPUS_PATH
  python ingest.py --pdf path/to/book.pdf   # enskild bok
  python ingest.py --force                  # tvinga om-indexering
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct

import config
from config import (
    COLLECTION_NAME, EMBEDDING_MODEL, SCHEMA_VERSION,
    BOOK_METADATA, get_qdrant_client, is_local_available,
)
from schema.core import (
    AccessOrigin, BookExt, ContentType, CopyrightStatus,
    CorePayload, FullPayload, LocationPayload, Sensitivity, StorageTier,
)

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

# Lokal metadata-cache — kompletterar BOOK_METADATA för okända filer
_META_CACHE_PATH = _here / "metadata.json"

_GRN = "\033[92m"
_YEL = "\033[93m"
_GRY = "\033[90m"
_NRM = "\033[0m"


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _load_meta_cache() -> dict:
    if _META_CACHE_PATH.exists():
        return json.loads(_META_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_meta_cache(cache: dict) -> None:
    _META_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _ask_rights(filename: str) -> dict:
    """
    Interaktiv rättighetsdeklaration för okänd fil.
    Sparar svaret i metadata.json för framtida körningar.
    """
    cache = _load_meta_cache()
    key   = filename.lower()
    if key in cache:
        print(f"{_GRY}[meta] {filename} — använder sparad metadata{_NRM}")
        return cache[key]

    print(f"\n{_YEL}━━━  Rättighetsdeklaration  ━━━{_NRM}")
    print(f"  Fil: {filename}\n")

    title  = input("  Titel (Enter = filnamn): ").strip() or Path(filename).stem
    author = input("  Upphovsman: ").strip() or "Okänd"
    year_s = input("  Utgivningsår (Enter = okänt): ").strip()
    year   = int(year_s) if year_s.isdigit() else datetime.now().year

    print(f"\n  Vem äger upphovsrätten?")
    print(f"  {_YEL}1{_NRM}  Jag / AIAB  (self_created)")
    print(f"  {_YEL}2{_NRM}  Köpt        (purchased)")
    print(f"  {_YEL}3{_NRM}  Lånad       (borrowed)")
    print(f"  {_YEL}4{_NRM}  Public domain")

    origin_map = {
        "1": ("self_created",   "licensed"),
        "2": ("purchased",      "personal_use"),
        "3": ("borrowed",       "personal_use"),
        "4": ("public_domain",  "public_domain"),
    }
    while True:
        val = input("  Välj [1-4]: ").strip()
        if val in origin_map:
            access_origin, copyright_status = origin_map[val]
            break
        print("  Ogiltigt val — försök igen.")

    shareable = False
    if access_origin == "self_created":
        s = input("\n  Dela externt (shareable)? [j/N]: ").strip().lower()
        shareable = s in ("j", "y", "ja", "yes")

    meta = {
        "title":            title,
        "author":           author,
        "year":             year,
        "publisher":        None,
        "copyright_status": copyright_status,
        "access_origin":    access_origin,
        "shareable":        shareable,
    }

    cache[key] = meta
    _save_meta_cache(cache)
    print(f"\n{_GRN}  ✓ Sparat i metadata.json{_NRM}")
    return meta


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def source_id_for_path(path: Path) -> str:
    """Deterministiskt UUID v5 baserat på filens absoluta sökväg."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, path.resolve().as_posix()))


def get_existing_hashes(client, source_id: str) -> dict[int, str]:
    """Hämtar {chunk_index: source_hash} för alla befintliga punkter med source_id."""
    existing: dict[int, str] = {}
    offset = None
    filt = Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])
    while True:
        result, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=filt,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in result:
            idx  = point.payload.get("chunk_index", -1)
            h    = point.payload.get("source_hash", "")
            existing[idx] = h
        if next_offset is None:
            break
        offset = next_offset
    return existing


def delete_all_chunks(client, source_id: str) -> int:
    """Tar bort alla punkter för ett source_id. Returnerar antal borttagna."""
    filt = Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])
    result = client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=filt,
    )
    return getattr(result, "operation_id", 0)


def extract_page_range(chunk) -> tuple[int, int]:
    """Extraherar page_start och page_end från ett Docling-chunk."""
    pages: list[int] = []
    try:
        for item in chunk.meta.doc_items:
            for prov in item.prov:
                if hasattr(prov, "page_no"):
                    pages.append(prov.page_no)
    except AttributeError:
        pass
    if not pages:
        return 0, 0
    return min(pages), max(pages)


def build_summary(text: str, max_chars: int = 1200) -> str:
    """Trunkera chunk-text till summary-fältet (200–400 ord ≈ ~1 200 tecken)."""
    return text[:max_chars].strip()


# ---------------------------------------------------------------------------
# Huvud-pipeline
# ---------------------------------------------------------------------------

def _extract_pages_pymupdf(pdf_path: Path) -> list[tuple[int, str]]:
    """
    Extraherar text per sida med PyMuPDF.
    Returnerar lista av (page_no, text) där page_no är 1-baserat.
    """
    import pymupdf
    doc = pymupdf.open(str(pdf_path))
    pages = []
    for i, page in enumerate(doc, 1):
        text = page.get_text("text")
        if text.strip():
            pages.append((i, text))
    doc.close()
    return pages


def _chunk_pages(pages: list[tuple[int, str]], max_words: int = 500, overlap: int = 50) -> list[tuple[int, int, str]]:
    """
    Glidande fönster-chunkning på sidnivå (~500 ord, ~20% överlapp).
    Returnerar lista av (page_start, page_end, text).
    """
    # Bygg ordlista med sidmarkeringar
    all_words: list[tuple[int, str]] = []  # (page_no, word)
    for page_no, text in pages:
        for word in text.split():
            all_words.append((page_no, word))

    if not all_words:
        return []

    chunks: list[tuple[int, int, str]] = []
    step = max_words - overlap
    i = 0
    while i < len(all_words):
        window = all_words[i: i + max_words]
        page_start = window[0][0]
        page_end   = window[-1][0]
        text       = " ".join(w for _, w in window)
        chunks.append((page_start, page_end, text))
        i += step

    return chunks


def ingest_pdf(
    pdf_path: Path,
    meta_override: Optional[dict] = None,
    force: bool = False,
) -> int:
    """
    Indexerar en bok. Returnerar antal nya/uppdaterade chunks.
    meta_override kan användas för att ange metadata direkt (kringgår BOOK_METADATA-lookup).
    """
    print(f"\n[ingest] {pdf_path.name}")

    # --- Metadata ---
    meta = meta_override or BOOK_METADATA.get(pdf_path.name.lower())
    if meta is None:
        # Kolla lokal cache, fråga annars användaren
        meta = _ask_rights(pdf_path.name)

    local_avail   = is_local_available()
    file_checksum = sha256_file(pdf_path)
    source_id     = source_id_for_path(pdf_path)

    # --- Textutläsning med PyMuPDF (lätt, ingen AI) ---
    print("[ingest] Extraherar text med PyMuPDF …")
    pages  = _extract_pages_pymupdf(pdf_path)
    print(f"[ingest] {len(pages)} sidor med text")

    # --- Chunkning ---
    print("[ingest] Chunkar (~500 ord, 20% överlapp) …")
    raw_chunks = _chunk_pages(pages, max_words=500, overlap=100)
    total      = len(raw_chunks)
    print(f"[ingest] {total} chunks")

    # --- Qdrant ---
    qdrant = get_qdrant_client()
    openai = OpenAI()

    existing_hashes = {} if force else get_existing_hashes(qdrant, source_id)

    if force and existing_hashes:
        print("[ingest] --force: raderar befintliga chunks …")
        delete_all_chunks(qdrant, source_id)
        existing_hashes = {}

    new_count = 0
    points: list[PointStruct] = []

    for idx, (page_start, page_end, text) in enumerate(raw_chunks):
        text = text.strip()
        if not text:
            continue

        h = sha256_text(text)

        # Omindexeringskontroll per chunk
        if idx in existing_hashes and existing_hashes[idx] == h:
            continue  # oförändrad — skippa

        # Embedding
        resp   = openai.embeddings.create(input=[text], model=EMBEDDING_MODEL)
        vector = resp.data[0].embedding

        # Payload
        core = CorePayload(
            id              = str(uuid.uuid4()),
            title           = meta["title"],
            summary         = build_summary(text),
            content_type    = ContentType.BOOK,
            language        = "sv",
            tags            = [],
            quality_score   = 1.0,
            sensitivity     = Sensitivity.INTERNAL,
            source_id       = source_id,
            chunk_index     = idx,
            chunk_total     = total,
            source_hash     = h,
            embedding_model = f"{EMBEDDING_MODEL}:{config.EMBEDDING_DIM}",
            schema_version  = SCHEMA_VERSION,
            indexed_at      = datetime.now(timezone.utc).isoformat(),
        )
        location = LocationPayload(
            storage_tier    = StorageTier.LOCAL,
            local_path      = str(pdf_path.resolve()),
            local_available = local_avail,
            file_size_bytes = pdf_path.stat().st_size,
            checksum_sha256 = file_checksum,
        )
        ext = BookExt(
            author           = meta["author"],
            year             = meta["year"],
            publisher        = meta.get("publisher"),
            page_start       = page_start,
            page_end         = page_end,
            copyright_status = CopyrightStatus(meta.get("copyright_status", "licensed")),
            access_origin    = AccessOrigin(meta.get("access_origin", "self_created")),
            shareable        = meta.get("shareable", False),
        )
        payload = FullPayload(core=core, location=location, ext=ext)

        points.append(PointStruct(
            id      = core.id,
            vector  = vector,
            payload = payload.to_dict(),
        ))
        new_count += 1

        # Batch-upsert var 50:e chunk
        if len(points) >= 50:
            qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
            print(f"[ingest]   upsert {new_count}/{total} chunks …")
            points = []

    # Sista batchen
    if points:
        qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

    print(f"[ingest] {pdf_path.name}: {new_count} nya/uppdaterade chunks (av {total} totalt)")
    return new_count


def ingest_corpus(corpus_path: Path, force: bool = False) -> None:
    """Indexerar alla kända böcker i corpus_path."""
    if not corpus_path.exists():
        print(f"[ingest] FEL: corpus-mappen finns inte: {corpus_path}")
        sys.exit(1)

    pdf_files = list(corpus_path.glob("*.pdf"))
    if not pdf_files:
        print(f"[ingest] Inga PDF-filer hittades i {corpus_path}")
        sys.exit(1)

    total_new = 0
    for pdf in sorted(pdf_files):
        total_new += ingest_pdf(pdf, force=force)

    print(f"\n[ingest] Klart — {total_new} chunks totalt indexerade.")


# ---------------------------------------------------------------------------
# Interaktiv filväljare (samma mönster som clio-audio-edit)
# ---------------------------------------------------------------------------

_GRN = "\033[92m"
_YEL = "\033[93m"
_CYN = "\033[96m"
_GRY = "\033[90m"
_BLD = "\033[1m"
_NRM = "\033[0m"
_WIDTH = 60


def _hr() -> None:
    print(f"{_CYN}{'-' * _WIDTH}{_NRM}")


def _section(title: str, lines: list[str]) -> None:
    print()
    _hr()
    print(f"  {_BLD}{title}{_NRM}")
    _hr()
    for line in lines:
        print(f"  {line}")
    _hr()


def _parse_selection(val: str, n: int) -> list[int] | None:
    """
    Tolkar urval som enskilda nummer, intervall och kommaseparerade listor.
    Returnerar lista med 0-baserade index, eller None om ogiltigt.
    Exempel: "3" → [2], "1-3" → [0,1,2], "1,3,5" → [0,2,4], "2-4,6" → [1,2,3,5]
    """
    indices: set[int] = set()
    try:
        for part in val.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                lo, hi = int(a.strip()), int(b.strip())
                if not (1 <= lo <= hi <= n):
                    return None
                indices.update(range(lo - 1, hi))
            else:
                i = int(part)
                if not (1 <= i <= n):
                    return None
                indices.add(i - 1)
    except ValueError:
        return None
    return sorted(indices)


def select_pdf_files(folder: Path) -> list[Path] | None:
    """
    Listar PDF-filer i mappen interaktivt.
    Returnerar lista med valda filer, eller None (Tillbaka).
    Stöd: nummer (3), intervall (1-3), kommalista (1,3,5), A (alla), 0 (tillbaka).
    """
    while True:
        files = sorted(folder.glob("*.pdf"), key=lambda p: p.name.lower())

        if not files:
            print(f"\n  Inga PDF-filer hittades i: {folder}")
            return None

        lines = []
        for i, f in enumerate(files, 1):
            try:
                size_kb = f.stat().st_size // 1024
                size_str = f"{size_kb / 1024:.1f} MB" if size_kb > 1024 else f"{size_kb} KB"
            except OSError:
                size_str = "?"
            name = f.name if len(f.name) <= 55 else f.name[:52] + "…"
            lines.append(f"{_YEL}{i:>2}{_NRM}  {name}  {_GRY}{size_str}{_NRM}")
        lines.append("")
        lines.append(f"{_GRN} A{_NRM}  Alla filer ({len(files)} st)")
        lines.append(f"{_GRY} 0{_NRM}  Tillbaka")

        short = ("…" + str(folder)[-46:]) if len(str(folder)) > 49 else str(folder)
        _section(f"PDF-filer  {_GRY}{short}{_NRM}", lines)
        print(f"  {_GRY}Tips: enskild (3), intervall (1-3), lista (1,3,5), kombination (1-3,5){_NRM}")

        val = input("\n  Välj: ").strip().lower()

        if val == "0":
            return None
        if val == "a":
            print(f"\n  {_GRN}>{_NRM} Alla {len(files)} filer valda.")
            return list(files)

        indices = _parse_selection(val, len(files))
        if indices is None:
            print(f"  {_GRY}Ogiltigt val — försök igen.{_NRM}")
            continue

        chosen = [files[i] for i in indices]
        print(f"\n  {_GRN}>{_NRM} Valde {len(chosen)} fil(er):")
        for f in chosen:
            print(f"    {f.name}")
        return chosen


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="clio-rag ingestion-pipeline")
    parser.add_argument("--pdf",    type=Path, help="Enskild PDF att indexera")
    parser.add_argument("--folder", type=Path, help="Interaktiv filväljare i mappen")
    parser.add_argument("--force",  action="store_true", help="Tvinga om-indexering")
    parser.add_argument("--corpus", type=Path, default=config.CORPUS_PATH,
                        help=f"Corpus-mapp (default: {config.CORPUS_PATH})")
    args = parser.parse_args()

    if args.pdf:
        ingest_pdf(args.pdf.resolve(), force=args.force)

    elif args.folder:
        folder = args.folder.resolve()
        if not folder.exists():
            print(f"[ingest] FEL: mappen finns inte: {folder}")
            sys.exit(1)
        selection = select_pdf_files(folder)
        if not selection:
            print("  Avbrutet.")
            sys.exit(0)
        total_new = 0
        for pdf in selection:
            total_new += ingest_pdf(pdf, force=args.force)
        print(f"\n[ingest] Klart — {total_new} chunks totalt indexerade.")

    else:
        ingest_corpus(args.corpus, force=args.force)


if __name__ == "__main__":
    main()
