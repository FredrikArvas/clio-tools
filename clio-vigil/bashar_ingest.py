#!/usr/bin/env python3
"""
bashar_ingest.py — Fristående RAG-ingest för Bashar/Darryl Anka
================================================================
Skapar och populerar Qdrant-kollektion 'vigil_bashar' med material från:

  Phase 0  --setup               Skapa kollektion + payload-index
  Phase 5  --batgap              Buddha at the Gas Pump-intervju (fritt)
  Phase 3  --youtube             Officiell YouTube-kanal (fritt)
  Phase 1  --bashtartv --catalog Katalogkartläggning via Uscreen API (kräver cookie)
  Phase 2  --bashtartv           Katalog + download + transkription
  Phase 4  --book FILE           Manuellt anskaffad bok (PDF/epub)

Copyright: Darryl Anka / Bashar Communications Inc.
Auktoriserat för privat forskningsanvändning av fredrik@arvas.se.
Materialet får aldrig reproduceras verbatim i externa output.

Körning — rekommenderad ordning:
  python bashar_ingest.py --setup
  python bashar_ingest.py --batgap
  python bashar_ingest.py --youtube [--max 20]
  python bashar_ingest.py --bashtartv --catalog --cookies data/bashar_cookies.json
  python bashar_ingest.py --bashtartv --cookies data/bashar_cookies.json [--max 10]
  python bashar_ingest.py --book /path/to/book.pdf --title "The New Metaphysics" --year 1987
"""

import argparse
import http.cookiejar
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env", override=True) or load_dotenv(_HERE.parent / ".env", override=True)

OLLAMA_HOST     = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("VIGIL_EMBED_MODEL", "bge-m3")
EMBEDDING_DIM   = 1024

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

COLLECTION = "vigil_bashar"

DATA_DIR      = _HERE / "data"
SESSION_INDEX = DATA_DIR / "bashar_session_index.json"
INDEXED_SET   = DATA_DIR / "bashar_indexed.json"   # lokalt dedup-register
INGEST_LOG    = DATA_DIR / "bashar_ingest.log"
AUDIO_DIR     = DATA_DIR / "bashar_audio"
CAPTIONS_DIR  = DATA_DIR / "bashar_captions"

# Chunkning — audio (Whisper-segment)
CHUNK_WINDOW_SEC  = 300   # 5 minuter
CHUNK_OVERLAP_SEC = 30    # 30 sekunders överlapp

# Chunkning — fritext (~400 tokens / 50 tokens överlapp)
CHUNK_WORDS         = 300
CHUNK_WORDS_OVERLAP = 35

EMBED_BATCH_SIZE = 3

USCREEN_API = "https://api.uscreencdn.com"

COPYRIGHT = {
    "owner": "Bashar Communications Inc.",
    "status": "restricted",
    "license": "private_research_only",
    "authorized_user": "fredrik@arvas.se",
}

# Whisper-modell (samma som vigil-pipelinen)
WHISPER_MODEL = "large-v3-turbo"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dedup-register (lokalt JSON-set)
# ---------------------------------------------------------------------------

def _load_indexed_set() -> set:
    if INDEXED_SET.exists():
        with open(INDEXED_SET, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def _save_indexed_set(s: set):
    with open(INDEXED_SET, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=2)


def _dedup_key(title: str, date: str) -> str:
    return f"{title.lower().strip()}|{date}"


def already_indexed(title: str, date: str, indexed_set: set) -> bool:
    return _dedup_key(title, date) in indexed_set


def mark_indexed(title: str, date: str, indexed_set: set):
    indexed_set.add(_dedup_key(title, date))


# ---------------------------------------------------------------------------
# Loggning
# ---------------------------------------------------------------------------

def _log(level: str, reason: str, title: str):
    with open(INGEST_LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {level} [{reason}] {title}\n")


def log_skip(reason: str, title: str):  _log("SKIP",  reason, title)
def log_error(reason: str, title: str): _log("ERROR", reason, title)


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------

def _get_client():
    from qdrant_client import QdrantClient
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)


def setup_collection():
    """Phase 0: Skapar vigil_bashar + payload-index om de saknas."""
    from qdrant_client.models import Distance, VectorParams, PayloadSchemaType

    client   = _get_client()
    existing = {c.name for c in client.get_collections().collections}

    if COLLECTION not in existing:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info("Kollektion skapad: %s (%d dim, Cosine)", COLLECTION, EMBEDDING_DIM)
    else:
        logger.info("Kollektion finns redan: %s", COLLECTION)

    indexes = {
        "source":        PayloadSchemaType.KEYWORD,
        "source_type":   PayloadSchemaType.KEYWORD,
        "session_date":  PayloadSchemaType.KEYWORD,
        "category_year": PayloadSchemaType.INTEGER,
        "entity":        PayloadSchemaType.KEYWORD,
        "tags":          PayloadSchemaType.KEYWORD,
    }
    created = []
    for field, schema in indexes.items():
        try:
            client.create_payload_index(COLLECTION, field, schema)
            created.append(field)
        except Exception as e:
            if "already exists" in str(e).lower():
                pass   # OK
            else:
                logger.warning("Payload-index %s: %s", field, e)

    print(f"✓ {COLLECTION} ({EMBEDDING_DIM} dim, Cosine)")
    if created:
        print(f"  Nya payload-index: {', '.join(created)}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Embedding — Ollama bge-m3 (exakt samma mönster som indexer.py)
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embeddar lista av texter i batchar via Ollama bge-m3."""
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        resp  = httpx.post(
            f"{OLLAMA_HOST}/api/embed",
            json={"model": EMBEDDING_MODEL, "input": batch},
            timeout=300.0,
        )
        resp.raise_for_status()
        vecs = resp.json().get("embeddings", [])
        if len(vecs) != len(batch):
            raise ValueError(f"Ollama: {len(vecs)} vektorer för {len(batch)} texter")
        all_vectors.extend(vecs)
    return all_vectors


# ---------------------------------------------------------------------------
# Chunkning
# ---------------------------------------------------------------------------

def chunk_segments(segments: list[dict]) -> list[dict]:
    """Delar Whisper-segment i tidsfönster med överlapp (300s / 30s)."""
    if not segments:
        return []
    chunks:            list[dict] = []
    chunk_start        = segments[0]["start"]
    chunk_end          = chunk_start + CHUNK_WINDOW_SEC
    current_texts:     list[str]  = []
    current_seg_start  = segments[0]["start"]

    for seg in segments:
        if seg["start"] >= chunk_end:
            if current_texts:
                chunks.append({
                    "text":          " ".join(current_texts),
                    "segment_start": current_seg_start,
                    "segment_end":   seg["start"],
                })
            chunk_start       = max(chunk_end - CHUNK_OVERLAP_SEC, seg["start"])
            chunk_end         = chunk_start + CHUNK_WINDOW_SEC
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


def chunk_text(text: str) -> list[dict]:
    """Delar fritext i ord-fönster (~300 ord / 35 ord överlapp ≈ 400/50 tokens)."""
    words = text.split()
    if not words:
        return []
    chunks: list[dict] = []
    step = CHUNK_WORDS - CHUNK_WORDS_OVERLAP
    i    = 0
    while i < len(words):
        end   = min(i + CHUNK_WORDS, len(words))
        chunk = " ".join(words[i:end])
        chunks.append({"text": chunk, "segment_start": i, "segment_end": end})
        if end == len(words):
            break
        i += step
    return chunks


def chunk_qa_list(items: list[str]) -> list[dict]:
    """Varje Q&A-item blir ett eget chunk — delar aldrig mitt i ett par."""
    return [
        {"text": item.strip(), "segment_start": idx, "segment_end": idx + 1}
        for idx, item in enumerate(items)
        if item.strip()
    ]


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

def upsert_chunks(chunks: list[dict], base_payload: dict) -> int:
    """Embeddar och upsertar chunks i vigil_bashar. Returnerar antal upsertade."""
    from qdrant_client.models import PointStruct

    if not chunks:
        return 0

    client  = _get_client()
    texts   = [c["text"] for c in chunks]
    vectors = embed_texts(texts)

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                **base_payload,
                "chunk_index":   i,
                "chunk_total":   len(chunks),
                "segment_start": c["segment_start"],
                "segment_end":   c["segment_end"],
                "text":          c["text"],
            },
        )
        for i, (c, vector) in enumerate(zip(chunks, vectors))
    ]
    client.upsert(collection_name=COLLECTION, points=points)
    return len(points)


# ---------------------------------------------------------------------------
# Phase 5: BATGAP-intervju
# ---------------------------------------------------------------------------

def run_batgap(indexed_set: set) -> dict:
    """Scraper och indexerar BATGAP-intervju med Darryl Anka (som sig själv)."""
    URL    = "https://batgap.com/darryl-anka-bashar-transcript/"
    title  = "Darryl Anka — Buddha at the Gas Pump Interview"
    sdate  = "2013-01-01"

    if already_indexed(title, sdate, indexed_set):
        log_skip("already_indexed", title)
        print("  BATGAP: redan indexerad")
        return {"batgap_chunks": 0, "skipped": 1}

    logger.info("Scraper BATGAP: %s", URL)
    resp = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    text = _extract_main_text(resp.text)
    if len(text) < 500:
        raise ValueError(f"BATGAP-transkript verkar tomt ({len(text)} tecken)")

    logger.info("BATGAP-transkript: %d tecken", len(text))

    base_payload = {
        "source":             "bashar_darryl_anka",
        "source_type":        "interview_transcript",
        "session_title":      title,
        "session_date":       sdate,
        "category_year":      2013,
        "duration_seconds":   0,
        "url":                URL,
        "entity":             "Darryl Anka (as himself)",
        "channeler":          "Darryl Anka",
        "platform":           "BATGAP",
        "copyright":          COPYRIGHT,
        "research_domain":    "consciousness",
        "methodological_box": "interview",
        "tags":               ["batgap", "darryl_anka", "interview"],
    }

    chunks = chunk_text(text)
    n      = upsert_chunks(chunks, base_payload)
    mark_indexed(title, sdate, indexed_set)
    logger.info("BATGAP: %d chunks upsertade", n)
    return {"batgap_chunks": n, "skipped": 0}


def _extract_main_text(html: str) -> str:
    """Extraherar huvudtext från HTML — försöker BeautifulSoup, annars regex."""
    try:
        from bs4 import BeautifulSoup
        soup    = BeautifulSoup(html, "html.parser")
        content = (
            soup.find("article") or
            soup.find("main") or
            soup.find("div", class_=re.compile(r"content|entry|post", re.I))
        )
        text = content.get_text(" ", strip=True) if content else soup.get_text(" ", strip=True)
    except ImportError:
        # Ingen BeautifulSoup — rensa taggar med regex
        text = re.sub(r"<[^>]+>", " ", html)

    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Phase 3: YouTube-kanal
# ---------------------------------------------------------------------------

def run_youtube(indexed_set: set, max_videos: Optional[int] = None) -> dict:
    """Phase 3: Hämtar auto-captions från officiell YouTube-kanal."""
    import yt_dlp

    CHANNEL_URL = "https://www.youtube.com/@BasharChanneledbyDarrylAnka/videos"
    logger.info("Hämtar YouTube-videolista...")

    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)

    videos = (info or {}).get("entries", [])
    if max_videos:
        videos = videos[:max_videos]

    logger.info("Hittade %d YouTube-videor", len(videos))
    CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)

    counts = {"indexed": 0, "skipped": 0, "failed": 0, "chunks": 0}

    for video in videos:
        vid_id = video.get("id", "")
        title  = video.get("title", vid_id)
        url    = f"https://www.youtube.com/watch?v={vid_id}"

        upload_date = str(video.get("upload_date", "") or "")
        if len(upload_date) == 8:
            session_date  = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
            category_year = int(upload_date[:4])
        else:
            session_date  = "1970-01-01"
            category_year = 0

        if already_indexed(title, session_date, indexed_set):
            log_skip("already_indexed", title)
            counts["skipped"] += 1
            continue

        # Försök 1: youtube-transcript-api (snabbare, ingen ffmpeg)
        segments = _fetch_yt_transcript_api(vid_id)

        # Försök 2: yt-dlp VTT (samma mönster som caption_fetcher.py)
        if not segments:
            segments = _fetch_yt_captions_ytdlp(vid_id, url)

        if not segments:
            log_error("no_transcript", title)
            counts["failed"] += 1
            continue

        base_payload = {
            "source":             "bashar_darryl_anka",
            "source_type":        "youtube_transcript",
            "session_title":      title,
            "session_date":       session_date,
            "category_year":      category_year,
            "duration_seconds":   int(video.get("duration", 0) or 0),
            "url":                url,
            "entity":             "Bashar",
            "channeler":          "Darryl Anka",
            "platform":           "YouTube",
            "access_tier":        "public",
            "copyright":          COPYRIGHT,
            "research_domain":    "consciousness",
            "methodological_box": "channeling_entity",
            "tags":               ["youtube", "bashar", "channeling"],
        }

        chunks = chunk_segments(segments)
        if not chunks:
            chunks = chunk_text(" ".join(s.get("text", "") for s in segments))

        try:
            n = upsert_chunks(chunks, base_payload)
            mark_indexed(title, session_date, indexed_set)
            counts["indexed"] += 1
            counts["chunks"]  += n
            logger.info("YouTube OK: %s → %d chunks", title[:60], n)
        except Exception as e:
            logger.error("Upsert misslyckades: %s | %s", title, e)
            log_error("upsert_failed", title)
            counts["failed"] += 1

    return counts


def _fetch_yt_transcript_api(vid_id: str) -> list[dict]:
    """Hämtar transkript via youtube-transcript-api (1.2.4 installerat)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        raw = YouTubeTranscriptApi.get_transcript(vid_id, languages=["en", "en-US"])
        return [
            {
                "start": t["start"],
                "end":   t["start"] + t.get("duration", 5.0),
                "text":  t["text"],
            }
            for t in raw
        ]
    except Exception as e:
        logger.debug("youtube-transcript-api misslyckades för %s: %s", vid_id, e)
        return []


def _fetch_yt_captions_ytdlp(vid_id: str, url: str) -> list[dict]:
    """Fallback: laddar ned VTT-captions via yt-dlp (mönster från caption_fetcher.py)."""
    import yt_dlp

    out_stem = str(CAPTIONS_DIR / vid_id)
    ydl_opts = {
        "skip_download":     True,
        "writeautomaticsub": True,
        "subtitlesformat":   "vtt",
        "subtitleslangs":    ["en", "en-US", "en-GB", "en-orig"],
        "outtmpl":           out_stem,
        "quiet":             True,
        "no_warnings":       True,
        "noprogress":        True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        logger.debug("yt-dlp VTT misslyckades för %s: %s", vid_id, e)
        return []

    vtt_files = list(CAPTIONS_DIR.glob(f"{vid_id}*.vtt"))
    if not vtt_files:
        return []

    return _parse_vtt(vtt_files[0].read_text(encoding="utf-8"))


def _parse_vtt(vtt: str) -> list[dict]:
    """Parsar WebVTT-innehåll till segment-lista. Slår ihop 30-sekunders fönster."""
    raw: list[dict] = []
    for line in vtt.splitlines():
        if "-->" not in line:
            continue
        parts = line.split("-->")
        if len(parts) != 2:
            continue
        start = _vtt_ts(parts[0].strip().split()[-1])
        end   = _vtt_ts(parts[1].strip().split()[0])
        raw.append({"start": start, "end": end, "text": ""})

    # Nästa icke-tomma rad efter tidsstämpeln är texten
    lines = vtt.splitlines()
    j = 0
    raw_idx = 0
    while j < len(lines) and raw_idx < len(raw):
        if "-->" in lines[j]:
            j += 1
            texts = []
            while j < len(lines) and lines[j].strip():
                clean = re.sub(r"<[^>]+>", "", lines[j]).strip()
                if clean:
                    texts.append(clean)
                j += 1
            if texts:
                raw[raw_idx]["text"] = " ".join(texts)
            raw_idx += 1
        else:
            j += 1

    return [s for s in raw if s["text"]]


def _vtt_ts(t: str) -> float:
    """HH:MM:SS.mmm eller MM:SS.mmm → sekunder."""
    parts = t.replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Phase 1: BasharTV — katalogkartläggning (Uscreen API)
# ---------------------------------------------------------------------------

def _load_session_cookies(cookie_path: Path) -> requests.Session:
    """Laddar Netscape-cookies → requests.Session."""
    jar = http.cookiejar.MozillaCookieJar()
    jar.load(str(cookie_path), ignore_discard=True, ignore_expires=True)
    sess = requests.Session()
    sess.cookies = jar
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept":     "application/json, text/html",
        "Referer":    "https://tv.bashar.org/",
    })
    return sess


def run_catalog(cookie_path: Path) -> list[dict]:
    """Phase 1: Hämtar sessionskatalog via Uscreen API → bashar_session_index.json."""
    rsess = _load_session_cookies(cookie_path)

    # Steg 1 — initial_categories
    logger.info("Uscreen: hämtar kategorier...")
    resp = rsess.get(
        f"{USCREEN_API}/catalog/initial_categories",
        params={
            "ai_recommendations":  "false",
            "continue_watching":   "true",
            "featured_category_id": "218633",
            "my_library":          "true",
            "preview":             "false",
            "user":                "true",
        },
        timeout=30,
    )
    resp.raise_for_status()
    cat_data = resp.json()

    # Steg 2 — filters (hämtas men används bara för loggning)
    try:
        rsess.get(f"{USCREEN_API}/catalog/filters", params={"preview": "false"}, timeout=30)
    except Exception:
        pass

    # Steg 3 — per år-kategori
    featured = (
        cat_data.get("featured_categories") or
        cat_data.get("categories") or
        []
    )
    logger.info("Hittade %d featured_categories", len(featured))

    all_sessions: list[dict] = []
    seen_ids: set = set()

    for cat in featured:
        cat_id   = cat.get("id")
        cat_name = cat.get("name", "")
        if not cat_id:
            continue

        try:
            r = rsess.get(
                f"{USCREEN_API}/catalog/featured_categories",
                params={"featured_category_id": cat_id, "preview": "false"},
                timeout=30,
            )
            r.raise_for_status()
            cdata = r.json()
        except Exception as e:
            logger.warning("Kategori %s (%s) misslyckades: %s", cat_id, cat_name, e)
            continue

        # Uscreen returnerar content/videos/items beroende på version
        items = (
            cdata.get("content") or
            cdata.get("videos") or
            cdata.get("items") or
            []
        )

        year_match = re.search(r"20\d{2}", cat_name)
        cat_year   = int(year_match.group()) if year_match else 0

        for item in items:
            sid   = str(item.get("id") or item.get("slug") or "")
            if not sid or sid in seen_ids:
                continue
            seen_ids.add(sid)

            slug     = item.get("slug") or item.get("permalink") or sid
            date_raw = item.get("published_at") or item.get("created_at") or ""

            all_sessions.append({
                "session_id":    sid,
                "session_title": item.get("title") or item.get("name") or "",
                "session_date":  _norm_date(date_raw),
                "duration":      int(item.get("duration") or 0),
                "url":           f"https://tv.bashar.org/videos/{slug}",
                "category_year": cat_year,
                "category_name": cat_name,
                "category_id":   cat_id,
            })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSION_INDEX, "w", encoding="utf-8") as f:
        json.dump(all_sessions, f, ensure_ascii=False, indent=2)

    logger.info("Sessionslista sparad: %d sessioner → %s", len(all_sessions), SESSION_INDEX)
    return all_sessions


# ---------------------------------------------------------------------------
# Phase 2: BasharTV — per-session download + transkription
# ---------------------------------------------------------------------------

def run_bashtartv_sessions(
    cookie_path: Path,
    sessions: list[dict],
    indexed_set: set,
    max_sessions: Optional[int] = None,
) -> dict:
    """Phase 2: Laddar ned, transkriberar och indexerar BasharTV-sessioner."""
    import yt_dlp

    if max_sessions:
        sessions = sessions[:max_sessions]

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    rsess = _load_session_cookies(cookie_path)

    # Whisper — cachas i process
    _whisper_cache: dict = {}

    def get_whisper():
        if "model" not in _whisper_cache:
            from faster_whisper import WhisperModel
            logger.info("Laddar Whisper %s (CUDA/int8)...", WHISPER_MODEL)
            _whisper_cache["model"] = WhisperModel(
                WHISPER_MODEL, device="cuda", compute_type="int8"
            )
        return _whisper_cache["model"]

    counts = {"indexed": 0, "skipped": 0, "failed": 0, "shownotes_chunks": 0, "transcript_chunks": 0}

    for sess in sessions:
        title  = sess["session_title"]
        sdate  = sess["session_date"]
        url    = sess["url"]
        sid    = sess["session_id"]

        if not title:
            continue

        if already_indexed(title, sdate, indexed_set):
            log_skip("already_indexed", title)
            counts["skipped"] += 1
            continue

        logger.info("─── %s (%s)", title, sdate)

        base_payload = {
            "source":             "bashar_darryl_anka",
            "session_title":      title,
            "session_date":       sdate,
            "category_year":      sess.get("category_year", 0),
            "duration_seconds":   sess.get("duration", 0),
            "url":                url,
            "entity":             "Bashar",
            "channeler":          "Darryl Anka",
            "platform":           "BasharTV / Uscreen",
            "copyright":          COPYRIGHT,
            "research_domain":    "consciousness",
            "methodological_box": "channeling_entity",
            "tags":               ["bashtartv", "bashar", "channeling"],
        }

        # ── Show notes / Q&A-metadata ─────────────────────────────────────
        try:
            rpage = rsess.get(url, timeout=30)
            if rpage.ok:
                sn_chunks = _extract_shownotes(rpage.text)
                if sn_chunks:
                    sn_payload = {**base_payload, "source_type": "bashtartv_shownotes"}
                    n = upsert_chunks(sn_chunks, sn_payload)
                    counts["shownotes_chunks"] += n
                    logger.info("  Show notes: %d chunks", n)
        except Exception as e:
            logger.debug("Show notes misslyckades: %s", e)

        # ── Audio-nedladdning ─────────────────────────────────────────────
        audio_path = AUDIO_DIR / f"{sid}.mp3"

        if not audio_path.exists():
            ydl_opts = {
                "format":      "bestaudio/best",
                "postprocessors": [{
                    "key":              "FFmpegExtractAudio",
                    "preferredcodec":   "mp3",
                    "preferredquality": "5",
                }],
                "outtmpl":     str(audio_path.with_suffix("")),
                "cookiefile":  str(cookie_path),  # cookie-auth — nytt jämfört med vigil-pipelinen
                "noplaylist":  True,
                "quiet":       True,
                "no_warnings": True,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                logger.info("  Nedladdad: %s", audio_path.name)
            except Exception as e:
                logger.warning("  yt-dlp misslyckades: %s — hoppar transkription", e)
                log_error("download_failed", f"{title} | {e}")
                # Kreditera som indexerad om vi ändå fick show notes
                if counts["shownotes_chunks"] > 0:
                    mark_indexed(title, sdate, indexed_set)
                else:
                    counts["failed"] += 1
                continue

        if not audio_path.exists():
            logger.warning("  Audiofil saknas: %s", audio_path.name)
            counts["failed"] += 1
            continue

        # ── Transkription ──────────────────────────────────────────────────
        try:
            model = get_whisper()
            raw_segs, info = model.transcribe(str(audio_path), beam_size=5, language=None)
            segments = [{"start": s.start, "end": s.end, "text": s.text} for s in raw_segs]
            logger.info("  Transkriberat: %d segment, språk=%s", len(segments), info.language)
        except Exception as e:
            logger.error("  Transkription misslyckades: %s", e)
            log_error("transcribe_failed", f"{title} | {e}")
            counts["failed"] += 1
            continue

        # ── Chunkning + upsert ────────────────────────────────────────────
        chunks = chunk_segments(segments)
        if not chunks:
            chunks = chunk_text(" ".join(s["text"] for s in segments))

        try:
            tr_payload = {**base_payload, "source_type": "bashtartv_transcript"}
            n = upsert_chunks(chunks, tr_payload)
            mark_indexed(title, sdate, indexed_set)
            counts["indexed"]          += 1
            counts["transcript_chunks"] += n
            logger.info("  ✓ %d chunks indexerade", n)
        except Exception as e:
            logger.error("  Upsert misslyckades: %s", e)
            log_error("upsert_failed", title)
            counts["failed"] += 1

    return counts


def _extract_shownotes(html: str) -> list[dict]:
    """Extraherar Q&A-lista ur sessionsida. Returnerar chunk-lista."""
    text = _extract_main_text(html)

    # Försök hitta Q&A-items: rader med - / Q: / • / numrering
    lines = text.splitlines() if "\n" in text else re.split(r"(?<=[.?!])\s+", text)
    qa_items = [
        l.strip() for l in lines
        if l.strip() and (
            l.strip().startswith(("-", "Q:", "•", "–", "—")) or
            re.match(r"^\d+[\.\)]", l.strip())
        )
    ]

    if qa_items:
        return chunk_qa_list(qa_items)
    # Ingen tydlig Q&A-struktur — returnera tom lista (hoppa show notes)
    return []


# ---------------------------------------------------------------------------
# Phase 4: Böcker
# ---------------------------------------------------------------------------

def run_book(pdf_path: Path, title: str, year: int, indexed_set: set) -> dict:
    """Phase 4: Indexerar manuellt anskaffad bok (PDF)."""
    sdate = f"{year}-01-01"

    if already_indexed(title, sdate, indexed_set):
        log_skip("already_indexed", title)
        return {"book_chunks": 0, "skipped": 1}

    # PDF-extrahering — försök PyMuPDF, fallback till ren text
    try:
        import fitz
        doc       = fitz.open(str(pdf_path))
        full_text = "\n".join(page.get_text() for page in doc)
        doc.close()
    except ImportError:
        full_text = pdf_path.read_text(encoding="utf-8", errors="replace")

    if len(full_text.strip()) < 500:
        raise ValueError(f"PDF verkar tom ({len(full_text)} tecken)")

    base_payload = {
        "source":             "bashar_darryl_anka",
        "source_type":        "book",
        "session_title":      title,
        "session_date":       sdate,
        "category_year":      year,
        "duration_seconds":   0,
        "url":                "",
        "entity":             "Bashar",
        "channeler":          "Darryl Anka",
        "platform":           "Book",
        "copyright":          COPYRIGHT,
        "research_domain":    "consciousness",
        "methodological_box": "channeling_entity",
        "tags":               ["book", "bashar", "darryl_anka"],
    }

    chunks = chunk_text(full_text)
    n      = upsert_chunks(chunks, base_payload)
    mark_indexed(title, sdate, indexed_set)
    logger.info("Bok indexerad: %s → %d chunks", title, n)
    return {"book_chunks": n, "skipped": 0}


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _norm_date(s: str) -> str:
    """Normaliserar datum till YYYY-MM-DD."""
    if not s:
        return "1970-01-01"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return "1970-01-01"


def print_summary(all_counts: dict):
    print("\n=== Bashar Ingest Summary ===")
    print(f"Kollektion : {COLLECTION}")
    for phase, counts in all_counts.items():
        print(f"\n  [{phase}]")
        if isinstance(counts, dict):
            for k, v in counts.items():
                print(f"    {k}: {v}")
        else:
            print(f"    {counts}")
    print(f"\nSessionslista : {SESSION_INDEX}")
    print(f"Dedup-register: {INDEXED_SET}")
    print(f"Log           : {INGEST_LOG}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Bashar/Darryl Anka RAG Corpus Ingest → vigil_bashar",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Rekommenderad körordning:
  1. python bashar_ingest.py --setup
  2. python bashar_ingest.py --batgap
  3. python bashar_ingest.py --youtube [--max 20]
  4. python bashar_ingest.py --bashtartv --catalog --cookies data/bashar_cookies.json
  5. python bashar_ingest.py --bashtartv --cookies data/bashar_cookies.json [--max 10]
  6. python bashar_ingest.py --book /path/to/book.pdf --title "..." --year 1987

Cookie-export (Chrome → Netscape-format):
  Installera tillägget "Get cookies.txt LOCALLY" och exportera för tv.bashar.org
  Scp till servern:
    scp bashar_cookies.json clioadmin@100.107.127.104:~/19.0/clio-tools/clio-vigil/data/
        """,
    )
    parser.add_argument("--setup",    action="store_true",
                        help="Phase 0: Skapa kollektion + payload-index")
    parser.add_argument("--batgap",   action="store_true",
                        help="Phase 5: Indexera BATGAP-intervju (fritt)")
    parser.add_argument("--youtube",  action="store_true",
                        help="Phase 3: Indexera YouTube-kanal (fritt)")
    parser.add_argument("--bashtartv", action="store_true",
                        help="Phase 1+2: BasharTV via Uscreen API (kräver --cookies)")
    parser.add_argument("--catalog",  action="store_true",
                        help="Med --bashtartv: bygg bara katalog, transkribera inte")
    parser.add_argument("--cookies",  type=Path,
                        default=DATA_DIR / "bashar_cookies.json",
                        help="Netscape cookie-fil för tv.bashar.org")
    parser.add_argument("--book",     type=Path,
                        help="Phase 4: PDF/epub att indexera")
    parser.add_argument("--title",    type=str,  help="Boktitel (krävs med --book)")
    parser.add_argument("--year",     type=int,  help="Publiceringsår (krävs med --book)")
    parser.add_argument("--max",      type=int,
                        help="Max antal sessioner/videos att bearbeta per körning")
    args = parser.parse_args()

    ran_something = False
    all_counts: dict = {}

    # Ladda dedup-register
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    indexed_set = _load_indexed_set()

    if args.setup:
        ran_something = True
        setup_collection()

    if args.batgap:
        ran_something = True
        try:
            all_counts["batgap"] = run_batgap(indexed_set)
        except Exception as e:
            logger.error("BATGAP misslyckades: %s", e)
            all_counts["batgap"] = {"error": str(e)}
        _save_indexed_set(indexed_set)

    if args.youtube:
        ran_something = True
        try:
            all_counts["youtube"] = run_youtube(indexed_set, max_videos=args.max)
        except Exception as e:
            logger.error("YouTube misslyckades: %s", e)
            all_counts["youtube"] = {"error": str(e)}
        _save_indexed_set(indexed_set)

    if args.bashtartv:
        ran_something = True
        if not args.cookies.exists():
            print(f"\n✗ Cookie-fil saknas: {args.cookies}", file=sys.stderr)
            print("  Exportera cookies från Chrome (tillägg: Get cookies.txt LOCALLY)", file=sys.stderr)
            print(f"  scp bashar_cookies.json clioadmin@100.107.127.104:~/19.0/clio-tools/clio-vigil/data/", file=sys.stderr)
            sys.exit(1)

        if args.catalog:
            sessions = run_catalog(args.cookies)
            print(f"\n✓ Katalog: {len(sessions)} sessioner → {SESSION_INDEX}")
        else:
            # Läs befintligt index om det finns, annars bygg katalog
            if SESSION_INDEX.exists():
                with open(SESSION_INDEX, encoding="utf-8") as f:
                    sessions = json.load(f)
                logger.info("Läser befintlig sessionslista: %d sessioner", len(sessions))
            else:
                sessions = run_catalog(args.cookies)

            try:
                all_counts["bashtartv"] = run_bashtartv_sessions(
                    args.cookies, sessions, indexed_set, max_sessions=args.max
                )
            except Exception as e:
                logger.error("BasharTV sessioner misslyckades: %s", e)
                all_counts["bashtartv"] = {"error": str(e)}
            _save_indexed_set(indexed_set)

    if args.book:
        ran_something = True
        if not args.title or not args.year:
            print("✗ --title och --year krävs med --book", file=sys.stderr)
            sys.exit(1)
        if not args.book.exists():
            print(f"✗ Filen finns inte: {args.book}", file=sys.stderr)
            sys.exit(1)
        try:
            all_counts["book"] = run_book(args.book, args.title, args.year, indexed_set)
        except Exception as e:
            logger.error("Bok-ingest misslyckades: %s", e)
            all_counts["book"] = {"error": str(e)}
        _save_indexed_set(indexed_set)

    if not ran_something:
        parser.print_help()
        return

    if all_counts:
        print_summary(all_counts)


if __name__ == "__main__":
    main()
