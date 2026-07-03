"""
ingest_forensic.py — Ingestion för forensisk RAG-coach (clio_forensic).

Hämtar offentliga lagtexter och riktlinjer via HTTP, chunkar och indexerar
dem i Qdrant-collection clio_forensic.

Körning:
  python ingest_forensic.py --all              # alla fördefinierade källor
  python ingest_forensic.py --source fb        # enskild källa
  python ingest_forensic.py --docx PATH TITLE  # lokal DOCX-fil
  python ingest_forensic.py --list             # lista tillgängliga källor
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
)

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

import config
from config import EMBEDDING_MODEL, EMBEDDING_DIM, SCHEMA_VERSION, get_qdrant_client
from schema.core import (
    AccessOrigin, BookExt, ContentType, CopyrightStatus,
    CorePayload, FullPayload, LocationPayload, Sensitivity, StorageTier,
)

# ---------------------------------------------------------------------------
# Konstanter
# ---------------------------------------------------------------------------

FORENSIC_COLLECTION = "clio_forensic"
MODEL_SONNET        = "claude-sonnet-4-6"
CHUNK_MAX_WORDS     = 500
CHUNK_OVERLAP       = 100
HEADERS             = {"User-Agent": "clio-rag/1.0 (AIAB; jessica@leijer.se)"}

_GRN = "\033[92m"
_YEL = "\033[93m"
_GRY = "\033[90m"
_RED = "\033[91m"
_NRM = "\033[0m"

# ---------------------------------------------------------------------------
# Fördefinierade forensiska källor
# ---------------------------------------------------------------------------

FORENSIC_SOURCES: dict[str, dict] = {
    "fb": {
        "title":         "Föräldrabalken (1949:381) kap 6 — Barnets bästa, vårdnad, umgänge",
        "url":           "https://lagen.nu/1949:381",
        "chapter_hint":  "6",   # extrahera bara kap 6
        "access_origin": "public_domain",
        "sensitivity":   "internal",
        "shareable":     False,
        "tags":          ["lagtext", "vårdnad", "barnets bästa", "FB"],
    },
    "rb": {
        "title":         "Rättegångsbalk (1942:740) kap 40 — Sakkunniga vittnen",
        "url":           "https://lagen.nu/1942:740",
        "chapter_hint":  "40",
        "access_origin": "public_domain",
        "sensitivity":   "internal",
        "shareable":     False,
        "tags":          ["lagtext", "sakkunnig", "vittne", "RB"],
    },
    "barnkonventionen": {
        "title":         "Barnkonventionen som svensk lag (SFS 2018:1197)",
        "url":           "https://lagen.nu/2018:1197",
        "chapter_hint":  None,
        "access_origin": "public_domain",
        "sensitivity":   "internal",
        "shareable":     False,
        "tags":          ["lagtext", "barnkonventionen", "barnrätt"],
    },
    "sol": {
        "title":         "Socialtjänstlagen (2001:453) — Barn och unga, anmälningsplikt",
        "url":           "https://lagen.nu/2001:453",
        "chapter_hint":  None,
        "access_origin": "public_domain",
        "sensitivity":   "internal",
        "shareable":     False,
        "tags":          ["lagtext", "socialtjänst", "anmälningsplikt", "barn"],
    },
    "psl": {
        "title":         "Patientsäkerhetslagen (2010:659) — Psykologers yrkesansvar",
        "url":           "https://lagen.nu/2010:659",
        "chapter_hint":  None,
        "access_origin": "public_domain",
        "sensitivity":   "internal",
        "shareable":     False,
        "tags":          ["lagtext", "patientsäkerhet", "psykolog", "yrkesansvar"],
    },
    "etik": {
        "title":         "Psykologförbundets yrkesetiska principer — Sakkunniguppdrag och barn",
        "url":           "https://www.psykologforbundet.se/yrkesetik/yrkesetiska-principer/",
        "chapter_hint":  None,
        "access_origin": "public_domain",
        "sensitivity":   "internal",
        "shareable":     False,
        "tags":          ["yrkesetik", "psykolog", "sakkunnig"],
    },
}

# ---------------------------------------------------------------------------
# Collection-hantering
# ---------------------------------------------------------------------------

def ensure_collection(client: QdrantClient) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if FORENSIC_COLLECTION not in existing:
        client.create_collection(
            collection_name=FORENSIC_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        print(f"{_GRN}[ingest] Skapade collection: {FORENSIC_COLLECTION}{_NRM}")
    else:
        print(f"{_GRY}[ingest] Collection finns redan: {FORENSIC_COLLECTION}{_NRM}")


# ---------------------------------------------------------------------------
# Textextraktion
# ---------------------------------------------------------------------------

def fetch_html_text(url: str, chapter_hint: str | None = None) -> str:
    """Hämtar URL och extraherar ren text via BeautifulSoup."""
    print(f"[ingest] Hämtar {url} …")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"{_RED}[ingest] FEL vid hämtning: {e}{_NRM}")
        return ""

    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # Ta bort navigation, skript, stilar
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    if chapter_hint:
        # Försök extrahera enbart relevant kapitel
        lines = text.splitlines()
        in_chapter = False
        extracted: list[str] = []
        for line in lines:
            stripped = line.strip()
            # Kapitel-start-mönster: "6 kap." eller "Kap. 6" eller "Kapitel 6"
            if (f"{chapter_hint} kap" in stripped.lower()
                    or stripped.lower().startswith(f"kap. {chapter_hint}")
                    or stripped.lower().startswith(f"kapitel {chapter_hint}")):
                in_chapter = True
            elif in_chapter:
                # Sluta vid nästa kapitel
                import re
                if re.match(r"^\d+ kap\.?$", stripped, re.IGNORECASE):
                    next_chap = re.match(r"^(\d+)", stripped)
                    if next_chap and int(next_chap.group(1)) != int(chapter_hint):
                        break
            if in_chapter:
                extracted.append(line)
        if extracted:
            text = "\n".join(extracted)
            print(f"{_GRY}[ingest] Extraherade kap {chapter_hint} ({len(text)} tecken){_NRM}")

    return text


def extract_docx_text(path: Path) -> str:
    """Extraherar text från DOCX med python-docx."""
    try:
        import docx as _docx
        doc = _docx.Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception as e:
        print(f"{_RED}[ingest] FEL vid DOCX-läsning: {e}{_NRM}")
        return ""


def extract_pdf_text(path: Path) -> str:
    """Extraherar text från PDF med PyMuPDF."""
    try:
        import pymupdf
        doc = pymupdf.open(str(path))
        pages = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                pages.append(text)
        doc.close()
        return "\n\n".join(pages)
    except Exception as e:
        print(f"{_RED}[ingest] FEL vid PDF-läsning: {e}{_NRM}")
        return ""


# ---------------------------------------------------------------------------
# Chunkning
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    max_words: int = CHUNK_MAX_WORDS,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Glidande fönster-chunkning på ordnivå."""
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    step = max(1, max_words - overlap)
    i = 0
    while i < len(words):
        chunk = " ".join(words[i: i + max_words])
        if chunk.strip():
            chunks.append(chunk)
        i += step
    return chunks


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_id_for(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"forensic:{key}"))


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def get_existing_hashes(client: QdrantClient, source_id: str) -> dict[int, str]:
    existing: dict[int, str] = {}
    offset = None
    filt = Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])
    while True:
        result, next_offset = client.scroll(
            collection_name=FORENSIC_COLLECTION,
            scroll_filter=filt,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in result:
            idx = point.payload.get("chunk_index", -1)
            h   = point.payload.get("source_hash", "")
            existing[idx] = h
        if next_offset is None:
            break
        offset = next_offset
    return existing


def delete_source(client: QdrantClient, source_id: str) -> None:
    filt = Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])
    client.delete(collection_name=FORENSIC_COLLECTION, points_selector=filt)


def ingest_text(
    key: str,
    text: str,
    meta: dict,
    force: bool = False,
) -> int:
    """Chunkar, embedar och indexerar text. Returnerar antal nya chunks."""
    if not text.strip():
        print(f"{_YEL}[ingest] {key}: ingen text — hoppar över{_NRM}")
        return 0

    chunks = chunk_text(text)
    total  = len(chunks)
    print(f"[ingest] {key}: {total} chunks")

    qdrant    = get_qdrant_client()
    openai    = OpenAI()
    source_id = source_id_for(key)

    existing_hashes = {} if force else get_existing_hashes(qdrant, source_id)
    if force and existing_hashes:
        print(f"[ingest] --force: raderar befintliga chunks …")
        delete_source(qdrant, source_id)
        existing_hashes = {}

    sensitivity = Sensitivity(meta.get("sensitivity", "internal"))
    access_org  = AccessOrigin(meta.get("access_origin", "public_domain"))
    copyright   = (CopyrightStatus.PUBLIC_DOMAIN
                   if access_org == AccessOrigin.PUBLIC_DOMAIN
                   else CopyrightStatus.LICENSED)

    new_count = 0
    points: list[PointStruct] = []

    for idx, chunk_text_str in enumerate(chunks):
        h = sha256(chunk_text_str)
        if idx in existing_hashes and existing_hashes[idx] == h:
            continue  # oförändrad

        resp   = openai.embeddings.create(input=[chunk_text_str], model=EMBEDDING_MODEL)
        vector = resp.data[0].embedding

        core = CorePayload(
            id              = str(uuid.uuid4()),
            title           = meta["title"],
            summary         = chunk_text_str[:1200].strip(),
            content_type    = ContentType.BOOK,
            language        = "sv",
            tags            = meta.get("tags", []),
            quality_score   = 1.0,
            sensitivity     = sensitivity,
            source_id       = source_id,
            chunk_index     = idx,
            chunk_total     = total,
            source_hash     = h,
            embedding_model = f"{EMBEDDING_MODEL}:{EMBEDDING_DIM}",
            schema_version  = SCHEMA_VERSION,
            indexed_at      = datetime.now(timezone.utc).isoformat(),
        )
        location = LocationPayload(
            storage_tier    = StorageTier.LOCAL,
            local_available = False,
        )
        ext = BookExt(
            author           = meta.get("author", "AIAB / Offentlig källa"),
            year             = meta.get("year", datetime.now().year),
            copyright_status = copyright,
            access_origin    = access_org,
            shareable        = meta.get("shareable", False),
        )
        payload = FullPayload(core=core, location=location, ext=ext)

        points.append(PointStruct(
            id      = core.id,
            vector  = vector,
            payload = payload.to_dict(),
        ))
        new_count += 1

        if len(points) >= 50:
            qdrant.upsert(collection_name=FORENSIC_COLLECTION, points=points)
            print(f"[ingest]   upsert {new_count}/{total} …")
            points = []

    if points:
        qdrant.upsert(collection_name=FORENSIC_COLLECTION, points=points)

    print(f"{_GRN}[ingest] {key}: {new_count} nya chunks indexerade{_NRM}")
    return new_count


def ingest_source(key: str, force: bool = False) -> int:
    """Hämtar och indexerar en fördefinierad källa."""
    if key not in FORENSIC_SOURCES:
        print(f"{_RED}[ingest] Okänd källa: {key}{_NRM}")
        return 0
    meta = FORENSIC_SOURCES[key]
    text = fetch_html_text(meta["url"], chapter_hint=meta.get("chapter_hint"))
    return ingest_text(key, text, meta, force=force)


def ingest_docx(path: Path, title: str, sensitivity: str = "confidential", force: bool = False) -> int:
    """Indexerar en lokal DOCX-fil."""
    text = extract_docx_text(path)
    key  = path.stem.lower().replace(" ", "_")[:40]
    meta = {
        "title":         title,
        "author":        "Jessica Leijer / Fredrik Arvas",
        "year":          datetime.now().year,
        "access_origin": "self_created",
        "sensitivity":   sensitivity,
        "shareable":     False,
        "tags":          ["artefakt", "jessica1", "sakkunnig"],
    }
    return ingest_text(key, text, meta, force=force)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Forensisk RAG-ingestion (clio_forensic)")
    parser.add_argument("--all",    action="store_true", help="Indexera alla fördefinierade källor")
    parser.add_argument("--source", help="Indexera en källa (se --list)")
    parser.add_argument("--docx",   type=Path, metavar="PATH", help="Lokal DOCX-fil att indexera")
    parser.add_argument("--pdf",    type=Path, metavar="PATH", help="Lokal PDF-fil att indexera")
    parser.add_argument("--title",  help="Titel för --docx / --pdf")
    parser.add_argument("--sensitivity", default="confidential",
                        choices=["public", "internal", "confidential"],
                        help="Sensitivity för --docx (default: confidential)")
    parser.add_argument("--force",  action="store_true", help="Tvinga om-indexering")
    parser.add_argument("--list",   action="store_true", help="Lista tillgängliga källor")
    args = parser.parse_args()

    if args.list:
        print("\nTillgängliga forensiska källor:")
        for k, v in FORENSIC_SOURCES.items():
            print(f"  {_YEL}{k:<20}{_NRM} {v['title']}")
        return

    qdrant = get_qdrant_client()
    ensure_collection(qdrant)
    total = 0

    if args.all:
        for key in FORENSIC_SOURCES:
            total += ingest_source(key, force=args.force)

    elif args.source:
        total += ingest_source(args.source, force=args.force)

    elif args.docx:
        if not args.docx.exists():
            print(f"{_RED}FEL: filen finns inte: {args.docx}{_NRM}")
            sys.exit(1)
        title = args.title or args.docx.stem
        total += ingest_docx(args.docx, title, args.sensitivity, force=args.force)

    elif args.pdf:
        if not args.pdf.exists():
            print(f"{_RED}FEL: filen finns inte: {args.pdf}{_NRM}")
            sys.exit(1)
        title = args.title or args.pdf.stem
        text  = extract_pdf_text(args.pdf)
        key   = args.pdf.stem.lower().replace(" ", "_")[:40]
        meta  = {
            "title":         title,
            "author":        "Psykologförbundet / AIAB",
            "year":          datetime.now().year,
            "access_origin": "public_domain",
            "sensitivity":   args.sensitivity,
            "shareable":     False,
            "tags":          ["yrkesetik", "psykolog"],
        }
        total += ingest_text(key, text, meta, force=args.force)

    else:
        parser.print_help()
        sys.exit(0)

    print(f"\n{_GRN}✓ Klart — {total} chunks totalt indexerade i {FORENSIC_COLLECTION}{_NRM}")


if __name__ == "__main__":
    main()
