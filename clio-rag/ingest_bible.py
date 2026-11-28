"""
ingest_bible.py — indexerar 1917 års svenska bibel i Qdrant (clio_bible).

Flöde:
  1. --fetch  : hämtar bibeltexten från getbible.net API → sparar corpus/bibeln_1917.json
  2. --index  : läser JSON → chunkar 10 verser (3 överlapp) → embeddar → Qdrant
  3. --simulate: visar chunks utan att skriva något

Körning:
  python ingest_bible.py --fetch          # ladda ner källtext (en gång)
  python ingest_bible.py --index          # indexera
  python ingest_bible.py --index --force  # tvinga om-indexering
  python ingest_bible.py --simulate       # visa chunks utan indexering
  python ingest_bible.py --test-fetch     # hämta bara 1 Mos 1 och visa resultat

Källa: getbible.net v2 API (public domain, 1917 års översättning = "swedish")
  https://api.getbible.net/v2/swedish/{book}/{chapter}.json
  Kör --list-translations för att se alla tillgängliga koder om "swedish" ej fungerar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct

import config
from config import (
    BIBLE_COLLECTION_NAME, SCHEMA_VERSION,
    get_qdrant_client, create_bible_collection,
)
from embedder import embed

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

# ---------------------------------------------------------------------------
# Konstanter
# ---------------------------------------------------------------------------

GETBIBLE_BASE    = "https://api.getbible.net/v2"
TRANSLATION_CODE = "swedish"          # 1917 årsöversättningen på getbible.net
SOURCE_JSON      = _here / "corpus" / "bibeln_1917.json"

CHUNK_SIZE    = 10   # verser per chunk
CHUNK_OVERLAP = 3    # överlapp mot föregående chunk
BATCH_SIZE    = 50   # punkter per Qdrant-upsert

_GRN = "\033[92m"
_YEL = "\033[93m"
_GRY = "\033[90m"
_NRM = "\033[0m"

# ---------------------------------------------------------------------------
# Bibelböcker — Svenska namn, testament, kapitelantal
# Kapitelantal: standard protestantisk kanon.
# ---------------------------------------------------------------------------

BIBLE_BOOKS: list[dict] = [
    # Gamla testamentet (GT) — bokindexen på getbible.net är 1-baserade
    {"idx": 1,  "code": "1Mos",  "name": "1 Mosebok",        "testament": "GT", "chapters": 50},
    {"idx": 2,  "code": "2Mos",  "name": "2 Mosebok",        "testament": "GT", "chapters": 40},
    {"idx": 3,  "code": "3Mos",  "name": "3 Mosebok",        "testament": "GT", "chapters": 27},
    {"idx": 4,  "code": "4Mos",  "name": "4 Mosebok",        "testament": "GT", "chapters": 36},
    {"idx": 5,  "code": "5Mos",  "name": "5 Mosebok",        "testament": "GT", "chapters": 34},
    {"idx": 6,  "code": "Jos",   "name": "Josua",             "testament": "GT", "chapters": 24},
    {"idx": 7,  "code": "Dom",   "name": "Domarboken",        "testament": "GT", "chapters": 21},
    {"idx": 8,  "code": "Rut",   "name": "Rut",               "testament": "GT", "chapters": 4},
    {"idx": 9,  "code": "1Sam",  "name": "1 Samuelsboken",   "testament": "GT", "chapters": 31},
    {"idx": 10, "code": "2Sam",  "name": "2 Samuelsboken",   "testament": "GT", "chapters": 24},
    {"idx": 11, "code": "1Kung", "name": "1 Kungaboken",     "testament": "GT", "chapters": 22},
    {"idx": 12, "code": "2Kung", "name": "2 Kungaboken",     "testament": "GT", "chapters": 25},
    {"idx": 13, "code": "1Krön", "name": "1 Krönikeboken",   "testament": "GT", "chapters": 29},
    {"idx": 14, "code": "2Krön", "name": "2 Krönikeboken",   "testament": "GT", "chapters": 36},
    {"idx": 15, "code": "Esra",  "name": "Esra",              "testament": "GT", "chapters": 10},
    {"idx": 16, "code": "Neh",   "name": "Nehemja",           "testament": "GT", "chapters": 13},
    {"idx": 17, "code": "Est",   "name": "Ester",             "testament": "GT", "chapters": 10},
    {"idx": 18, "code": "Job",   "name": "Job",               "testament": "GT", "chapters": 42},
    {"idx": 19, "code": "Ps",    "name": "Psaltaren",         "testament": "GT", "chapters": 150},
    {"idx": 20, "code": "Ords",  "name": "Ordspråksboken",   "testament": "GT", "chapters": 31},
    {"idx": 21, "code": "Pred",  "name": "Predikaren",        "testament": "GT", "chapters": 12},
    {"idx": 22, "code": "Höga",  "name": "Höga Visan",        "testament": "GT", "chapters": 8},
    {"idx": 23, "code": "Jes",   "name": "Jesaja",            "testament": "GT", "chapters": 66},
    {"idx": 24, "code": "Jer",   "name": "Jeremia",           "testament": "GT", "chapters": 52},
    {"idx": 25, "code": "Klag",  "name": "Klagovisorna",      "testament": "GT", "chapters": 5},
    {"idx": 26, "code": "Hes",   "name": "Hesekiel",          "testament": "GT", "chapters": 48},
    {"idx": 27, "code": "Dan",   "name": "Daniel",            "testament": "GT", "chapters": 12},
    {"idx": 28, "code": "Hos",   "name": "Hosea",             "testament": "GT", "chapters": 14},
    {"idx": 29, "code": "Joel",  "name": "Joel",              "testament": "GT", "chapters": 3},
    {"idx": 30, "code": "Amos",  "name": "Amos",              "testament": "GT", "chapters": 9},
    {"idx": 31, "code": "Obad",  "name": "Obadja",            "testament": "GT", "chapters": 1},
    {"idx": 32, "code": "Jona",  "name": "Jona",              "testament": "GT", "chapters": 4},
    {"idx": 33, "code": "Mika",  "name": "Mika",              "testament": "GT", "chapters": 7},
    {"idx": 34, "code": "Nah",   "name": "Nahum",             "testament": "GT", "chapters": 3},
    {"idx": 35, "code": "Hab",   "name": "Habackuk",          "testament": "GT", "chapters": 3},
    {"idx": 36, "code": "Sef",   "name": "Sefanja",           "testament": "GT", "chapters": 3},
    {"idx": 37, "code": "Hag",   "name": "Haggai",            "testament": "GT", "chapters": 2},
    {"idx": 38, "code": "Sak",   "name": "Sakarja",           "testament": "GT", "chapters": 14},
    {"idx": 39, "code": "Mal",   "name": "Malaki",            "testament": "GT", "chapters": 4},
    # Nya testamentet (NT)
    {"idx": 40, "code": "Matt",  "name": "Matteus",           "testament": "NT", "chapters": 28},
    {"idx": 41, "code": "Mark",  "name": "Markus",            "testament": "NT", "chapters": 16},
    {"idx": 42, "code": "Luk",   "name": "Lukas",             "testament": "NT", "chapters": 24},
    {"idx": 43, "code": "Joh",   "name": "Johannes",          "testament": "NT", "chapters": 21},
    {"idx": 44, "code": "Apg",   "name": "Apostlagärningarna","testament": "NT", "chapters": 28},
    {"idx": 45, "code": "Rom",   "name": "Romarbrevet",       "testament": "NT", "chapters": 16},
    {"idx": 46, "code": "1Kor",  "name": "1 Korinthierbrevet","testament": "NT", "chapters": 16},
    {"idx": 47, "code": "2Kor",  "name": "2 Korinthierbrevet","testament": "NT", "chapters": 13},
    {"idx": 48, "code": "Gal",   "name": "Galaterbrevet",     "testament": "NT", "chapters": 6},
    {"idx": 49, "code": "Ef",    "name": "Efesierbrevet",     "testament": "NT", "chapters": 6},
    {"idx": 50, "code": "Fil",   "name": "Filipperbrevet",    "testament": "NT", "chapters": 4},
    {"idx": 51, "code": "Kol",   "name": "Kolosserbrevet",    "testament": "NT", "chapters": 4},
    {"idx": 52, "code": "1Tess", "name": "1 Thessalonikerbrevet", "testament": "NT", "chapters": 5},
    {"idx": 53, "code": "2Tess", "name": "2 Thessalonikerbrevet", "testament": "NT", "chapters": 3},
    {"idx": 54, "code": "1Tim",  "name": "1 Timotheosbrevet", "testament": "NT", "chapters": 6},
    {"idx": 55, "code": "2Tim",  "name": "2 Timotheosbrevet", "testament": "NT", "chapters": 4},
    {"idx": 56, "code": "Tit",   "name": "Titusbrevet",       "testament": "NT", "chapters": 3},
    {"idx": 57, "code": "Filem", "name": "Filemonbrevet",     "testament": "NT", "chapters": 1},
    {"idx": 58, "code": "Heb",   "name": "Hebreerbrevet",     "testament": "NT", "chapters": 13},
    {"idx": 59, "code": "Jak",   "name": "Jakobsbrevet",      "testament": "NT", "chapters": 5},
    {"idx": 60, "code": "1Pet",  "name": "1 Petrusbrevet",    "testament": "NT", "chapters": 5},
    {"idx": 61, "code": "2Pet",  "name": "2 Petrusbrevet",    "testament": "NT", "chapters": 3},
    {"idx": 62, "code": "1Joh",  "name": "1 Johannesbrevet",  "testament": "NT", "chapters": 5},
    {"idx": 63, "code": "2Joh",  "name": "2 Johannesbrevet",  "testament": "NT", "chapters": 1},
    {"idx": 64, "code": "3Joh",  "name": "3 Johannesbrevet",  "testament": "NT", "chapters": 1},
    {"idx": 65, "code": "Jud",   "name": "Judasbrevet",       "testament": "NT", "chapters": 1},
    {"idx": 66, "code": "Upp",   "name": "Uppenbarelseboken", "testament": "NT", "chapters": 22},
]

_BOOK_BY_CODE = {b["code"]: b for b in BIBLE_BOOKS}
_BOOK_BY_IDX  = {b["idx"]:  b for b in BIBLE_BOOKS}

# ---------------------------------------------------------------------------
# Hämtning — getbible.net v2 API
#
# Svar per kapitel (GET /v2/{translation}/{book_number}/{chapter}.json):
# {
#   "book_nr": 1, "chapter": 1, "name": "Genesis", "translation": "swedish",
#   "verses": [{"verse": 1, "text": "I begynnelsen..."}, ...]
# }
# ---------------------------------------------------------------------------

def _fetch_chapter(session, book_idx: int, chapter: int) -> list[dict]:
    """
    Hämtar ett kapitel från getbible.net och returnerar
    lista av {"verse": int, "text": str}.
    """
    import urllib.request
    url = f"{GETBIBLE_BASE}/{TRANSLATION_CODE}/{book_idx}/{chapter}.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "clio-rag/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        verses = data.get("verses", [])
        if not verses:
            print(f"  {_YEL}Varning: inga verser hittades för {book_idx}:{chapter}{_NRM}")
        return [{"verse": v["verse"], "text": v["text"].strip()} for v in verses]
    except Exception as exc:
        print(f"  {_YEL}FEL vid hämtning {book_idx}:{chapter} — {exc}{_NRM}")
        return []


def fetch_all(output_path: Path, delay: float = 0.3) -> int:
    """
    Hämtar hela bibeln kapitel för kapitel och sparar som JSON-lista.
    Returnerar totalt antal verser.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_verses: list[dict] = []
    total_chapters = sum(b["chapters"] for b in BIBLE_BOOKS)
    fetched = 0

    print(f"[fetch] Hämtar 1917 års bibel från getbible.net ({total_chapters} kapitel) …")
    print(f"[fetch] Källa: {GETBIBLE_BASE}/{TRANSLATION_CODE}/")
    print(f"[fetch] Uppskattad tid: ~{int(total_chapters * delay / 60)} min\n")

    for book in BIBLE_BOOKS:
        print(f"  {book['testament']} {book['name']} ({book['chapters']} kap) …", end="", flush=True)
        book_verses = 0
        for chapter in range(1, book["chapters"] + 1):
            verses = _fetch_chapter(None, book["idx"], chapter)
            for v in verses:
                all_verses.append({
                    "book_code":  book["code"],
                    "book_name":  book["name"],
                    "testament":  book["testament"],
                    "book_idx":   book["idx"],
                    "chapter":    chapter,
                    "verse":      v["verse"],
                    "text":       v["text"],
                })
            book_verses += len(verses)
            fetched += 1
            time.sleep(delay)
        print(f" {_GRY}{book_verses} verser{_NRM}")

    output_path.write_text(
        json.dumps(all_verses, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n{_GRN}[fetch] Klart — {len(all_verses)} verser sparade till {output_path}{_NRM}")
    return len(all_verses)


# ---------------------------------------------------------------------------
# Chunkning — glidande fönster per bok
# ---------------------------------------------------------------------------

def _make_chunks(
    verses: list[dict],
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """
    Delar en boks verser i överlappande passagechunkar.
    Varje chunk innehåller chunk_size verser, med overlap verser gemensamma
    med föregående chunk.  Korsar aldrig bokgränser.
    """
    if not verses:
        return []

    chunks: list[dict] = []
    step = max(1, chunk_size - overlap)
    i = 0
    while i < len(verses):
        window = verses[i: i + chunk_size]
        first  = window[0]
        last   = window[-1]
        text   = _build_passage_text(window)
        chunks.append({
            "book_code":     first["book_code"],
            "book_name":     first["book_name"],
            "testament":     first["testament"],
            "book_idx":      first["book_idx"],
            "chapter_start": first["chapter"],
            "verse_start":   first["verse"],
            "chapter_end":   last["chapter"],
            "verse_end":     last["verse"],
            "text":          text,
        })
        i += step
    return chunks


def _build_passage_text(verses: list[dict]) -> str:
    """Bygger läsbar strängt för embedding: rubrik + verstext."""
    first = verses[0]
    last  = verses[-1]
    if first["chapter"] == last["chapter"]:
        ref = f"{first['book_name']} {first['chapter']}:{first['verse']}–{last['verse']}"
    else:
        ref = (f"{first['book_name']} {first['chapter']}:{first['verse']}"
               f"–{last['chapter']}:{last['verse']}")
    lines = [ref, ""]
    for v in verses:
        lines.append(f"{v['chapter']}:{v['verse']} {v['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hjälpfunktioner — Qdrant
# ---------------------------------------------------------------------------

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


BIBLE_SOURCE_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "clio-rag:bibeln:1917:sv"))


def _get_existing_hashes(client) -> dict[str, str]:
    """Returnerar {chunk_key: source_hash} för alla befintliga bibelchunkar."""
    existing: dict[str, str] = {}
    offset = None
    while True:
        result, next_offset = client.scroll(
            collection_name=BIBLE_COLLECTION_NAME,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in result:
            key  = point.payload.get("chunk_key", "")
            h    = point.payload.get("source_hash", "")
            if key:
                existing[key] = h
        if next_offset is None:
            break
        offset = next_offset
    return existing


def _chunk_key(chunk: dict) -> str:
    """Deterministisk nyckel för en passage, använd för om-indexeringskontroll."""
    return (f"{chunk['book_code']}."
            f"{chunk['chapter_start']}:{chunk['verse_start']}-"
            f"{chunk['chapter_end']}:{chunk['verse_end']}")


def _build_payload(chunk: dict, chunk_idx: int, chunk_total: int, source_hash: str) -> dict:
    """Bygger platt Qdrant-payload dict (speglar FullPayload.to_dict()-formatet)."""
    return {
        # core
        "id":              str(uuid.uuid4()),
        "title":           f"Bibeln 1917 — {chunk['book_name']}",
        "summary":         chunk["text"][:1200].strip(),
        "content_type":    "bible",
        "language":        "sv",
        "tags":            [chunk["testament"], chunk["book_code"]],
        "quality_score":   1.0,
        "sensitivity":     "public",
        "source_id":       BIBLE_SOURCE_ID,
        "chunk_index":     chunk_idx,
        "chunk_total":     chunk_total,
        "source_hash":     source_hash,
        "chunk_key":       _chunk_key(chunk),
        "embedding_model": f"{EMBEDDING_MODEL}:{config.EMBEDDING_DIM}",
        "schema_version":  SCHEMA_VERSION,
        "indexed_at":      datetime.now(timezone.utc).isoformat(),
        # location
        "loc_storage_tier":    "cloud",
        "loc_local_available": False,
        # bible-specifika fält (ext_*)
        "ext_testament":     chunk["testament"],
        "ext_book_name":     chunk["book_name"],
        "ext_book_code":     chunk["book_code"],
        "ext_book_idx":      chunk["book_idx"],
        "ext_chapter_start": chunk["chapter_start"],
        "ext_verse_start":   chunk["verse_start"],
        "ext_chapter_end":   chunk["chapter_end"],
        "ext_verse_end":     chunk["verse_end"],
        "ext_copyright_status": "public_domain",
        "ext_access_origin":    "public_domain",
        "ext_shareable":        True,
        "ext_year":             1917,
        "ext_author":           "Svenska Bibelsällskapet",
        "ext_publisher":        "Svenska Bibelsällskapet",
    }


# ---------------------------------------------------------------------------
# Huvud-pipeline
# ---------------------------------------------------------------------------

def ingest_bible(
    source_path: Path,
    force: bool = False,
    simulate: bool = False,
) -> int:
    """
    Indexerar bibeln från JSON-källfilen.
    Returnerar antal nya/uppdaterade chunks.
    """
    if not source_path.exists():
        print(f"[ingest] FEL: källfilen saknas: {source_path}")
        print(f"[ingest] Kör --fetch för att ladda ner bibeltexten.")
        sys.exit(1)

    print(f"[ingest] Läser {source_path.name} …")
    all_verses: list[dict] = json.loads(source_path.read_text(encoding="utf-8-sig"))
    print(f"[ingest] {len(all_verses)} verser laddade")

    # Bygg chunks per bok
    all_chunks: list[dict] = []
    books_seen: dict[str, list] = {}
    for v in all_verses:
        books_seen.setdefault(v["book_code"], []).append(v)
    for book_code in [b["code"] for b in BIBLE_BOOKS]:  # bevara bibelordning
        if book_code in books_seen:
            all_chunks.extend(_make_chunks(books_seen[book_code]))

    chunk_total = len(all_chunks)
    print(f"[ingest] {chunk_total} passagechunkar (fönster {CHUNK_SIZE} verser, överlapp {CHUNK_OVERLAP})")

    if simulate:
        print(f"\n[simulate] Visar de 3 första chunks:\n")
        for chunk in all_chunks[:3]:
            print(f"  {_chunk_key(chunk)}")
            print(f"  {chunk['text'][:300]}")
            print()
        print(f"[simulate] Totalt {chunk_total} chunks — inget indexerades.")
        return 0

    if not simulate:
        create_bible_collection()

    qdrant = get_qdrant_client()

    existing_hashes = {} if force else _get_existing_hashes(qdrant)

    if force and existing_hashes:
        print("[ingest] --force: raderar befintliga bibelchunkar …")
        from qdrant_client.models import FilterSelector
        qdrant.delete(
            collection_name=BIBLE_COLLECTION_NAME,
            points_selector=FilterSelector(
                filter=Filter(must=[
                    FieldCondition(key="source_id", match=MatchValue(value=BIBLE_SOURCE_ID))
                ])
            ),
        )
        existing_hashes = {}

    new_count = 0
    points: list[PointStruct] = []

    for idx, chunk in enumerate(all_chunks):
        text = chunk["text"].strip()
        if not text:
            continue

        h   = sha256_text(text)
        key = _chunk_key(chunk)

        if key in existing_hashes and existing_hashes[key] == h:
            continue

        vector = embed([text])[0]

        payload = _build_payload(chunk, idx, chunk_total, h)
        points.append(PointStruct(
            id=payload["id"],
            vector=vector,
            payload=payload,
        ))
        new_count += 1

        if len(points) >= BATCH_SIZE:
            qdrant.upsert(collection_name=BIBLE_COLLECTION_NAME, points=points)
            print(f"[ingest]   upsert {new_count}/{chunk_total} chunks …")
            points = []

    if points:
        qdrant.upsert(collection_name=BIBLE_COLLECTION_NAME, points=points)

    print(f"\n{_GRN}[ingest] Klart — {new_count} nya/uppdaterade chunks (av {chunk_total} totalt).{_NRM}")
    return new_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="clio-rag: indexerar 1917 års svenska bibel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exempel:
  python ingest_bible.py --fetch          # ladda ner källtext
  python ingest_bible.py --index          # indexera i Qdrant
  python ingest_bible.py --index --force  # tvinga om-indexering
  python ingest_bible.py --simulate       # visa chunks utan att indexera
  python ingest_bible.py --test-fetch     # hämta 1 Mos 1 och verifiera källformat
  python ingest_bible.py --list-books     # lista alla 66 böcker
        """,
    )
    parser.add_argument("--fetch",        action="store_true",
                        help="Hämta bibeltexten från getbible.net och spara lokalt")
    parser.add_argument("--index",        action="store_true",
                        help="Indexera från lokal JSON-källfil")
    parser.add_argument("--simulate",     action="store_true",
                        help="Visa chunks utan att indexera (kräver ej --index)")
    parser.add_argument("--force",        action="store_true",
                        help="Tvinga om-indexering av alla chunks")
    parser.add_argument("--source",       type=Path, default=SOURCE_JSON,
                        help=f"Sökväg till källfil (default: {SOURCE_JSON})")
    parser.add_argument("--test-fetch",   action="store_true",
                        help="Hämta bara 1 Mosebok kap 1 och skriv ut resultatet")
    parser.add_argument("--list-books",   action="store_true",
                        help="Lista alla 66 böcker med kod och kapitelantal")
    parser.add_argument("--delay",        type=float, default=0.3,
                        help="Fördröjning mellan HTTP-anrop vid --fetch (sekunder, default 0.3)")
    args = parser.parse_args()

    if args.list_books:
        print(f"\n{'Kod':<8} {'Namn':<30} {'Test':<5} {'Kap':>5}")
        print("-" * 55)
        for b in BIBLE_BOOKS:
            print(f"{b['code']:<8} {b['name']:<30} {b['testament']:<5} {b['chapters']:>5}")
        print(f"\n{len(BIBLE_BOOKS)} böcker, "
              f"{sum(b['chapters'] for b in BIBLE_BOOKS)} kapitel totalt.")
        return

    if args.test_fetch:
        print("[test-fetch] Hämtar 1 Mosebok kap 1 …")
        verses = _fetch_chapter(None, 1, 1)
        if not verses:
            print(f"{_YEL}[test-fetch] Inga verser hittades.")
            print(f"  Kontrollera att TRANSLATION_CODE='{TRANSLATION_CODE}' är korrekt.")
            print(f"  Tillgängliga koder: {GETBIBLE_BASE}/translations.json{_NRM}")
            sys.exit(1)
        print(f"{_GRN}[test-fetch] OK — {len(verses)} verser hämtade:{_NRM}\n")
        for v in verses[:5]:
            print(f"  {v['verse']:>3}: {v['text']}")
        if len(verses) > 5:
            print(f"  … ({len(verses) - 5} fler)")
        return

    if args.simulate:
        ingest_bible(args.source, force=False, simulate=True)
        return

    if args.fetch:
        fetch_all(args.source, delay=args.delay)

    if args.index:
        ingest_bible(args.source, force=args.force, simulate=False)

    if not any([args.fetch, args.index, args.simulate, args.test_fetch, args.list_books]):
        parser.print_help()


if __name__ == "__main__":
    main()
