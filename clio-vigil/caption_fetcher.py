"""
clio-vigil — caption_fetcher.py
=================================
Hämtar automatgenererade undertexter från YouTube-videos.

Sprint B — caption_check-fas i pipeline
  - Körs på YouTube-items i state=queued INNAN Whisper-kön
  - Om captions hittas → sparas som transkript, state → captioned
  - Om inga captions → state kvar som queued (Whisper körs som vanligt)

Transkriptformat: samma JSON-struktur som faster-whisper (segment-lista
med start/end/text) — kompatibelt med summarizer.py och indexer.py.

Körning:
  python caption_fetcher.py --run [--domain ufo] [--max 50]
  python caption_fetcher.py --item 42
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from orchestrator import init_db, transition

logger = logging.getLogger(__name__)

DATA_DIR        = Path(__file__).parent / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"

# Föredragna captionspråk (i prioritetsordning)
# YouTube levererar ofta "en" (US), "en-US" och "en-orig"
CAPTION_LANGS = ["en", "en-US", "en-GB", "en-orig", "sv", "sv-SE"]


# ---------------------------------------------------------------------------
# VTT-parsning
# ---------------------------------------------------------------------------

def _parse_vtt(vtt_text: str) -> list[dict]:
    """
    Parsar WebVTT-text till lista av segment-dict (start, end, text).
    Kompatibelt med Whisper-transkriptformat.

    Hanterar:
    - Standard WebVTT-block med cue-IDs
    - YouTube-specifika HTML-taggar (<c>, <b>, <00:00:01.234>)
    - Rubrik-rad "WEBVTT" och "NOTE"-block
    """
    segments = []
    lines = vtt_text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Hitta tidsstämpelrad: 00:00:01.234 --> 00:00:05.678 [...]
        if "-->" in line:
            m = re.match(
                r"(\d+):(\d+):(\d+)[.,](\d+)\s*-->\s*(\d+):(\d+):(\d+)[.,](\d+)",
                line,
            )
            if m:
                def _ts(h, mi, s, ms):
                    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000

                start = _ts(*m.group(1, 2, 3, 4))
                end   = _ts(*m.group(5, 6, 7, 8))

                # Samla textraderna efter tidsstämpeln
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    raw = lines[i]
                    # Strippa YouTube-interna tidsstämplar (<00:00:01.234>)
                    raw = re.sub(r"<\d+:\d+:\d+\.\d+>", "", raw)
                    # Strippa HTML-taggar (<c.color>, <b>, </c> etc.)
                    raw = re.sub(r"<[^>]+>", "", raw).strip()
                    if raw:
                        text_lines.append(raw)
                    i += 1

                text = " ".join(text_lines).strip()
                if text:
                    segments.append({
                        "start": round(start, 2),
                        "end":   round(end, 2),
                        "text":  text,
                    })
        i += 1

    return segments


def _merge_segments(segments: list[dict], window_sec: float = 30.0) -> list[dict]:
    """
    Slår ihop korta VTT-segment (~2 sek) till längre fönster (~30 sek).
    YouTube-captions är extremt fragmenterade — sammanfogning ger
    bättre RAG-chunks och minskar onödig precision.
    """
    if not segments:
        return []

    merged = []
    current = {**segments[0]}

    for seg in segments[1:]:
        if seg["start"] - current["start"] < window_sec:
            current["text"] += " " + seg["text"]
            current["end"] = seg["end"]
        else:
            merged.append(current)
            current = {**seg}

    merged.append(current)
    return merged


def _find_vtt_file(stem: Path, item_id: int) -> Optional[Path]:
    """
    Letar upp nedladdad VTT-fil. yt-dlp namnger dem:
    {stem}.{lang}.vtt  t.ex. vigil_42_caption.en.vtt
    """
    # Föredra konfigurerade språk
    for lang in CAPTION_LANGS:
        candidate = stem.parent / f"{stem.name}.{lang}.vtt"
        if candidate.exists():
            return candidate
    # Fallback: sök alla VTT-filer med rätt prefix
    for f in stem.parent.glob(f"{stem.name}*.vtt"):
        return f
    return None


# ---------------------------------------------------------------------------
# Huvud-funktion: hämta captions för ett item
# ---------------------------------------------------------------------------

def fetch_captions(item: dict) -> Optional[Path]:
    """
    Försöker ladda ned auto-captions för ett YouTube-item via yt-dlp.

    Returnerar sökväg till sparad transkript-JSON (Whisper-kompatibelt format),
    eller None om inga captions finns eller något gick fel.
    """
    try:
        import yt_dlp
    except ImportError:
        raise ImportError("yt-dlp saknas — kör: pip install yt-dlp")

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    item_id  = item["id"]
    url      = item["url"]
    out_stem = TRANSCRIPTS_DIR / f"vigil_{item_id}_caption"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writeautomaticsub": True,   # Automatgenererade undertexter
        "subtitlesformat": "vtt",    # WebVTT — har tidsstämplar
        "subtitleslangs": CAPTION_LANGS,
        "outtmpl": str(out_stem),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        logger.debug(f"yt-dlp fel vid caption-nedladdning item {item_id}: {e}")
        return None

    vtt_file = _find_vtt_file(out_stem, item_id)
    if not vtt_file:
        logger.debug(f"Inga auto-captions tillgängliga: item {item_id} ({url[:60]})")
        return None

    # Parsa VTT och sammanfoga korta segment
    try:
        vtt_text = vtt_file.read_text(encoding="utf-8", errors="replace")
        segments = _parse_vtt(vtt_text)
        vtt_file.unlink(missing_ok=True)   # Ta bort råfilen
    except Exception as e:
        logger.warning(f"VTT-parsfel item {item_id}: {e}")
        return None

    if not segments:
        logger.debug(f"Tom VTT för item {item_id}")
        return None

    segments = _merge_segments(segments, window_sec=30.0)

    # Spara i samma JSON-format som Whisper
    transcript_path = TRANSCRIPTS_DIR / f"vigil_{item_id}.json"
    transcript_path.write_text(
        json.dumps(segments, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    word_count = sum(len(s["text"].split()) for s in segments)
    logger.info(
        f"Caption OK: item {item_id}, {len(segments)} segment, "
        f"~{word_count} ord → {transcript_path.name}"
    )
    return transcript_path


# ---------------------------------------------------------------------------
# Köprocessor
# ---------------------------------------------------------------------------

def run_caption_check(conn, domain: Optional[str] = None,
                      max_items: int = 50) -> dict:
    """
    Kör caption-check på YouTube-items i state=queued.

    Hittas captions  → transcript_path uppdateras, state → captioned,
                        item tas bort från transcription_queue.
    Inga captions    → item kvar i queued (körs av Whisper nästa steg).

    Returnerar räknare: {captioned, skipped, failed}.
    """
    counts = {"captioned": 0, "skipped": 0, "failed": 0}

    query = """
        SELECT id, url, title, source_name
        FROM vigil_items
        WHERE state = 'queued' AND source_type = 'youtube'
        {}
        ORDER BY priority_score DESC
        LIMIT ?
    """.format("AND domain = ?" if domain else "")

    params = (domain, max_items) if domain else (max_items,)
    rows = conn.execute(query, params).fetchall()

    if not rows:
        logger.info("Inga YouTube-items i kö att caption-checka.")
        return counts

    logger.info(f"Caption-check startar: {len(rows)} YouTube-items")

    for row in rows:
        item_id = row["id"]
        try:
            transcript_path = fetch_captions(dict(row))

            if transcript_path:
                conn.execute(
                    "UPDATE vigil_items SET transcript_path = ? WHERE id = ?",
                    (str(transcript_path), item_id),
                )
                transition(conn, item_id, "captioned")
                # Ta bort ur transcription_queue — Whisper behövs inte
                conn.execute(
                    "DELETE FROM transcription_queue WHERE item_id = ?",
                    (item_id,),
                )
                conn.commit()
                counts["captioned"] += 1
            else:
                counts["skipped"] += 1   # Kvar i queued → Whisper

        except Exception as e:
            logger.error(f"Caption-fel item {item_id}: {e}", exc_info=True)
            counts["failed"] += 1

    logger.info(
        f"Caption-check klar: "
        f"{counts['captioned']} captioned (slipper Whisper), "
        f"{counts['skipped']} till Whisper-kö, "
        f"{counts['failed']} fel"
    )
    return counts


# ---------------------------------------------------------------------------
# CLI (fristående körning)
# ---------------------------------------------------------------------------

def _main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="clio-vigil caption_fetcher — hämtar YouTube auto-captions"
    )
    parser.add_argument("--run",    action="store_true", help="Kör caption-check på alla queued YouTube-items")
    parser.add_argument("--item",   type=int,            help="Kör caption-check för specifikt item-ID")
    parser.add_argument("--domain", type=str,            help="Begränsa till domän")
    parser.add_argument("--max",    type=int, default=50, help="Max antal items (default: 50)")
    args = parser.parse_args()

    conn = init_db()

    if args.item:
        item = conn.execute(
            "SELECT * FROM vigil_items WHERE id = ?", (args.item,)
        ).fetchone()
        if not item:
            print(f"Item {args.item} finns inte.")
            sys.exit(1)
        path = fetch_captions(dict(item))
        print(f"✓ Captions: {path}" if path else "✗ Inga captions tillgängliga")

    elif args.run:
        counts = run_caption_check(conn, domain=args.domain, max_items=args.max)
        print(
            f"\n✓ Caption-check klar: "
            f"{counts['captioned']} captioned, "
            f"{counts['skipped']} till Whisper, "
            f"{counts['failed']} fel"
        )
    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    _main()
