"""
clio-vigil — transcriber.py
============================
Transkriberar bevakningsobjekt med rätt backend per språk:
  - Engelska  → nvidia/parakeet-tdt-1.1b (NeMo, CUDA) — snabbt, hög kvalitet
  - Svenska   → KBLab/kb-whisper-medium  (faster-whisper, CUDA int8)

Modeller cachas per process (laddas en gång, återanvänds för alla items).

Flöde:
  1. Hämta nästa objekt ur kön (state=queued), sorterat på priority_score
  2. Ladda ned audio via yt-dlp (youtube) eller requests (rss/podcast)
  3. Transkribera med rätt backend baserat på item.language
  4. Preemptiv paus: kontrollera var 50:e segment om högre prio väntar (Whisper)
     Parakeet: hela filen i ett anrop — avbrutna items körs om från början
  5. Spara transkript (JSON med tidsstämplar + läsbar txt)
  6. Uppdatera vigil_items: state=transcribed, transcript_path

Körning:
  python transcriber.py --run [--domain ufo] [--max 5]
  python transcriber.py --item 42
"""

import json
import logging
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from orchestrator import (
    get_next_queued,
    get_next_for_transcription,
    init_db,
    preempt_current,
    transition,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SIGTERM-hantering — ren avslutning med bevarat delresultat
# ---------------------------------------------------------------------------

_shutdown_requested: bool = False


def _handle_sigterm(signum, frame):
    global _shutdown_requested
    logger.info("SIGTERM mottagen — avslutar transkription rent vid nästa segment")
    _shutdown_requested = True


DATA_DIR        = Path(__file__).parent / "data"
AUDIO_DIR       = DATA_DIR / "audio"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"

# ---------------------------------------------------------------------------
# Transkriptionsprofiler (fallback när item.language saknas)
# ---------------------------------------------------------------------------

TRANSCRIPTION_PROFILES = {
    "ufo_content": {
        "language": "en",
        "description": "UFO/UAP-innehåll, engelska",
    },
    "swedish_news": {
        "language": "sv",
        "description": "Svenska nyheter och podcasts",
    },
    "default": {
        "language": "en",
        "description": "Standard (engelska)",
    },
}

# ---------------------------------------------------------------------------
# Modellcache — laddas en gång per process
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict = {}


def _get_whisper(model_size: str):
    """Returnerar cachad faster-whisper-modell (CUDA, int8)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError("faster-whisper saknas — kör: pip install faster-whisper")
    key = f"whisper:{model_size}"
    if key not in _MODEL_CACHE:
        logger.info("Laddar whisper-modell: %s (cuda/int8)", model_size)
        _MODEL_CACHE[key] = WhisperModel(model_size, device="cuda", compute_type="int8")
    return _MODEL_CACHE[key]


# ---------------------------------------------------------------------------
# Audio-nedladdning
# ---------------------------------------------------------------------------

def _download_youtube(url: str, output_path: Path) -> bool:
    """Laddar ned audio från YouTube via yt-dlp Python-bibliotek."""
    try:
        import yt_dlp
    except ImportError:
        raise ImportError("yt-dlp saknas — kör: pip install yt-dlp")

    output_template = str(output_path.with_suffix(""))
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "5"}],
        "outtmpl": output_template,
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
    """Laddar ned ljud-URL direkt (podcast-enclosures, direktlänkar)."""
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


def _make_slug(text: str, max_len: int = 20) -> str:
    text = text.lower()
    text = text.replace("å", "a").replace("ä", "a").replace("ö", "o")
    text = text.replace("é", "e").replace("ü", "u").replace("ñ", "n")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:max_len].rstrip("-")


def _audio_filename(item: dict) -> str:
    source = item.get("source_name") or "okand"
    slug   = _make_slug(source)
    date   = (item.get("published_at") or "")[:10].replace("-", "")
    if not date:
        date = "nodatum"
    return f"{slug}_{item['id']}_{date}.mp3"


def download_audio(item: dict) -> Optional[Path]:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    item_id     = item["id"]
    source_type = item["source_type"]
    url         = item["url"]
    output_path = AUDIO_DIR / _audio_filename(item)

    if source_type == "youtube":
        logger.info(f"Laddar ned YouTube-audio: {url[:70]}")
        ok = _download_youtube(url, output_path)
    elif source_type == "rss":
        raw = json.loads(item["raw_metadata"] or "{}")
        audio_url = raw.get("enclosure_url") or url
        logger.info(f"Laddar ned RSS-audio: {audio_url[:70]}")
        ok = _download_url(audio_url, output_path)
    else:
        logger.warning(f"Okänd source_type '{source_type}' för item {item_id} — hoppar över")
        return None

    if not ok:
        logger.error(f"Nedladdning misslyckades för item {item_id}")
        return None

    size_kb = output_path.stat().st_size // 1024
    logger.info(f"Audio klar: {output_path.name} ({size_kb} KB)")
    return output_path


# ---------------------------------------------------------------------------
# Parakeet-backend (engelska, NeMo, CUDA)
# ---------------------------------------------------------------------------

def _mp3_to_wav(mp3_path: Path, wav_path: Path) -> bool:
    """Konverterar MP3 → WAV 16 kHz mono för Parakeet."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "16000", "-ac", "1", str(wav_path)],
        capture_output=True,
    )
    return wav_path.exists() and wav_path.stat().st_size > 0


def _words_to_segments(words: list[dict], gap_threshold: float = 1.0,
                       max_seg_duration: float = 15.0) -> list[dict]:
    """
    Grupperar ord till segment (max ~15 s eller vid talpaus > 1 s).
    Varje word-dict förväntas ha 'start', 'end', 'word'.
    """
    if not words:
        return []
    segments = []
    current_words = []
    seg_start = words[0]["start"]

    for w in words:
        if current_words:
            gap = w["start"] - current_words[-1]["end"]
            duration = w["end"] - seg_start
            if gap > gap_threshold or duration > max_seg_duration:
                text = " ".join(cw["word"] for cw in current_words).strip()
                if text:
                    segments.append({"start": round(seg_start, 2),
                                     "end": round(current_words[-1]["end"], 2),
                                     "text": text})
                seg_start = w["start"]
                current_words = []
        current_words.append(w)

    if current_words:
        text = " ".join(cw["word"] for cw in current_words).strip()
        if text:
            segments.append({"start": round(seg_start, 2),
                             "end": round(current_words[-1]["end"], 2),
                             "text": text})
    return segments


# ---------------------------------------------------------------------------
# Whisper-backend (svenska, faster-whisper, CUDA)
# ---------------------------------------------------------------------------

def _transcribe_whisper_stream(audio_path: Path, model_size: str, language: str,
                               item_id: int, conn, item: dict,
                               existing_segments: list, resume_from: int) -> tuple[list, bool]:
    """
    Transkriberar med faster-whisper (streaming, segmentvis med preemptiv paus).
    Returnerar (all_segments, preempted).
    """
    model = _get_whisper(model_size)
    raw_segs, _ = model.transcribe(str(audio_path), beam_size=5, language=language)

    new_segments: list[dict] = []
    preempted = False
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    transcript_json = TRANSCRIPTS_DIR / f"vigil_{item_id}.json"

    for seg_idx, seg in enumerate(raw_segs):
        if seg_idx < resume_from:
            continue

        if _shutdown_requested:
            if new_segments:
                _flush_segments(transcript_json, existing_segments + new_segments)
                conn.execute(
                    "UPDATE vigil_items SET whisper_segment = ? WHERE id = ?",
                    (seg_idx, item_id),
                )
                conn.commit()
            logger.info(
                f"SIGTERM: item {item_id} avbruten vid segment {seg_idx} "
                f"— {len(existing_segments) + len(new_segments)} segment sparade"
            )
            return [], False  # Signalera SIGTERM via tom lista

        new_segments.append({
            "start": round(seg.start, 2),
            "end":   round(seg.end, 2),
            "text":  seg.text.strip(),
        })

        if len(new_segments) % 50 == 0:
            _flush_segments(transcript_json, existing_segments + new_segments)
            conn.execute(
                "UPDATE vigil_items SET whisper_segment = ? WHERE id = ?",
                (seg_idx + 1, item_id),
            )
            conn.commit()

            preempter_id = _should_preempt(conn, item_id, item["priority_score"])
            if preempter_id:
                logger.info(f"Preempteras av item {preempter_id} vid segment {seg_idx + 1}")
                preempt_current(conn, item_id,
                                reason=f"preempted_by_item_{preempter_id}",
                                segment=seg_idx + 1)
                preempted = True
                break

    return existing_segments + new_segments, preempted


# ---------------------------------------------------------------------------
# Transkription — routing
# ---------------------------------------------------------------------------

def _should_preempt(conn, current_id: int, current_priority: float) -> Optional[int]:
    row = conn.execute(
        """SELECT id FROM vigil_items
           WHERE state = 'queued' AND id != ? AND priority_score > ?
           ORDER BY priority_score DESC LIMIT 1""",
        (current_id, current_priority),
    ).fetchone()
    return row["id"] if row else None


def transcribe_item(conn, item_id: int, domain_config: dict) -> bool:
    """
    Transkriberar ett bevakningsobjekt.
    Routar till Parakeet (engelska) eller kb-whisper (svenska) baserat på item.language.
    Returnerar True om transkriptionen slutfördes helt.
    """
    item = conn.execute(
        "SELECT * FROM vigil_items WHERE id = ?", (item_id,)
    ).fetchone()
    if not item:
        logger.error(f"Item {item_id} hittades inte i databasen")
        return False

    # Bestäm språk: item.language > domänprofil > default
    item_language = item["language"] if item["language"] else None
    if not item_language:
        profile_name  = domain_config.get("transcription_profile", "default")
        profile       = TRANSCRIPTION_PROFILES.get(profile_name, TRANSCRIPTION_PROFILES["default"])
        item_language = profile["language"]

    model_size  = item["whisper_model"] or domain_config.get("whisper_model", "kb-whisper-medium")
    resume_from = item["whisper_segment"] or 0

    transition(conn, item_id, "transcribing")
    conn.execute(
        """UPDATE transcription_queue SET started_at = datetime('now')
           WHERE item_id = ? AND completed_at IS NULL""",
        (item_id,),
    )
    conn.commit()

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    transcript_json = TRANSCRIPTS_DIR / f"vigil_{item_id}.json"
    transcript_txt  = TRANSCRIPTS_DIR / f"vigil_{item_id}.txt"

    existing_path = item["audio_path"] if item["audio_path"] else None
    if existing_path and Path(existing_path).exists():
        logger.info(f"Använder befintlig audio: {existing_path}")
        audio_path = Path(existing_path)
        _delete_after = False
    else:
        audio_path = download_audio(dict(item))
        _delete_after = True

    if not audio_path:
        transition(conn, item_id, "queued")
        return False

    # ── faster-whisper (engelska + svenska, CUDA) ────────────────────────────────────
    if item_language == "en":
        model_size = "large-v3-turbo"
    logger.info(
        f"Transkriberar [{model_size}/{item_language}] item {item_id}: "
        f"{(item['title'] or '—')[:55]}"
    )
    existing_segments: list[dict] = []
    if resume_from > 0 and transcript_json.exists():
        try:
            existing_segments = json.loads(transcript_json.read_text(encoding="utf-8"))
            logger.info(f"Återupptar från segment {resume_from} ({len(existing_segments)} befintliga)")
        except Exception:
            existing_segments = []
            resume_from = 0

    try:
        all_segments, preempted = _transcribe_whisper_stream(
            audio_path, model_size, item_language,
            item_id, conn, dict(item), existing_segments, resume_from,
        )
    except Exception as e:
        logger.error(f"Whisper-fel för item {item_id}: {e}")
        transition(conn, item_id, "failed")
        if _delete_after:
            _cleanup_audio(audio_path)
        return False

    if _delete_after:
        _cleanup_audio(audio_path)

    if preempted:
        return False

    if not all_segments:
        # SIGTERM under whisper — item är kvar i transcribing för återupptagning
        return False

    _flush_segments(transcript_json, all_segments)
    transcript_txt.write_text(
        "\n".join(f"[{_fmt_ts(s['start'])}] {s['text']}" for s in all_segments),
        encoding="utf-8",
    )
    transition(conn, item_id, "transcribed", transcript_path=str(transcript_json))
    conn.execute(
        """UPDATE transcription_queue SET completed_at = datetime('now')
           WHERE item_id = ? AND completed_at IS NULL""",
        (item_id,),
    )
    conn.commit()
    logger.info(f"Klar [{model_size}]: {len(all_segments)} segment → {transcript_json.name}")
    return True


# ---------------------------------------------------------------------------
# Odoo-sync (kraschsäker — misslyckas tyst)
# ---------------------------------------------------------------------------

def _odoo_sync_item(conn, item_id: int) -> None:
    try:
        from odoo_writer import get_odoo_env, sync_item
        env = get_odoo_env()
        if env is None:
            return
        row = conn.execute("SELECT * FROM vigil_items WHERE id = ?", (item_id,)).fetchone()
        if row:
            sync_item(env, row)
            logger.info("Odoo-sync: item %d uppdaterad", item_id)
    except Exception as exc:
        logger.warning("Odoo-sync misslyckades för item %d: %s", item_id, exc)


# ---------------------------------------------------------------------------
# Köprocessor
# ---------------------------------------------------------------------------

def run_transcription_queue(conn, domain: Optional[str] = None,
                             max_items: int = 10) -> dict:
    """
    Processar transkriptionskön tills den är tom eller max_items nåtts.
    Returnerar räknare: {completed, preempted, failed}.
    """
    from main import load_domain_config

    global _shutdown_requested
    _shutdown_requested = False
    signal.signal(signal.SIGTERM, _handle_sigterm)

    counts = {"completed": 0, "preempted": 0, "failed": 0}

    for _ in range(max_items):
        if _shutdown_requested:
            logger.info("SIGTERM: avbryter kön — återupptas vid nästa körning")
            break

        item = get_next_for_transcription(conn, domain)
        if not item:
            logger.info("Transkriptionskön är tom")
            break

        item_id = item["id"]
        try:
            domain_config = load_domain_config(item["domain"])
        except FileNotFoundError:
            domain_config = {"transcription_profile": "default", "whisper_model": "kb-whisper-medium"}

        ok = transcribe_item(conn, item_id, domain_config)

        if ok:
            counts["completed"] += 1
            _odoo_sync_item(conn, item_id)
        else:
            # SIGTERM mottaget — bryt utan att markera som failed; item stannar i
            # transcribing med whisper_segment satt → återupptas av steg 0 nästa körning
            if _shutdown_requested:
                logger.info(f"SIGTERM: item {item_id} sparas i transcribing — återupptas nästa körning")
                break
            state_row = conn.execute(
                "SELECT state FROM vigil_items WHERE id = ?", (item_id,)
            ).fetchone()
            if state_row and state_row["state"] == "queued":
                counts["preempted"] += 1
                continue
            elif state_row and state_row["state"] == "transcribing":
                # Avbröts utan SIGTERM (t.ex. krasch) — lämna i transcribing för återupptagning
                logger.info(f"Item {item_id} stannar i transcribing — återupptas nästa körning")
                counts["failed"] += 1
            else:
                transition(conn, item_id, "failed")
                logger.warning(f"Item {item_id} markerad som failed — fortsätter med nästa")
                counts["failed"] += 1

    return counts


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _flush_segments(path: Path, segments: list[dict]) -> None:
    path.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _cleanup_audio(path: Optional[Path]) -> None:
    if path and path.exists():
        try:
            path.unlink()
        except Exception as e:
            logger.warning(f"Kunde inte ta bort audio {path}: {e}")


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
        description="clio-vigil transcriber — kör transkriptionskö"
    )
    parser.add_argument("--run", action="store_true", help="Kör kön tills tom")
    parser.add_argument("--item", type=int, help="Transkribera specifikt item-ID")
    parser.add_argument("--domain", type=str, help="Begränsa till domän")
    parser.add_argument("--max", type=int, default=10, help="Max antal objekt (default: 10)")
    args = parser.parse_args()

    conn = init_db()

    if args.item:
        from main import load_domain_config
        item = conn.execute(
            "SELECT * FROM vigil_items WHERE id = ?", (args.item,)
        ).fetchone()
        if not item:
            print(f"Item {args.item} finns inte.")
            sys.exit(1)
        try:
            domain_config = load_domain_config(item["domain"])
        except FileNotFoundError:
            domain_config = {"transcription_profile": "default", "whisper_model": "kb-whisper-medium"}
        ok = transcribe_item(conn, args.item, domain_config)
        print("OK Klar" if ok else "MISS Misslyckades eller preempterad")

    elif args.run:
        counts = run_transcription_queue(conn, domain=args.domain, max_items=args.max)
        print(
            f"\nTranskription klar: "
            f"{counts['completed']} klara, "
            f"{counts['preempted']} preempterade, "
            f"{counts['failed']} misslyckade"
        )
    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    _main()
