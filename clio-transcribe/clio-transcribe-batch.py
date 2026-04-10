"""
clio-transcribe-batch.py
Batch transcription of audio files to text using Whisper.

Supported formats: mp3, mp4, wav, m4a, ogg, flac, webm

Usage:
    python clio-transcribe-batch.py <input-folder>

Example:
    python clio-transcribe-batch.py "C:\\Users\\fredr\\Documents\\audio"

Output per file:
    - filename_TRANSKRIPT.md  – text with timestamps per segment
    - clio-transcribe-batch.log – log file in script folder
"""

import sys
import re
import time
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime

from clio_core.utils import has_non_ascii, t

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "2.0.1"

TRANSCRIPT_SUFFIX = "_TRANSKRIPT"
SUPPORTED_FORMATS = {".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".flac", ".webm"}
DEFAULT_LANGUAGE  = "sv"
STATE_FILE        = Path(__file__).parent.parent / "config" / "clio_state.json"
LOG_FILE          = Path(__file__).parent / "clio-transcribe-batch.log"

# Model selection – KB-Whisper for Swedish, standard Whisper for others
WHISPER_MODELS = {
    "sv": {
        "small":  "KBLab/kb-whisper-small",
        "medium": "KBLab/kb-whisper-medium",
        "large":  "KBLab/kb-whisper-large",
    },
    "default": {
        "small":  "small",
        "medium": "medium",
        "large":  "large",
    },
}
WHISPER_SIZE = "medium"  # Change to "large" on GPU machine

# Language name mapping
LANGUAGE_MAP = {
    "svenska": "sv", "swedish": "sv",
    "engelska": "en", "english": "en",
    "tyska": "de", "german": "de",
    "franska": "fr", "french": "fr",
    "spanska": "es", "spanish": "es",
    "finska": "fi", "finnish": "fi",
    "norska": "no", "norwegian": "no",
    "danska": "da", "danish": "da",
}

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Hardware config ───────────────────────────────────────────────────────────

def load_hw_config() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return state.get("hw", {})
    except:
        return {}


def select_backend(hw: dict) -> tuple:
    if hw.get("cuda"):
        return "cuda", "float16"
    return "cpu", "int8"


def ensure_whisper():
    try:
        import faster_whisper
    except ImportError:
        log.info("Installing faster-whisper...")
        subprocess.run([sys.executable, "-m", "pip", "install", "faster-whisper"], check=True)

# ── File discovery ────────────────────────────────────────────────────────────

def find_audio_files(folder: Path, recursive: bool = False) -> list:
    if recursive:
        all_files = [p for p in folder.rglob("*") if p.suffix.lower() in SUPPORTED_FORMATS]
    else:
        all_files = [p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_FORMATS]
    return sorted([p for p in all_files if TRANSCRIPT_SUFFIX not in p.stem])

# ── Transcription ─────────────────────────────────────────────────────────────

def transcribe(file: Path, device: str, compute_type: str, language: str = None) -> tuple:
    from faster_whisper import WhisperModel

    transcript_file = file.parent / f"{file.stem}{TRANSCRIPT_SUFFIX}.md"
    if transcript_file.exists():
        return False, None, f"Skipping – transcript already exists: {transcript_file.name}"

    import tempfile, shutil

    use_temp = has_non_ascii(str(file)) or ' ' in str(file)
    tmp_dir  = None

    try:
        if use_temp:
            tmp_dir  = Path(tempfile.mkdtemp())
            src      = tmp_dir / f"clio_audio{file.suffix.lower()}"
            shutil.copy2(str(file), str(src))
            source_file = src
            log.info(f"  Copied to temp: {src.name}")
        else:
            source_file = file

        model_name = WHISPER_MODELS.get(language or "default", WHISPER_MODELS["default"])[WHISPER_SIZE]
        log.info(f"  Loading model: {model_name} ({device})...")
        model = WhisperModel(model_name, device=device, compute_type=compute_type)

        log.info("  Transcribing...")
        segments, info = model.transcribe(
            str(source_file),
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        detected_lang = info.language
        lang_prob     = info.language_probability
        log.info(f"  Detected language: {detected_lang} ({lang_prob:.0%})")

        lines = []
        lines.append(f"# {file.stem}\n")
        lines.append(f"- **Source:** {file.name}")
        lines.append(f"- **Date:** {datetime.now().strftime('%Y-%m-%d')}")
        lines.append(f"- **Language:** {detected_lang} ({lang_prob:.0%})")
        lines.append(f"- **Model:** {model_name}")
        lines.append(f"- **Backend:** {device}\n")
        lines.append("---\n")

        segment_count = 0
        for seg in segments:
            start = _format_time(seg.start)
            end   = _format_time(seg.end)
            text  = seg.text.strip()
            lines.append(f"**[{start} → {end}]** {text}\n")
            segment_count += 1
            if segment_count % 100 == 0:
                log.info(f"  ... {segment_count} segments transcribed")

        transcript_file.write_text("\n".join(lines), encoding="utf-8")
        if use_temp and tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        size_kb = transcript_file.stat().st_size / 1024
        return True, transcript_file, f"OK -> {transcript_file.name} ({size_kb:.0f} KB, {segment_count} segments)"

    except Exception as e:
        if use_temp and tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return False, None, f"EXCEPTION: {e}"


def _format_time(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s   = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_folder = Path(sys.argv[1])
    if not input_folder.is_dir():
        log.error(f"Folder not found: {input_folder}")
        sys.exit(1)

    ensure_whisper()

    hw = load_hw_config()
    device, compute_type = select_backend(hw)
    if hw.get("gpu_name") or hw.get("gpu"):
        log.info(f"Hardware: {hw.get('gpu_name') or hw.get('gpu')} ({device})")
    else:
        log.info(f"Hardware: CPU ({device})")

    files     = find_audio_files(input_folder, recursive=False)
    files_sub = find_audio_files(input_folder, recursive=True)
    extra     = len(files_sub) - len(files)

    if extra > 0:
        print(f"\nFound {len(files)} audio file(s) in folder and {extra} in subfolders.")
        answer = input("Search subfolders too? [n/J]: ").strip().lower()
        if answer == "j":
            files = files_sub

    if not files:
        log.info("No audio files to process.")
        return

    print(f"\nLanguage code (Enter = sv, auto = automatic detection)")
    print(t("language_hint"))
    lang_input = input("Language [sv]: ").strip().lower()
    if not lang_input:
        language = "sv"
    elif lang_input == "auto":
        language = None
    else:
        language = LANGUAGE_MAP.get(lang_input, lang_input)
    log.info(f"Language: {language or 'auto-detect'}")

    log.info(f"clio-transcribe-batch v{__version__}")
    log.info(f"Starting batch – {len(files)} file(s)")
    log.info(f"Folder: {input_folder}")
    log.info("-" * 60)

    succeeded = failed = skipped = 0
    total_start = time.time()

    for file in files:
        log.info(f"Processing: {file.name}")
        start = time.time()
        ok, _, message = transcribe(file, device, compute_type, language)
        elapsed = time.time() - start

        if ok:
            log.info(f"  {message} ({elapsed:.0f}s)")
            succeeded += 1
        elif "Skipping" in message:
            log.info(f"  {message}")
            skipped += 1
        else:
            log.error(f"  {message}")
            failed += 1

    total = time.time() - total_start
    log.info("-" * 60)
    log.info(f"Done in {total:.0f}s – Succeeded: {succeeded} | Skipped: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    main()
