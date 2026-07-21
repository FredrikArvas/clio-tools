"""
clio-vigil — downloader.py
===========================
Laddar ned audio för köade bevakningsobjekt till persistent lagring.

Flöde:
  queued (med audio) → download_audio() → downloaded (audio_path satt)
  queued (bild-URL)  → ocr_image()      → transcribed (direkt, utan whisper)

Ordning: nyaste published_at först (senast publicerat = mest relevant).
Text-only RSS (ingen enclosure_url) hoppas över — hanteras av transcriber.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from ocr import is_image_file, ocr_image, write_image_transcript
from orchestrator import init_db, transition

logger = logging.getLogger(__name__)

AUDIO_DIR = Path("/mnt/wde2/clio-vigil-audio")


# ---------------------------------------------------------------------------
# Filnamn
# ---------------------------------------------------------------------------

def _make_slug(text: str, max_len: int = 20) -> str:
    text = text.lower()
    for a, b in [("å","a"),("ä","a"),("ö","o"),("é","e"),("ü","u"),("ñ","n")]:
        text = text.replace(a, b)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:max_len].rstrip("-")


def _audio_filename(item) -> str:
    source = item["source_name"] or "okand"
    slug   = _make_slug(source)
    date   = (item["published_at"] or "")[:10].replace("-", "") or "nodatum"
    return f"{slug}_{item['id']}_{date}.mp3"


# ---------------------------------------------------------------------------
# Nedladdning
# ---------------------------------------------------------------------------

def _download_youtube(url: str, output_path: Path) -> bool:
    try:
        import yt_dlp
    except ImportError:
        raise ImportError("yt-dlp saknas")

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "5"}],
        "outtmpl": str(output_path.with_suffix("")),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        logger.error(f"yt-dlp fel: {e}")
        return False
    return output_path.exists() and output_path.stat().st_size > 0


def _download_url(url: str, output_path: Path) -> bool:
    try:
        import requests
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception as e:
        logger.error(f"Nedladdningsfel ({url[:60]}): {e}")
        return False


def _has_audio(item) -> bool:
    """Returnerar True om item har nedladdningsbar audio (inte text-only RSS)."""
    if item["source_type"] == "youtube":
        return True
    if item["source_type"] == "rss":
        raw = json.loads(item["raw_metadata"] or "{}")
        return bool(raw.get("enclosure_url"))
    return False


def download_item(conn, item_id: int) -> bool:
    """
    Laddar ned audio för ett enskilt item.
    Returnerar True om lyckad nedladdning.
    """
    item = conn.execute(
        "SELECT * FROM vigil_items WHERE id = ?", (item_id,)
    ).fetchone()
    if not item:
        logger.error(f"Item {item_id} finns inte")
        return False

    if not _has_audio(item):
        logger.info(f"Item {item_id} saknar audio — hoppas över")
        return False

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    output_path = AUDIO_DIR / _audio_filename(item)

    # Redan nedladdad (t.ex. avbruten körning)
    if output_path.exists() and output_path.stat().st_size > 100_000:
        logger.info(f"Redan nedladdad: {output_path.name}")
        transition(conn, item_id, "downloaded", audio_path=str(output_path))
        return True

    url          = item["url"]
    source_type  = item["source_type"]

    if source_type == "youtube":
        logger.info(f"[dl] YouTube → {output_path.name}")
        ok = _download_youtube(url, output_path)
    else:
        raw       = json.loads(item["raw_metadata"] or "{}")
        audio_url = raw["enclosure_url"]
        logger.info(f"[dl] RSS → {output_path.name}")
        ok = _download_url(audio_url, output_path)

    if not ok:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        logger.error(f"[dl] Misslyckades: item {item_id}")
        return False

    size_mb = output_path.stat().st_size / 1_048_576
    logger.info(f"[dl] Klar: {output_path.name} ({size_mb:.1f} MB)")

    # Kontrollera om filen är en bild — OCR:a direkt istället för whisper
    if is_image_file(output_path):
        logger.info(f"[dl] Bildfil detekterad ({output_path.name}) — OCR:ar med Claude Vision")
        title = item["title"] or ""
        ocr_text = ocr_image(output_path, item_id, title=title)
        if ocr_text:
            json_path, _ = write_image_transcript(item_id, ocr_text)
            transition(conn, item_id, "transcribed",
                       audio_path=str(output_path),
                       transcript_path=str(json_path))
            logger.info(f"[dl] OCR klar → transcribed: item {item_id}")
        else:
            logger.warning(f"[dl] OCR misslyckades för item {item_id} — filtrerar bort")
            output_path.unlink(missing_ok=True)
            transition(conn, item_id, "filtered_out")
        return bool(ocr_text)

    transition(conn, item_id, "downloaded", audio_path=str(output_path))
    return True


# ---------------------------------------------------------------------------
# Köprocessor
# ---------------------------------------------------------------------------

def run_downloader(conn, domain: Optional[str] = None, max_items: int = 1) -> dict:
    """
    Laddar ned audio för köade items, nyaste published_at först.
    Returnerar räknare: {downloaded, skipped, failed}.
    """
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}

    domain_clause = "AND domain = ?" if domain else ""
    params        = (domain, max_items) if domain else (max_items,)

    rows = conn.execute(
        f"""
        SELECT id FROM vigil_items
        WHERE state = 'queued'
          {domain_clause}
          AND (
              source_type = 'youtube'
              OR (source_type = 'rss'
                  AND json_extract(raw_metadata, '$.enclosure_url') IS NOT NULL
                  AND json_extract(raw_metadata, '$.enclosure_url') != '')
          )
        ORDER BY priority_score DESC, published_at DESC NULLS LAST
        LIMIT ?
        """,
        params,
    ).fetchall()

    if not rows:
        logger.info("[dl] Inga items med audio i kö")
        return counts

    for row in rows:
        ok = download_item(conn, row["id"])
        if ok:
            counts["downloaded"] += 1
        else:
            counts["failed"] += 1

    return counts
