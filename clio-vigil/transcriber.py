"""
clio-vigil — transcriber.py
============================
Laddar ner och transkriberar bevakningsobjekt med faster-whisper.

Flöde:
  1. Hämta nästa objekt ur kön (state=queued), sorterat på priority_score
  2. Ladda ned audio via yt-dlp (youtube) eller requests (rss/podcast)
  3. Transkribera med faster-whisper, segmentvis
  4. Preemptiv paus: kontrollera var 50:e segment om högre prio väntar
  5. Spara transkript (JSON med tidsstämplar + läsbar txt)
  6. Uppdatera vigil_items: state=transcribed, transcript_path

Preemptiv paus:
  orchestrator.preempt_current(conn, current_id, reason, segment)
  Jobbet återupptas från whisper_segment vid nästa körning.

Körning (separat från pipeline — GPU-intensiv):
  python transcriber.py --run [--domain ufo] [--max 5]
  python transcriber.py --item 42
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional

from orchestrator import (
    get_next_queued,
    init_db,
    preempt_current,
    transition,
)

logger = logging.getLogger(__name__)

DATA_DIR       = Path(__file__).parent / "data"
AUDIO_DIR      = DATA_DIR / "audio"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"

# ---------------------------------------------------------------------------
# Transkriptionsprofiler
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
# Audio-nedladdning
# ---------------------------------------------------------------------------

def _download_youtube(url: str, output_path: Path) -> bool:
    """Laddar ned audio från YouTube via yt-dlp Python-bibliotek."""
    try:
        import yt_dlp
    except ImportError:
        raise ImportError("yt-dlp saknas — kör: pip install yt-dlp")

    # yt-dlp lägger till extension — ge sökväg utan .mp3
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


def download_audio(item: dict) -> Optional[Path]:
    """
    Laddar ned audio för ett bevakningsobjekt.
    Returnerar sökväg till nedladdad fil, eller None vid fel.
    """
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    item_id     = item["id"]
    source_type = item["source_type"]
    url         = item["url"]

    output_path = AUDIO_DIR / f"vigil_{item_id}.mp3"

    if source_type == "youtube":
        logger.info(f"Laddar ned YouTube-audio: {url[:70]}")
        ok = _download_youtube(url, output_path)

    elif source_type == "rss":
        # Försök med sparad enclosure-URL (satt av rss_collector om tillgänglig),
        # annars fall tillbaka på item-URL (kan vara artikel, inte ljud)
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
# Transkription
# ---------------------------------------------------------------------------

def _should_preempt(conn, current_id: int, current_priority: float) -> Optional[int]:
    """
    Kontrollerar om ett väntande jobb har högre prioritet.
    Returnerar item_id för preempteraren, eller None.
    """
    row = conn.execute(
        """SELECT id FROM vigil_items
           WHERE state = 'queued' AND id != ? AND priority_score > ?
           ORDER BY priority_score DESC LIMIT 1""",
        (current_id, current_priority),
    ).fetchone()
    return row["id"] if row else None


def transcribe_item(conn, item_id: int, domain_config: dict) -> bool:
    """
    Transkriberar ett bevakningsobjekt med faster-whisper.
    Stödjer återupptagning från whisper_segment vid preemptiv paus.
    Returnerar True om transkriptionen slutfördes helt.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError("faster-whisper saknas — kör: pip install faster-whisper")

    item = conn.execute(
        "SELECT * FROM vigil_items WHERE id = ?", (item_id,)
    ).fetchone()
    if not item:
        logger.error(f"Item {item_id} hittades inte i databasen")
        return False

    # Profil och modell
    profile_name = domain_config.get("transcription_profile", "default")
    profile      = TRANSCRIPTION_PROFILES.get(profile_name, TRANSCRIPTION_PROFILES["default"])
    model_size   = item["whisper_model"] or domain_config.get("whisper_model", "medium")
    language     = profile["language"]
    resume_from  = item["whisper_segment"] or 0

    # Sätt tillstånd → transcribing
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

    # Ladda ned audio
    audio_path = download_audio(dict(item))
    if not audio_path:
        transition(conn, item_id, "queued")
        return False

    # Ladda in befintliga segment om vi återupptar
    existing_segments: list[dict] = []
    if resume_from > 0 and transcript_json.exists():
        try:
            existing_segments = json.loads(transcript_json.read_text(encoding="utf-8"))
            logger.info(f"Återupptar från segment {resume_from} ({len(existing_segments)} befintliga)")
        except Exception:
            existing_segments = []
            resume_from = 0

    logger.info(
        f"Transkriberar [{model_size}/{language}] item {item_id}: "
        f"{(item['title'] or '—')[:55]}"
    )

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    raw_segs, _ = model.transcribe(str(audio_path), beam_size=5, language=language)

    new_segments: list[dict] = []
    preempted = False

    for seg_idx, seg in enumerate(raw_segs):
        if seg_idx < resume_from:
            continue  # hoppa över redan sparade segment

        new_segments.append({
            "start": round(seg.start, 2),
            "end":   round(seg.end, 2),
            "text":  seg.text.strip(),
        })

        # Spara progress + preemptiv kontroll var 50:e segment
        if len(new_segments) % 50 == 0:
            _flush_segments(transcript_json, existing_segments + new_segments)
            conn.execute(
                "UPDATE vigil_items SET whisper_segment = ? WHERE id = ?",
                (seg_idx + 1, item_id),
            )
            conn.commit()

            preempter_id = _should_preempt(conn, item_id, item["priority_score"])
            if preempter_id:
                logger.info(
                    f"Preempteras av item {preempter_id} vid segment {seg_idx + 1}"
                )
                preempt_current(
                    conn, item_id,
                    reason=f"preempted_by_item_{preempter_id}",
                    segment=seg_idx + 1,
                )
                preempted = True
                break

    _cleanup_audio(audio_path)

    if preempted:
        return False

    # Klar — skriv färdigt transkript
    all_segments = existing_segments + new_segments
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

    logger.info(f"Klar: {len(all_segments)} segment → {transcript_json.name}")
    return True


# ---------------------------------------------------------------------------
# Köprocessor
# ---------------------------------------------------------------------------

def run_transcription_queue(conn, domain: Optional[str] = None,
                             max_items: int = 10) -> dict:
    """
    Processar transkriptionskön tills den är tom eller max_items nåtts.
    Returnerar räknare: {completed, preempted, failed}.
    """
    # Importeras här för att undvika cirkulär import
    from main import load_domain_config

    counts = {"completed": 0, "preempted": 0, "failed": 0}

    for _ in range(max_items):
        item = get_next_queued(conn, domain)
        if not item:
            logger.info("Transkriptionskön är tom")
            break

        item_id = item["id"]
        try:
            domain_config = load_domain_config(item["domain"])
        except FileNotFoundError:
            domain_config = {"transcription_profile": "default", "whisper_model": "medium"}

        ok = transcribe_item(conn, item_id, domain_config)

        if ok:
            counts["completed"] += 1
        else:
            state_row = conn.execute(
                "SELECT state FROM vigil_items WHERE id = ?", (item_id,)
            ).fetchone()
            if state_row and state_row["state"] == "queued":
                counts["preempted"] += 1
                break  # Jobbyte — starta om loopen med ny prioritetsordning
            else:
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
    parser.add_argument("--run", action="store_true",
                        help="Kör kön tills tom")
    parser.add_argument("--item", type=int,
                        help="Transkribera specifikt item-ID")
    parser.add_argument("--domain", type=str,
                        help="Begränsa till domän")
    parser.add_argument("--max", type=int, default=10,
                        help="Max antal objekt (default: 10)")
    args = parser.parse_args()

    conn = init_db()

    if args.item:
        from main import load_domain_config, get_all_domains
        item = conn.execute(
            "SELECT * FROM vigil_items WHERE id = ?", (args.item,)
        ).fetchone()
        if not item:
            print(f"Item {args.item} finns inte.")
            sys.exit(1)
        try:
            domain_config = load_domain_config(item["domain"])
        except FileNotFoundError:
            domain_config = {"transcription_profile": "default", "whisper_model": "medium"}
        ok = transcribe_item(conn, args.item, domain_config)
        print("✓ Klar" if ok else "✗ Misslyckades eller preempterad")

    elif args.run:
        counts = run_transcription_queue(conn, domain=args.domain, max_items=args.max)
        print(
            f"\n✓ Transkription klar: "
            f"{counts['completed']} klara, "
            f"{counts['preempted']} preempterade, "
            f"{counts['failed']} misslyckade"
        )
    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    _main()
