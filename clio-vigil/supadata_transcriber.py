"""
supadata_transcriber.py
========================
Hämtar transkript för YouTube-items via Supadata (synkront, billigt).
On-demand mp3-transkription (kostar credits) är avsiktligt avskiljd
till --backlog-läget och ska INTE köras löpande.

Löpande pipeline (bara YouTube-fetch):
  python supadata_transcriber.py [--domain ufo] [--max 50]

Engångskörning för mp3-backlogg (on-demand, kostar credits):
  python supadata_transcriber.py --backlog [--domain ufo] [--max 100]
  python supadata_transcriber.py --backlog --item 7986

Pipeline-integration (anropas från main.py --transcribe):
  from supadata_transcriber import run_supadata_queue
  counts = run_supadata_queue(conn, domain=..., max_items=...)
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from dotenv import load_dotenv

# ── Ladda .env ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env", override=False)

# ── Konfig ───────────────────────────────────────────────────────────────────
SUPADATA_API_KEY   = os.getenv("SUPADATA_API_KEY", "")
SUPADATA_YT        = "https://api.supadata.ai/v1/youtube/transcript"
SUPADATA_SUBMIT    = "https://api.supadata.ai/v1/transcript"          # on-demand, kostar credits
SUPADATA_POLL      = "https://api.supadata.ai/v1/transcript/{job_id}" # on-demand polling

DATA_DIR           = BASE_DIR / "data"
TRANSCRIPTS_DIR    = DATA_DIR / "transcripts"
DB_PATH            = DATA_DIR / "vigil.db"

POLL_INTERVAL      = 15      # sekunder mellan poll-anrop (on-demand)
POLL_MAX_TRIES     = 60      # max ~15 min per item
SLEEP_BETWEEN      = 1.0     # sekunder mellan items

AUDIO_EXTENSIONS   = {".mp3", ".m4a", ".ogg", ".aac", ".wav", ".flac", ".opus"}

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "supadata_transcriber.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("supadata_transcriber")


# ── DB-hjälpare ──────────────────────────────────────────────────────────────
def get_conn():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_youtube_items(conn, domain, max_items):
    """Köade YouTube-items att hämta transkript för."""
    domain_clause = "AND domain=?" if domain else ""
    params = ([domain] if domain else []) + [max_items]
    return conn.execute(
        f"""SELECT * FROM vigil_items
            WHERE state='queued' AND source_type='youtube'
            {domain_clause}
            ORDER BY priority_score DESC LIMIT ?""",
        params,
    ).fetchall()


def fetch_rss_items(conn, domain, max_items, item_id=None):
    """Köade RSS-items med audio-enclosure (för --backlog)."""
    if item_id:
        return conn.execute(
            "SELECT * FROM vigil_items WHERE id=? AND source_type='rss'",
            (item_id,),
        ).fetchall()
    domain_clause = "AND domain=?" if domain else ""
    params = ([domain] if domain else []) + [max_items]
    return conn.execute(
        f"""SELECT * FROM vigil_items
            WHERE state='queued' AND source_type='rss'
            {domain_clause}
            ORDER BY priority_score DESC LIMIT ?""",
        params,
    ).fetchall()


def mark_transcribed(conn, item_id, transcript_path, dry_run=False):
    if dry_run:
        return
    conn.execute(
        """UPDATE vigil_items
           SET state='transcribed', transcript_path=?, state_updated_at=datetime('now')
           WHERE id=?""",
        (transcript_path, item_id),
    )
    conn.commit()


def mark_error(conn, item_id, msg, dry_run=False):
    if dry_run:
        return
    conn.execute(
        """UPDATE vigil_items
           SET state='queued', error_message=?, state_updated_at=datetime('now')
           WHERE id=?""",
        (msg[:500], item_id),
    )
    conn.commit()


# ── Gemensamma hjälpare ───────────────────────────────────────────────────────
def _headers():
    return {"x-api-key": SUPADATA_API_KEY}


def save_transcript(item_id, text):
    """Spara transkript som .txt och .json (Whisper-kompatibelt format)."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = TRANSCRIPTS_DIR / f"vigil_{item_id}"
    stem.with_suffix(".txt").write_text(text, encoding="utf-8")
    data = [{"start": 0.0, "end": 0.0, "text": text}]
    stem.with_suffix(".json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(stem.with_suffix(".json"))


# ── YouTube-fetch (löpande drift) ─────────────────────────────────────────────
def extract_video_id(url):
    """Extrahera videoId ur youtube.com/watch?v=... eller youtu.be/..."""
    if not url:
        return None
    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc:
        qs = parse_qs(parsed.query)
        return qs.get("v", [None])[0]
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/").split("/")[0] or None
    return None


MAX_RATE_LIMIT_RETRIES = 5  # max antal 429-retries innan vi ger upp


def fetch_youtube_transcript(video_id, _rl_attempt=1):
    """
    Hämta YouTube-transkript från Supadata (synkront, billigt).
    Returnerar text eller None om ej tillgängligt.
    """
    try:
        resp = requests.get(
            SUPADATA_YT,
            params={"videoId": video_id, "text": "true"},
            headers=_headers(),
            timeout=30,
        )
    except requests.Timeout:
        log.warning("  YouTube-fetch timeout")
        return None

    if resp.status_code == 404:
        log.info("  Inget YouTube-transkript tillgängligt (404)")
        return None
    if resp.status_code == 429:
        if _rl_attempt >= MAX_RATE_LIMIT_RETRIES:
            log.error(f"  Rate limit efter {_rl_attempt} försök — ger upp")
            return None
        log.warning(f"  Rate limit (försök {_rl_attempt}/{MAX_RATE_LIMIT_RETRIES}) — väntar 60s")
        time.sleep(60)
        return fetch_youtube_transcript(video_id, _rl_attempt + 1)
    if resp.status_code != 200:
        log.warning(f"  YouTube-fetch HTTP {resp.status_code}: {resp.text[:120]}")
        return None

    data = resp.json()
    content = data.get("content", "")
    if not content:
        return None
    if isinstance(content, str):
        return content
    return " ".join(c.get("text", "") for c in content if c.get("text"))


def process_youtube_item(conn, item, dry_run=False):
    item_id = item["id"]
    title   = (item["title"] or "")[:60]
    url     = item["url"] or ""

    log.info(f"[{item_id}] YouTube — {title!r}")

    video_id = extract_video_id(url)
    if not video_id:
        log.info("  Kunde inte extrahera videoId — hoppar")
        return "no_video_id"

    log.info(f"  videoId: {video_id}")

    if dry_run:
        log.info("  [DRY-RUN]")
        return "dry_run"

    text = fetch_youtube_transcript(video_id)
    if not text:
        log.info("  Inget transkript — faller tillbaka på Whisper")
        return "no_transcript"

    log.info(f"  Transkript: {len(text):,} tecken")
    path = save_transcript(item_id, text)
    mark_transcribed(conn, item_id, path)
    log.info(f"  [OK] → {path}")
    return "ok"


# ── On-demand mp3 (--backlog, engångskörning) ─────────────────────────────────
def extract_audio_url(item):
    """Hämta audio-URL ur raw_metadata eller item.url."""
    meta = {}
    if item["raw_metadata"]:
        try:
            meta = json.loads(item["raw_metadata"])
        except json.JSONDecodeError:
            pass

    url = meta.get("enclosure_url") or meta.get("enclosure") or ""
    if url and not isinstance(url, dict):
        path = urlparse(str(url)).path.lower()
        if any(path.endswith(ext) for ext in AUDIO_EXTENSIONS):
            return str(url)

    # Fallback: item.url om det är en ljudfil
    item_url = item["url"] or ""
    path = urlparse(item_url).path.lower()
    if any(path.endswith(ext) for ext in AUDIO_EXTENSIONS):
        return item_url

    return None


def _extract_content(data):
    content = data.get("content", "")
    if not content:
        return None
    if isinstance(content, str):
        return content
    return " ".join(c.get("text", "") for c in content if c.get("text"))


def _poll_job(job_id):
    url = SUPADATA_POLL.format(job_id=job_id)
    for attempt in range(1, POLL_MAX_TRIES + 1):
        resp = requests.get(url, headers=_headers(), timeout=30)
        if resp.status_code == 404:
            log.warning(f"  [POLL] {job_id} — 404")
            return None
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "unknown")
        if status == "completed":
            return _extract_content(data)
        if status in ("failed", "error"):
            log.warning(f"  [POLL] {job_id} — status={status}")
            return None
        log.info(f"  [POLL #{attempt}] status={status} — väntar {POLL_INTERVAL}s")
        time.sleep(POLL_INTERVAL)
    log.warning(f"  [POLL] Timeout efter {POLL_MAX_TRIES} försök")
    return None


def fetch_transcript_audio(audio_url, attempt=1):
    """On-demand transkription via Supadata (kostar credits)."""
    try:
        resp = requests.get(
            SUPADATA_SUBMIT,
            params={"url": audio_url, "text": "true"},
            headers=_headers(),
            timeout=90,
        )
    except requests.Timeout:
        if attempt < 3:
            log.warning(f"  Submit timeout (försök {attempt}) — retry om 10s")
            time.sleep(10)
            return fetch_transcript_audio(audio_url, attempt + 1)
        log.error("  Submit timeout efter 3 försök")
        return None

    if resp.status_code == 429:
        if attempt >= MAX_RATE_LIMIT_RETRIES:
            log.error(f"  Rate limit efter {attempt} försök — ger upp")
            return None
        log.warning(f"  Rate limit (försök {attempt}/{MAX_RATE_LIMIT_RETRIES}) — väntar 60s")
        time.sleep(60)
        return fetch_transcript_audio(audio_url, attempt + 1)
    if resp.status_code not in (200, 202):
        log.error(f"  HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    data = resp.json()
    if "content" in data:
        text = _extract_content(data)
        log.info(f"  Synkront svar ({len(text or ''):,} tecken)")
        return text
    job_id = data.get("jobId")
    if not job_id:
        log.error(f"  Inget content eller jobId: {data}")
        return None
    log.info(f"  jobId: {job_id}")
    return _poll_job(job_id)


def process_backlog_item(conn, item, dry_run=False):
    """On-demand mp3-transkription (--backlog, kostar credits)."""
    item_id = item["id"]
    title   = (item["title"] or "")[:60]

    log.info(f"[{item_id}] BACKLOG — {title!r}")

    audio_url = extract_audio_url(item)
    if not audio_url:
        log.info("  Ingen audio-URL — hoppar")
        return "no_audio"

    log.info(f"  Audio: {audio_url[:80]}")

    if dry_run:
        log.info("  [DRY-RUN]")
        return "dry_run"

    try:
        text = fetch_transcript_audio(audio_url)
    except Exception as exc:
        log.error(f"  Fel: {exc}")
        mark_error(conn, item_id, str(exc))
        return "error"

    if not text:
        mark_error(conn, item_id, "Supadata returnerade inget transkript")
        return "failed"

    log.info(f"  Transkript: {len(text):,} tecken")
    path = save_transcript(item_id, text)
    mark_transcribed(conn, item_id, path)
    log.info(f"  [OK] → {path}")
    return "ok"


# ── Pipeline-integration (anropas från main.py --transcribe) ──────────────────
def run_supadata_queue(conn, domain=None, max_items=50):
    """
    Hämtar YouTube-transkript för köade youtube-items.
    Tyst no-op om SUPADATA_API_KEY saknas.
    On-demand mp3-transkription ingår INTE — det är --backlog.
    Returnerar dict: transcribed, no_transcript, error.
    """
    if not SUPADATA_API_KEY:
        log.debug("SUPADATA_API_KEY saknas — hoppar Supadata-steg")
        return {"transcribed": 0, "no_transcript": 0, "error": 0}

    items = fetch_youtube_items(conn, domain, max_items)
    if not items:
        return {"transcribed": 0, "no_transcript": 0, "error": 0}

    log.info("Supadata YouTube-fetch — %d items (max %d)", len(items), max_items)
    result = {"transcribed": 0, "no_transcript": 0, "error": 0}

    for item in items:
        status = process_youtube_item(conn, item)
        if status == "ok":
            result["transcribed"] += 1
        elif status in ("no_transcript", "no_video_id"):
            result["no_transcript"] += 1
        else:
            result["error"] += 1
        time.sleep(SLEEP_BETWEEN)

    log.info(
        "Supadata klar: %d hämtade, %d ej tillgängliga, %d fel",
        result["transcribed"], result["no_transcript"], result["error"],
    )
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Supadata — YouTube-fetch (standard) eller mp3-backlogg (--backlog)"
    )
    parser.add_argument("--backlog",  action="store_true", help="On-demand mp3-transkription (kostar credits)")
    parser.add_argument("--max",      type=int, default=50,  help="Max antal items")
    parser.add_argument("--domain",   type=str, default="",  help="Domän (ufo/ai)")
    parser.add_argument("--item",     type=int, default=0,   help="Specifikt item-id (bara --backlog)")
    parser.add_argument("--dry-run",  action="store_true",   help="Simulera, ändra inget")
    args = parser.parse_args()

    if not SUPADATA_API_KEY:
        log.error("SUPADATA_API_KEY saknas i .env")
        sys.exit(1)

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    conn   = get_conn()
    domain = args.domain or None

    if args.backlog:
        items = fetch_rss_items(conn, domain, args.max, args.item or None)
        log.info("=== BACKLOG — %d mp3-items (on-demand, kostar credits) ===", len(items))
        stats = {"ok": 0, "no_audio": 0, "failed": 0, "error": 0, "dry_run": 0}
        for item in items:
            status = process_backlog_item(conn, item, args.dry_run)
            stats[status] = stats.get(status, 0) + 1
            time.sleep(SLEEP_BETWEEN)
    else:
        items = fetch_youtube_items(conn, domain, args.max)
        log.info("=== YouTube-fetch — %d items ===", len(items))
        stats = {"ok": 0, "no_transcript": 0, "no_video_id": 0, "error": 0, "dry_run": 0}
        for item in items:
            status = process_youtube_item(conn, item, args.dry_run)
            stats[status] = stats.get(status, 0) + 1
            time.sleep(SLEEP_BETWEEN)

    conn.close()
    log.info("Klart: %s", stats)


if __name__ == "__main__":
    main()
