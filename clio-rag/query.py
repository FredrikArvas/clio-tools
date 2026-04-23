"""
Kommandoradsfrågor mot clio-rag (ADD v1.0 §7).

Flöde:
  1. Frågetexten embedas med text-embedding-3-small
  2. Qdrant returnerar top-5 chunks från vald collection
  3. Chunks + fråga (+ valfri konversationshistorik + bilagor) skickas till Claude Sonnet
  4. Svar skrivs till terminal med källhänvisning

Körning:
  python query.py --q "Vad säger Ulrika om ovillkorlig kärlek?"
  python query.py --q "..." --collection cap_ssf_crm
  python query.py --q "..." --top 10
  python query.py --q "..." --history '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'
  python query.py --q "..." --attachment-text "extraherad text från bilaga"
"""

from __future__ import annotations

import argparse
import json
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
# Systempromptar
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

SYSTEM_PROMPT_PROJECT = """\
Du är en hjälpsam projektassistent med tillgång till projektdokumentation.
Du får relevanta textpassager ur projektets dokument och en fråga.
Svara baserat på passagerna. Ange källhänvisning [Dokumentnamn] efter varje påstående.
Om informationen inte finns, säg det tydligt och föreslå vilken typ av dokument som skulle behövas.
Du har även tillgång till konversationshistorik — använd den för att förstå kontext och följdfrågor.
Om en bilaga bifogas, prioritera informationen i bilagan framför RAG-passagerna.
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


def ask_claude(
    question: str,
    context: str,
    is_ncc: bool = False,
    history: list[dict] | None = None,
    attachment_text: str | None = None,
    is_project: bool = False,
) -> str:
    """
    Skickar fråga + kontext till Claude.
    history: lista med {"role": "user"|"assistant", "content": "..."} — tidigare utbyte
    attachment_text: extraherad text från en bifogad fil
    """
    client = anthropic.Anthropic()

    if is_project:
        system = SYSTEM_PROMPT_PROJECT
    elif is_ncc:
        system = SYSTEM_PROMPT_NCC
    else:
        system = SYSTEM_PROMPT_BOOKS

    # Bygg user-meddelandet
    user_parts = [f"Projektdokumentation (RAG):\n\n{context}"]
    if attachment_text:
        user_parts.append(f"Bifogad fil:\n\n{attachment_text[:4000]}")
    user_parts.append(f"Fråga: {question}")
    user_content = "\n\n---\n\n".join(user_parts)

    # Bygg messages — historik först (max 6 = 3 utbyten), sedan aktuell fråga
    messages: list[dict] = []
    if history:
        for msg in history[-6:]:
            role    = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content.strip():
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_content})

    message = client.messages.create(
        model=LLM_MODEL,
        max_tokens=1500,
        system=system,
        messages=messages,
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
    parser = argparse.ArgumentParser(description="clio-rag: fråga mot böcker, NCC eller projektdokumentation")
    parser.add_argument("--q",               required=True, help="Fråga")
    parser.add_argument("--top",             type=int, default=5, help="Antal chunks (default 5)")
    parser.add_argument("--book",            help="Filtrera på boktitel (clio_books)")
    parser.add_argument("--ncc",             action="store_true", help="Sök i clio_ncc")
    parser.add_argument("--collection",      help="Välj collection direkt")
    parser.add_argument("--no-source",       action="store_true", help="Visa inte källförteckning")
    parser.add_argument("--history",         help="JSON-sträng med konversationshistorik")
    parser.add_argument("--attachment-text", help="Extraherad text från bifogad fil")
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

    is_ncc     = collection == NCC_COLLECTION_NAME
    is_project = not is_ncc and collection != COLLECTION_NAME

    # Parsa historik
    history: list[dict] | None = None
    if args.history:
        try:
            history = json.loads(args.history)
        except json.JSONDecodeError:
            pass

    print(f"\nFråga: {question}")
    print(f"Collection: {collection}")
    if history:
        print(f"Historik: {len(history)} meddelanden")
    if args.attachment_text:
        print(f"Bilaga: {len(args.attachment_text)} tecken")
    print("Söker …")

    vector  = embed_query(question)
    hits    = search_qdrant(vector, top_k=args.top, title_filter=args.book, collection=collection)

    if not hits:
        print(f"Inga träffar i {collection}. Är collection indexerad?")
        sys.exit(0)

    context = format_context(hits, is_ncc=is_ncc)
    answer  = ask_claude(
        question,
        context,
        is_ncc=is_ncc,
        history=history,
        attachment_text=args.attachment_text,
        is_project=is_project,
    )

    print(f"\n{answer}")

    if not args.no_source:
        print_sources(hits, is_ncc=is_ncc)

    if not is_ncc:
        maybe_offer_original(hits)


if __name__ == "__main__":
    main()
