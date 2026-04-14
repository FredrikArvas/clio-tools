"""
Kommandoradsfrågor mot clio-rag (ADD v1.0 §7).

Flöde:
  1. Frågetexten embedas med text-embedding-3-small
  2. Qdrant returnerar top-5 chunks från clio_books
  3. Chunks + fråga skickas till Claude Sonnet med instruktion att citera bok och sida
  4. Svar skrivs till terminal med källhänvisning: [Ovillkorlig, s. 47]
  5. Om WD4TB1 är monterad erbjuds originalpassagen

Körning:
  python query.py --q "Vad säger Ulrika om ovillkorlig kärlek?"
  python query.py --q "..." --top 10   # fler chunks
  python query.py --q "..." --no-source  # bara svaret, ingen källhänvisning
"""

from __future__ import annotations

import argparse
import sys

import anthropic
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
from qdrant_client.models import Filter, FieldCondition, MatchValue

import config
from config import (
    COLLECTION_NAME, NCC_COLLECTION_NAME, EMBEDDING_MODEL, LLM_MODEL,
    get_qdrant_client, is_local_available,
)

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

# ---------------------------------------------------------------------------
# Systempromt till Claude
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_BOOKS = """\
Du är en hjälpsam assistent som svarar på frågor om böcker.
Du får ett antal textpassager från böcker och en fråga.
Svara på frågan baserat enbart på de givna passagerna.
Ange alltid källhänvisning i formatet [Boktitel, s. X–Y] direkt efter varje påstående.
Om informationen inte finns i passagerna, säg det tydligt.
Svara på svenska om inte frågan ställs på annat språk.
"""

SYSTEM_PROMPT_NCC = """\
Du är en hjälpsam assistent som svarar på frågor om tidigare beslut, resonemang och projektkontext.
Du får ett antal textpassager från Notion Context Cards (NCC) och en fråga.
Svara på frågan baserat enbart på de givna passagerna.
Ange alltid källhänvisning i formatet [NCC-titel] direkt efter varje påstående.
Om informationen inte finns i passagerna, säg det tydligt.
Svara på svenska om inte frågan ställs på annat språk.
"""


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def embed_query(text: str) -> list[float]:
    client = OpenAI()
    resp = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return resp.data[0].embedding


def search_qdrant(
    vector: list[float],
    top_k: int = 5,
    title_filter: str | None = None,
    collection: str = COLLECTION_NAME,
) -> list:
    client = get_qdrant_client()

    filt = None
    if title_filter:
        filt = Filter(must=[
            FieldCondition(key="title", match=MatchValue(value=title_filter))
        ])

    response = client.query_points(
        collection_name=collection,
        query=vector,
        limit=top_k,
        with_payload=True,
        query_filter=filt,
    )
    return response.points


def format_context(hits: list, is_ncc: bool = False) -> str:
    """Bygger context-strängen som skickas till Claude."""
    parts: list[str] = []
    for i, hit in enumerate(hits, 1):
        p          = hit.payload
        title      = p.get("title", "Okänd")
        summary    = p.get("summary", "")
        if is_ncc:
            source = title
        else:
            page_start = p.get("ext_page_start", 0)
            page_end   = p.get("ext_page_end", 0)
            if page_start and page_end and page_start != page_end:
                source = f"{title}, s. {page_start}–{page_end}"
            elif page_start:
                source = f"{title}, s. {page_start}"
            else:
                source = title
        parts.append(f"[Passage {i} — {source}]\n{summary}")
    return "\n\n".join(parts)


def ask_claude(question: str, context: str, is_ncc: bool = False) -> str:
    client  = anthropic.Anthropic()
    system  = SYSTEM_PROMPT_NCC if is_ncc else SYSTEM_PROMPT_BOOKS
    message = client.messages.create(
        model      = LLM_MODEL,
        max_tokens = 1024,
        system     = system,
        messages   = [
            {
                "role":    "user",
                "content": f"Textpassager:\n\n{context}\n\nFråga: {question}",
            }
        ],
    )
    return message.content[0].text


def print_sources(hits: list, is_ncc: bool = False) -> None:
    print("\n--- Källor ---")
    for hit in hits:
        p     = hit.payload
        title = p.get("title", "?")
        score = round(hit.score, 3)
        if is_ncc:
            url = p.get("ext_notion_url", "")
            print(f"  [{score}] {title}  {url}")
        else:
            page_start = p.get("ext_page_start", 0)
            page_end   = p.get("ext_page_end", 0)
            if page_start and page_end and page_start != page_end:
                pages = f"s. {page_start}–{page_end}"
            elif page_start:
                pages = f"s. {page_start}"
            else:
                pages = "sida okänd"
            print(f"  [{score}] {title}, {pages}")


def maybe_offer_original(hits: list) -> None:
    """Om WD4TB1 är monterad: erbjud att visa originalpassagen."""
    if not is_local_available():
        return
    local_paths = {h.payload.get("loc_local_path") for h in hits if h.payload.get("loc_local_path")}
    if local_paths:
        print("\n[WD4TB1 tillgänglig] Originalfiler:")
        for p in sorted(local_paths):
            print(f"  {p}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="clio-rag: fråga mot böcker eller NCC")
    parser.add_argument("--q",          required=True, help="Fråga")
    parser.add_argument("--top",        type=int, default=5, help="Antal chunks (default 5)")
    parser.add_argument("--book",       help="Filtrera på boktitel (clio_books)")
    parser.add_argument("--ncc",        action="store_true", help="Sök i clio_ncc istället för clio_books")
    parser.add_argument("--collection", help="Välj collection direkt (override av --ncc)")
    parser.add_argument("--no-source",  action="store_true", help="Visa inte källförteckning")
    args = parser.parse_args()

    question = args.q.strip()
    if not question:
        print("FEL: Frågan får inte vara tom.")
        sys.exit(1)

    # Välj collection
    if args.collection:
        collection = args.collection
    elif args.ncc:
        collection = NCC_COLLECTION_NAME
    else:
        collection = COLLECTION_NAME

    is_ncc = collection == NCC_COLLECTION_NAME

    print(f"\nFråga: {question}")
    print(f"Collection: {collection}")
    print("Söker …")

    vector  = embed_query(question)
    hits    = search_qdrant(vector, top_k=args.top, title_filter=args.book, collection=collection)

    if not hits:
        print(f"Inga träffar i {collection}. Är collection indexerad?")
        sys.exit(0)

    context = format_context(hits, is_ncc=is_ncc)
    answer  = ask_claude(question, context, is_ncc=is_ncc)

    print(f"\n{answer}")

    if not args.no_source:
        print_sources(hits, is_ncc=is_ncc)

    if not is_ncc:
        maybe_offer_original(hits)


if __name__ == "__main__":
    main()
