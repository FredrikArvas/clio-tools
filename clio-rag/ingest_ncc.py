"""
Ingestion-pipeline för clio-rag sprint 2 — Notion Context Cards (NCC).

Flöde:
  1. Hämta alla child-pages under NCC_PARENT_PAGE_ID
  2. Per sida: hämta block-innehåll och konvertera till text
  3. Chunka vid H1/H2-rubriker (~500 ord max per chunk)
  4. Re-indexeringskontroll: hoppa om last_edited_time <= indexed_at
  5. Embed med text-embedding-3-small
  6. Upsert i Qdrant collection clio_ncc

Körning:
  python ingest_ncc.py                       # alla NCC:er under NCC_PARENT_PAGE_ID
  python ingest_ncc.py --page PAGE_ID        # enskild sida (UUID med eller utan bindestreck)
  python ingest_ncc.py --force               # tvinga om-indexering
  python ingest_ncc.py --dry-run             # visa vad som skulle indexeras utan att skriva
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from notion_client import Client as NotionClient
from openai import OpenAI
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct

import config
from config import (
    NCC_COLLECTION_NAME, EMBEDDING_MODEL, SCHEMA_VERSION,
    NCC_PARENT_PAGE_ID, NOTION_TOKEN,
    get_qdrant_client, create_ncc_collection,
)
from schema.core import (
    ContentType, CorePayload, FullPayload, LocationPayload,
    NccExt, Sensitivity, StorageTier,
)

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

_GRN = "\033[92m"
_YEL = "\033[93m"
_GRY = "\033[90m"
_NRM = "\033[0m"

# Max ord per chunk
_MAX_WORDS = 500


# ---------------------------------------------------------------------------
# Notion-klient
# ---------------------------------------------------------------------------

def _get_notion() -> NotionClient:
    token = NOTION_TOKEN or ""
    if not token:
        print("[ncc] FEL: NOTION_TOKEN saknas i .env")
        sys.exit(1)
    return NotionClient(auth=token)


# ---------------------------------------------------------------------------
# Hämta child-pages
# ---------------------------------------------------------------------------

def fetch_child_pages(parent_id: str) -> list[dict]:
    """
    Hämtar alla child-pages direkt under parent_id.
    Returnerar lista av dict med id, title, last_edited_time, url.
    """
    notion   = _get_notion()
    pages    = []
    cursor   = None

    while True:
        kwargs: dict = {"block_id": parent_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp   = notion.blocks.children.list(**kwargs)
        blocks = resp.get("results", [])

        for block in blocks:
            if block.get("type") == "child_page":
                pid   = block["id"]
                title = block.get("child_page", {}).get("title", pid)
                # Hämta last_edited_time via pages API
                try:
                    page_meta = notion.pages.retrieve(page_id=pid)
                    last_edited = page_meta.get("last_edited_time", "")
                    page_url    = f"https://www.notion.so/{pid.replace('-', '')}"
                except Exception:
                    last_edited = ""
                    page_url    = f"https://www.notion.so/{pid.replace('-', '')}"
                pages.append({
                    "id":               pid,
                    "title":            title,
                    "last_edited_time": last_edited,
                    "url":              page_url,
                })

        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    return pages


# ---------------------------------------------------------------------------
# Block-extraktion → markdown-text
# ---------------------------------------------------------------------------

def _extract_rich_text(rich_text: list) -> str:
    return "".join(r.get("plain_text", "") for r in rich_text).strip()


def fetch_page_text(page_id: str) -> str:
    """
    Hämtar alla block från en Notion-sida och konverterar till markdown-text.
    Hanterar pagination (max 100 block per anrop).
    """
    notion = _get_notion()
    lines  = []
    cursor = None

    while True:
        kwargs: dict = {"block_id": page_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp   = notion.blocks.children.list(**kwargs)
        blocks = resp.get("results", [])

        for block in blocks:
            btype = block.get("type", "")
            content = block.get(btype, {})
            rich    = content.get("rich_text", [])
            text    = _extract_rich_text(rich)

            if btype == "heading_1" and text:
                lines.append(f"# {text}")
            elif btype == "heading_2" and text:
                lines.append(f"## {text}")
            elif btype == "heading_3" and text:
                lines.append(f"### {text}")
            elif btype == "paragraph" and text:
                lines.append(text)
            elif btype == "bulleted_list_item" and text:
                lines.append(f"- {text}")
            elif btype == "numbered_list_item" and text:
                lines.append(f"1. {text}")
            elif btype == "quote" and text:
                lines.append(f"> {text}")
            elif btype == "code" and text:
                lang = content.get("language", "")
                lines.append(f"```{lang}\n{text}\n```")
            elif btype == "callout" and text:
                lines.append(f"> {text}")
            elif btype == "divider":
                lines.append("---")
            # child_page, image, video etc. hoppas över

        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rubrik-baserad chunkning
# ---------------------------------------------------------------------------

def chunk_by_headings(text: str, page_title: str) -> list[tuple[str, str]]:
    """
    Delar markdown-text vid H1/H2-rubriker.
    Returnerar lista av (heading, chunk_text).
    Chunks > MAX_WORDS ord delas vid styckebrytning.
    """
    # Lägg till sidtiteln som implicit H1 om texten inte börjar med en rubrik
    if not text.startswith("#"):
        text = f"# {page_title}\n{text}"

    # Dela vid H1/H2
    pattern = re.compile(r"^(#{1,2} .+)$", re.MULTILINE)
    parts   = pattern.split(text)

    chunks: list[tuple[str, str]] = []
    current_heading = page_title
    current_body    = ""

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if pattern.match(part):
            # Ny rubrik — spara föregående chunk
            if current_body.strip():
                chunks.extend(_split_long_chunk(current_heading, current_body))
            current_heading = part.lstrip("#").strip()
            current_body    = ""
        else:
            current_body += "\n" + part

    # Sista chunken
    if current_body.strip():
        chunks.extend(_split_long_chunk(current_heading, current_body))

    return chunks


def _split_long_chunk(heading: str, body: str) -> list[tuple[str, str]]:
    """Delar en för lång chunk (> MAX_WORDS) vid styckebrytning."""
    words = body.split()
    if len(words) <= _MAX_WORDS:
        return [(heading, f"## {heading}\n{body}".strip())]

    result: list[tuple[str, str]] = []
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    current_words = 0
    current_parts: list[str] = []

    for para in paragraphs:
        para_words = len(para.split())
        if current_words + para_words > _MAX_WORDS and current_parts:
            chunk_text = f"## {heading}\n" + "\n\n".join(current_parts)
            result.append((heading, chunk_text.strip()))
            current_parts = [para]
            current_words = para_words
        else:
            current_parts.append(para)
            current_words += para_words

    if current_parts:
        chunk_text = f"## {heading}\n" + "\n\n".join(current_parts)
        result.append((heading, chunk_text.strip()))

    return result


# ---------------------------------------------------------------------------
# Re-indexeringskontroll
# ---------------------------------------------------------------------------

def get_indexed_at(qdrant, source_id: str) -> Optional[str]:
    """
    Hämtar indexed_at för ett source_id (första chunk).
    Returnerar ISO-sträng eller None om sidan ej är indexerad.
    """
    filt = Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])
    result, _ = qdrant.scroll(
        collection_name=NCC_COLLECTION_NAME,
        scroll_filter=filt,
        limit=1,
        with_payload=True,
        with_vectors=False,
    )
    if result:
        return result[0].payload.get("indexed_at")
    return None


def needs_reindex(last_edited_time: str, indexed_at: Optional[str]) -> bool:
    """True om sidan uppdaterats sedan senaste indexering."""
    if indexed_at is None:
        return True
    if not last_edited_time:
        return False
    try:
        edited  = datetime.fromisoformat(last_edited_time.replace("Z", "+00:00"))
        indexed = datetime.fromisoformat(indexed_at.replace("Z", "+00:00"))
        return edited > indexed
    except ValueError:
        return True


def delete_page_chunks(qdrant, source_id: str) -> None:
    """Tar bort alla chunks för ett source_id."""
    filt = Filter(must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))])
    qdrant.delete(collection_name=NCC_COLLECTION_NAME, points_selector=filt)


# ---------------------------------------------------------------------------
# Huvud-pipeline
# ---------------------------------------------------------------------------

def source_id_for_page(page_id: str) -> str:
    """Deterministiskt UUID v5 baserat på Notion page-ID."""
    clean = page_id.replace("-", "")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"notion:{clean}"))


def ingest_ncc_page(
    page: dict,
    qdrant,
    openai_client,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """
    Indexerar en NCC-sida. Returnerar antal nya chunks.
    """
    page_id         = page["id"]
    title           = page["title"]
    last_edited     = page["last_edited_time"]
    page_url        = page["url"]
    source_id       = source_id_for_page(page_id)

    print(f"\n[ncc] {title}")

    # Re-indexeringskontroll
    if not force:
        indexed_at = get_indexed_at(qdrant, source_id)
        if not needs_reindex(last_edited, indexed_at):
            print(f"  {_GRY}→ oförändrad sedan {indexed_at[:10]}, hoppar{_NRM}")
            return 0

    # Hämta text
    print(f"  Hämtar block från Notion …")
    text = fetch_page_text(page_id)
    if not text.strip():
        print(f"  {_YEL}→ tom sida, hoppar{_NRM}")
        return 0

    # Chunka
    chunks = chunk_by_headings(text, title)
    total  = len(chunks)
    print(f"  {total} chunks")

    if dry_run:
        for i, (heading, chunk_text) in enumerate(chunks):
            words = len(chunk_text.split())
            print(f"    [{i}] {heading[:60]} ({words} ord)")
        return total

    # Radera gamla
    delete_page_chunks(qdrant, source_id)

    now         = datetime.now(timezone.utc).isoformat()
    new_count   = 0
    points: list[PointStruct] = []

    for idx, (heading, chunk_text) in enumerate(chunks):
        chunk_text = chunk_text.strip()
        if not chunk_text:
            continue

        # Embedding
        resp   = openai_client.embeddings.create(input=[chunk_text], model=EMBEDDING_MODEL)
        vector = resp.data[0].embedding

        # Payload
        core = CorePayload(
            title           = title,
            summary         = chunk_text[:1200].strip(),
            content_type    = ContentType.NCC,
            language        = "sv",
            tags            = [],
            quality_score   = 1.0,
            sensitivity     = Sensitivity.INTERNAL,
            source_id       = source_id,
            chunk_index     = idx,
            chunk_total     = total,
            source_hash     = "",          # NCC använder last_edited_time, ej SHA-256
            embedding_model = f"{EMBEDDING_MODEL}:{config.EMBEDDING_DIM}",
            schema_version  = SCHEMA_VERSION,
            indexed_at      = now,
        )
        location = LocationPayload(
            storage_tier    = StorageTier.CLOUD,
            cloud_path      = page_url,
            local_available = False,
        )
        ext = NccExt(
            notion_page_id   = page_id,
            notion_url       = page_url,
            last_edited_time = last_edited,
            parent_page_id   = NCC_PARENT_PAGE_ID,
        )
        payload = FullPayload(core=core, location=location, ext=ext)

        points.append(PointStruct(
            id      = core.id,
            vector  = vector,
            payload = payload.to_dict(),
        ))
        new_count += 1

        # Batch-upsert var 20:e chunk
        if len(points) >= 20:
            qdrant.upsert(collection_name=NCC_COLLECTION_NAME, points=points)
            print(f"  upsert {new_count}/{total} chunks …")
            points = []

    if points:
        qdrant.upsert(collection_name=NCC_COLLECTION_NAME, points=points)

    print(f"  {_GRN}✓{_NRM} {new_count} chunks indexerade")
    return new_count


def ingest_all(parent_page_id: str, force: bool = False, dry_run: bool = False) -> None:
    """Indexerar alla NCC:er under parent_page_id."""
    print(f"[ncc] Hämtar child-pages från Notion …")
    pages = fetch_child_pages(parent_page_id)
    print(f"[ncc] {len(pages)} NCC-sidor hittade\n")

    if not dry_run:
        create_ncc_collection()

    qdrant = get_qdrant_client() if not dry_run else None
    openai = OpenAI()              if not dry_run else None

    total_new = 0
    for page in pages:
        total_new += ingest_ncc_page(page, qdrant, openai, force=force, dry_run=dry_run)

    label = "chunk(s) skulle indexerats" if dry_run else "chunks indexerade totalt"
    print(f"\n[ncc] Klart — {total_new} {label}.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="clio-rag NCC ingestion — sprint 2")
    parser.add_argument("--page",    help="Enskild Notion page-ID att indexera")
    parser.add_argument("--force",   action="store_true", help="Tvinga om-indexering")
    parser.add_argument("--dry-run", action="store_true", help="Visa vad som skulle indexeras")
    args = parser.parse_args()

    if args.page:
        notion = _get_notion()
        page_meta = notion.pages.retrieve(page_id=args.page)
        title = ""
        for _, v in page_meta.get("properties", {}).items():
            if v.get("type") == "title":
                title = "".join(r["plain_text"] for r in v["title"])
                break
        page = {
            "id":               args.page,
            "title":            title or args.page,
            "last_edited_time": page_meta.get("last_edited_time", ""),
            "url":              f"https://www.notion.so/{args.page.replace('-', '')}",
        }
        qdrant = get_qdrant_client() if not args.dry_run else None
        openai = OpenAI()              if not args.dry_run else None
        if not args.dry_run:
            create_ncc_collection()
        ingest_ncc_page(page, qdrant, openai, force=args.force, dry_run=args.dry_run)
    else:
        ingest_all(NCC_PARENT_PAGE_ID, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
