#!/usr/bin/env python3
"""
ea_ingest.py — Elizabeth April YouTube RAG Corpus Ingestion, Fas 1
Hämtar videolista via YouTube Data API v3, transkript via youtube-transcript-api,
chunkar och upsertart till Qdrant vigil_consciousness.
Synkar även ett clio.media.article per video till Odoo (uap-databasen).

Kör: python ea_ingest.py [--dry-run] [--max N] [--video-id VIDEO_ID]
"""
import argparse
import logging
import os
import sys
import time
import uuid
import xmlrpc.client
from pathlib import Path

import requests
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType

# ── Ladda .env ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
# Fallback: läs vigil .env på servern om vi kör lokalt via SSH-miljö
_vigil_env = Path("/home/clioadmin/19.0/clio-tools/clio-vigil/.env")
if _vigil_env.exists():
    load_dotenv(_vigil_env, override=False)

# ── Config ───────────────────────────────────────────────────────────────────
CHANNEL_ID     = "UC3Pdep93CKklB-WAMpJXN5w"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

QDRANT_HOST    = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT    = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_TIMEOUT = 60
COLLECTION     = "vigil_consciousness"

SUPADATA_API_KEY = os.getenv("SUPADATA_API_KEY", "")
SUPADATA_URL     = "https://api.supadata.ai/v1/youtube/transcript"

OLLAMA_HOST    = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL    = "bge-m3"
VECTOR_SIZE    = 1024

ODOO_URL       = os.getenv("VIGIL_ODOO_URL", "")
ODOO_DB        = os.getenv("VIGIL_ODOO_DB", "")
ODOO_USER      = os.getenv("ODOO_USER", "")
ODOO_PASS      = os.getenv("ODOO_PASSWORD", "")

CHUNK_CHARS    = 1600
OVERLAP_CHARS  = 200
EMBED_BATCH    = 8
SLEEP_BETWEEN  = 1.0   # Supadata hanterar rate-limiting internt

LOG_FILE           = "/tmp/ea_ingest.log"
NO_TRANSCRIPT_FILE = "/tmp/ea_no_transcript.tsv"

COPYRIGHT = {
    "owner": "Elizabeth April",
    "status": "restricted",
    "license": "private_research_only",
    "authorized_user": "fredrik@arvas.se",
}

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ea_ingest")


# ── YouTube Data API v3 ──────────────────────────────────────────────────────
def fetch_channel_videos(channel_id: str, api_key: str) -> list[dict]:
    videos, url = [], "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": api_key, "channelId": channel_id,
        "part": "snippet", "type": "video",
        "order": "date", "maxResults": 50,
    }
    page = 1
    while True:
        log.info(f"YouTube API — sida {page} ({len(videos)} videor hittills)")
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []):
            snippet = item["snippet"]
            videos.append({
                "video_id":     item["id"]["videoId"],
                "title":        snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", "")[:10],
                "description":  snippet.get("description", ""),
            })
        next_page = data.get("nextPageToken")
        if not next_page:
            break
        params["pageToken"] = next_page
        page += 1
        time.sleep(0.5)
    log.info(f"Totalt från YouTube API: {len(videos)} videor")
    return videos


# ── Qdrant ───────────────────────────────────────────────────────────────────
def get_qdrant() -> QdrantClient:
    return QdrantClient(QDRANT_HOST, port=QDRANT_PORT, timeout=QDRANT_TIMEOUT)


def ensure_collection(client: QdrantClient):
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION not in existing:
        log.info(f"Skapar kollektion: {COLLECTION}")
        client.create_collection(
            COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            on_disk_payload=True,
        )
        for field in ("source", "video_id", "published_at", "methodological_box"):
            client.create_payload_index(COLLECTION, field, PayloadSchemaType.KEYWORD)
        log.info("Kollektion och index skapade.")
    else:
        log.info(f"Kollektion {COLLECTION} finns redan.")


def point_id(video_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{video_id}_{chunk_index}"))


def already_indexed(client: QdrantClient, video_id: str) -> bool:
    return len(client.retrieve(COLLECTION, ids=[point_id(video_id, 0)], with_payload=False)) > 0


# ── Odoo ─────────────────────────────────────────────────────────────────────
_odoo_uid: int | None = None
_odoo_models = None

def get_odoo():
    global _odoo_uid, _odoo_models
    if _odoo_uid is None:
        common = xmlrpc.client.ServerProxy(ODOO_URL + "/xmlrpc/2/common")
        _odoo_uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASS, {})
        _odoo_models = xmlrpc.client.ServerProxy(ODOO_URL + "/xmlrpc/2/object")
        log.info(f"Odoo ansluten: UID={_odoo_uid}, DB={ODOO_DB}")
    return _odoo_uid, _odoo_models


def sync_article_to_odoo(video: dict, fulltext: str, dry_run: bool = False) -> bool:
    """Skapar eller uppdaterar ett clio.media.article per video."""
    if not ODOO_URL:
        return False
    try:
        uid, models = get_odoo()
        yt_url = f"https://youtube.com/watch?v={video['video_id']}"

        # Sök befintlig artikel
        existing = models.execute_kw(
            ODOO_DB, uid, ODOO_PASS, "clio.media.article", "search_read",
            [[["url", "=", yt_url]]],
            {"fields": ["id"], "limit": 1},
        )

        supadata_url = (
            f"{SUPADATA_URL}?videoId={video['video_id']}&text=true"
            if fulltext else ""
        )
        vals = {
            "title":        video["title"],
            "url":          yt_url,
            "source":       "elizabeth_april",
            "body":         fulltext[:60000],  # Odoo text-fält, trunkerat
            "language":     "en",
            "media_type":   "video",
            "vigil_state":  "notified",
            "supadata_url": supadata_url,
        }
        if video["published_at"] and video["published_at"] != "unknown":
            vals["published"] = video["published_at"] + " 00:00:00"

        if dry_run:
            log.info(f"[ODOO DRY] {'update' if existing else 'create'} — {video['title'][:50]}")
            return True

        if existing:
            models.execute_kw(ODOO_DB, uid, ODOO_PASS, "clio.media.article", "write",
                              [[existing[0]["id"]], vals])
        else:
            models.execute_kw(ODOO_DB, uid, ODOO_PASS, "clio.media.article", "create", [vals])

        return True
    except Exception as e:
        log.warning(f"[ODOO ERROR] {video['video_id']}: {e}")
        return False


# ── Embedding ────────────────────────────────────────────────────────────────
def embed_batch(texts: list[str]) -> list[list[float]]:
    resp = requests.post(
        OLLAMA_HOST + "/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=120,
    )
    resp.raise_for_status()
    embeddings = resp.json().get("embeddings", [])
    if len(embeddings) != len(texts):
        raise ValueError(f"Ollama: {len(embeddings)} vektorer för {len(texts)} texter")
    return embeddings


# ── Chunkning ────────────────────────────────────────────────────────────────
def chunk_text(text: str) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + CHUNK_CHARS])
        start += CHUNK_CHARS - OVERLAP_CHARS
    return chunks


# ── Supadata transcript ──────────────────────────────────────────────────────
def fetch_transcript_supadata(video_id: str) -> str | None:
    """Hämtar transkript via Supadata API. Returnerar None om ej tillgängligt."""
    resp = requests.get(
        SUPADATA_URL,
        params={"videoId": video_id, "text": "true"},
        headers={"x-api-key": SUPADATA_API_KEY},
        timeout=30,
    )
    if resp.status_code == 404:
        return None  # Inget transkript för denna video
    if resp.status_code == 429:
        log.warning(f"[SUPADATA] Rate limit nådd — väntar 60s")
        time.sleep(60)
        resp = requests.get(
            SUPADATA_URL,
            params={"videoId": video_id, "text": "true"},
            headers={"x-api-key": SUPADATA_API_KEY},
            timeout=30,
        )
    resp.raise_for_status()
    data = resp.json()
    content = data.get("content", "")
    if isinstance(content, str):
        return content
    # Fallback: lista av {text, offset, duration}
    return " ".join(c.get("text", "") for c in content)


# ── Ingest per video ─────────────────────────────────────────────────────────
def ingest_video(client: QdrantClient, video: dict, dry_run: bool) -> str:
    video_id     = video["video_id"]
    title        = video["title"]

    if already_indexed(client, video_id):
        log.info(f"[SKIP] {video_id} — redan i Qdrant")
        return "skipped"

    # Hämta transkript via Supadata
    try:
        fulltext = fetch_transcript_supadata(video_id)
    except requests.HTTPError as e:
        log.warning(f"[SUPADATA ERROR] {video_id} — HTTP {e.response.status_code}: {e}")
        return "error"
    except Exception as e:
        log.warning(f"[ERROR] {video_id} — {type(e).__name__}: {e}")
        return "error"

    if fulltext is None:
        log.info(f"[NO_TRANSCRIPT] {video_id} — {title[:50]}")
        return "no_transcript"

    chunks = chunk_text(fulltext)
    log.info(f"[TRANSKRIPT] {video_id} — {title[:50]!r} → {len(chunks)} chunks")

    if dry_run:
        sync_article_to_odoo(video, fulltext, dry_run=True)
        return "dry_run"

    # Embedd + upsert i batchar
    for batch_start in range(0, len(chunks), EMBED_BATCH):
        batch_chunks = chunks[batch_start:batch_start + EMBED_BATCH]
        try:
            vectors = embed_batch(batch_chunks)
        except Exception as e:
            log.error(f"[EMBED_ERROR] {video_id} batch {batch_start}: {e}")
            return "embed_error"

        points = []
        for i, (chunk, vector) in enumerate(zip(batch_chunks, vectors)):
            chunk_idx = batch_start + i
            points.append(PointStruct(
                id=point_id(video_id, chunk_idx),
                vector=vector,
                payload={
                    "source":             "elizabeth_april",
                    "source_type":        "youtube_transcript",
                    "video_id":           video_id,
                    "title":              title,
                    "published_at":       video["published_at"],
                    "chunk_index":        chunk_idx,
                    "text":               chunk,
                    "url":                f"https://youtube.com/watch?v={video_id}",
                    "copyright":          COPYRIGHT,
                    "research_domain":    "consciousness",
                    "methodological_box": "consciousness_phenomena",
                    "tags":               [],
                },
            ))
        client.upsert(COLLECTION, points=points)

    # Odoo-sync: ett artikel per video
    sync_article_to_odoo(video, fulltext)

    log.info(f"[OK] {video_id} — {len(chunks)} chunks + Odoo-artikel")
    return "ok"


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="EA Ingest Fas 1")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--max",      type=int, default=0)
    parser.add_argument("--max-api",  type=int, default=0, help="Max antal Supadata API-anrop (credits)")
    parser.add_argument("--video-id", type=str, default="")
    args = parser.parse_args()

    if not GOOGLE_API_KEY:
        log.error("GOOGLE_API_KEY saknas i .env")
        sys.exit(1)
    if not SUPADATA_API_KEY:
        log.error("SUPADATA_API_KEY saknas i .env")
        sys.exit(1)

    client = get_qdrant()
    ensure_collection(client)

    if args.video_id:
        videos = [{"video_id": args.video_id, "title": "manuell", "published_at": "unknown", "description": ""}]
    else:
        videos = fetch_channel_videos(CHANNEL_ID, GOOGLE_API_KEY)

    if args.max:
        videos = videos[:args.max]

    log.info(f"=== EA Ingest Fas 1 — {len(videos)} videor ===")

    stats = {"ok": 0, "skipped": 0, "no_transcript": 0, "error": 0, "embed_error": 0, "dry_run": 0}
    no_trans, dates = [], []
    api_calls = 0

    for i, video in enumerate(videos, 1):
        log.info(f"[{i}/{len(videos)}] {video['video_id']}")
        status = ingest_video(client, video, args.dry_run)
        stats[status] = stats.get(status, 0) + 1
        if status not in ("skipped",):
            api_calls += 1  # Supadata anropades (ok, no_transcript, error, dry_run)
        if status == "no_transcript":
            no_trans.append(f"{video['video_id']}\t{video['title']}\t{video['published_at']}")
        if status == "ok" and video["published_at"] not in ("", "unknown"):
            dates.append(video["published_at"])
        if args.max_api and api_calls >= args.max_api:
            log.info(f"[STOP] max-api {args.max_api} nådd — {api_calls} Supadata-anrop gjorda")
            break
        time.sleep(SLEEP_BETWEEN)

    if no_trans:
        Path(NO_TRANSCRIPT_FILE).write_text("\n".join(no_trans))
        log.info(f"Utan transkript → {NO_TRANSCRIPT_FILE}")

    info = client.get_collection(COLLECTION)
    date_range = f"{min(dates)} → {max(dates)}" if dates else "okänt"

    log.info("=" * 55)
    log.info("=== EA Ingest — sammanfattning ===")
    log.info(f"Videor totalt:      {len(videos)}")
    log.info(f"Indexerade (nya):   {stats['ok']}")
    log.info(f"Redan indexerade:   {stats['skipped']}")
    log.info(f"Utan transkript:    {stats['no_transcript']}")
    log.info(f"Fel:                {stats['error'] + stats.get('embed_error', 0)}")
    log.info(f"Dry-run:            {stats['dry_run']}")
    log.info(f"Datum span:         {date_range}")
    log.info(f"Supadata API-anrop: {api_calls}")
    log.info(f"Punkter i Qdrant:   {info.points_count}")
    log.info("=" * 55)


if __name__ == "__main__":
    main()
