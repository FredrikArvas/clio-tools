"""
clio-narrate-batch.py
Converts text/MD/DOCX files to speech (audiobook).

Engines:
    1. Piper     – local, free, Swedish voices (nst, lisa)
    2. Edge-TTS  – Microsoft, free, requires internet
    3. ElevenLabs – paid, best quality, voice cloning

Input:  .txt, .md, .docx
Output: .mp3 per file

Usage:
    python clio-narrate-batch.py <input-folder>

Environment variables:
    ELEVENLABS_API_KEY  – required for ElevenLabs engine
"""

import sys
import re
import os
import time
import asyncio
import logging
import subprocess
from pathlib import Path
from datetime import datetime

from clio_core.utils import sanitize_filename, has_non_ascii, t

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "3.1.1"

NARRATE_SUFFIX   = "_NARRAT"
SUPPORTED_FORMATS = {".txt", ".md", ".docx"}
LOG_FILE         = Path(__file__).parent / "clio-narrate-batch.log"
PIPER_VOICE_DIR  = Path(__file__).parent.parent / "config" / "piper-voices"
STATE_FILE       = Path(__file__).parent.parent / "config" / "clio_state.json"

# Piper voices
PIPER_VOICES = {
    "sv-nst":  {"name": "NST (female)",  "file": "sv_SE-nst-medium",  "url": "sv/sv_SE/nst/medium"},
    "sv-lisa": {"name": "Lisa (female)", "file": "sv_SE-lisa-medium", "url": "sv/sv_SE/lisa/medium"},
}

# Edge-TTS voices
EDGE_VOICES_SV = {
    "sofie":   {"name": "Sofie (female)", "voice": "sv-SE-SofieNeural"},
    "mattias": {"name": "Mattias (male)", "voice": "sv-SE-MattiasNeural"},
}
EDGE_VOICES_OTHER = {
    "en": "en-GB-SoniaNeural",
    "de": "de-DE-KatjaNeural",
    "fr": "fr-FR-DeniseNeural",
    "fi": "fi-FI-SelmaNeural",
    "no": "nb-NO-PernilleNeural",
    "da": "da-DK-ChristelNeural",
}

# Wisdom quotes for voice samples (keyed by voice short name)
WISDOM_QUOTES = {
    "sofie":   "Sofie whispers: The quiet moment often carries more truth than a thousand words.",
    "mattias": "Mattias says: Those who listen carefully hear more than those who speak loudly.",
    "nst":     "An old voice remembers: The words we choose shape the world we see.",
    "lisa":    "Lisa tells: In every story there is a door that opens inward.",
    "default": "Clio reads: What is written with care lives longer than what is said in haste.",
}

# Speed steps (Edge-TTS rate format)
SPEEDS = {
    "1": ("-30%", "Slow – good for note-takers"),
    "2": ("-10%", "Slightly slower – good for books"),
    "3": ("+0%",  "Normal"),
    "4": ("+15%", "Slightly faster"),
    "5": ("+30%", "Fast – good for review"),
}

# Language name mapping
LANGUAGE_MAP = {
    "svenska": "sv", "swedish": "sv",
    "engelska": "en", "english": "en",
    "tyska": "de", "german": "de",
    "franska": "fr", "french": "fr",
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

# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(file: Path) -> str:
    suffix = file.suffix.lower()

    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", "python-docx"], check=True)
            from docx import Document
        doc = Document(str(file))
        return "\n\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())

    raw = file.read_text(encoding="utf-8", errors="replace")
    if suffix == ".md":
        raw = re.sub(r'^---.*?---\s*', '', raw, flags=re.DOTALL)
        raw = re.sub(r'<!--.*?-->', '', raw, flags=re.DOTALL)
        raw = re.sub(r'^#{1,6}\s+', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', raw)
        raw = re.sub(r'\*\[No text.*?\]\*', '', raw)
        raw = re.sub(r'^\*\[.*?\]\*\s*$', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'^---+\s*$', '', raw, flags=re.MULTILINE)

    return '\n'.join(r.strip() for r in raw.splitlines() if r.strip())


def split_into_chunks(text: str, max_chars: int = 1000) -> list:
    paragraphs = re.split(r'\n{2,}', text)
    result, buffer = [], ""
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(buffer) + len(p) < max_chars:
            buffer += (" " if buffer else "") + p
        else:
            if buffer:
                result.append(buffer)
            buffer = p
    if buffer:
        result.append(buffer)
    return result

# ── ID3 tagging ───────────────────────────────────────────────────────────────

def tag_mp3(file: Path, title: str, artist: str, album: str = "",
            genre: str = "Audiobook", comment: str = "",
            language: str = "swe", track: str = ""):
    try:
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, COMM, TLAN, TRCK, ID3NoHeaderError
        try:
            tags = ID3(str(file))
        except ID3NoHeaderError:
            tags = ID3()
        tags["TIT2"] = TIT2(encoding=3, text=title)
        tags["TPE1"] = TPE1(encoding=3, text=artist)
        if album:
            tags["TALB"] = TALB(encoding=3, text=album)
        tags["TCON"] = TCON(encoding=3, text=genre)
        tags["TLAN"] = TLAN(encoding=3, text=language)
        if comment:
            tags["COMM"] = COMM(encoding=3, lang="eng", desc="", text=comment)
        if track:
            tags["TRCK"] = TRCK(encoding=3, text=track)
        tags.save(str(file))
    except ImportError:
        pass
    except Exception:
        pass

# ── Piper engine ──────────────────────────────────────────────────────────────

def download_piper_voice(voice_key: str) -> Path | None:
    voice = PIPER_VOICES[voice_key]
    PIPER_VOICE_DIR.mkdir(parents=True, exist_ok=True)
    onnx = PIPER_VOICE_DIR / f"{voice['file']}.onnx"
    json_f = PIPER_VOICE_DIR / f"{voice['file']}.onnx.json"

    if not onnx.exists() or not json_f.exists():
        import urllib.request
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{voice['url']}"
        for url, dst in [
            (f"{base}/{voice['file']}.onnx?download=true", onnx),
            (f"{base}/{voice['file']}.onnx.json?download=true", json_f),
        ]:
            if not dst.exists():
                log.info(f"  Downloading {dst.name}...")
                try:
                    urllib.request.urlretrieve(url, str(dst))
                except Exception as e:
                    log.error(f"  Download failed: {e}")
                    return None
    return onnx


def narrate_piper(text: str, output_file: Path, voice_key: str, speed: str) -> tuple:
    try:
        from piper.voice import PiperVoice
        import json as _json, wave, io

        onnx = download_piper_voice(voice_key)
        if not onnx:
            raise RuntimeError("Could not download Piper voice files")

        json_f = onnx.with_suffix('.onnx.json')
        log.info(f"  Loading Piper voice: {onnx.name}...")
        voice_obj = PiperVoice.load(str(onnx))

        sample_rate = 22050
        if json_f.exists():
            try:
                cfg = _json.loads(json_f.read_text(encoding="utf-8"))
                sample_rate = cfg.get("audio", {}).get("sample_rate", 22050)
            except:
                pass

        chunks = split_into_chunks(text)
        wav_file = output_file.with_suffix('.wav')

        with wave.open(str(wav_file), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for i, chunk in enumerate(chunks):
                buf = io.BytesIO()
                with wave.open(buf, 'wb') as tmp:
                    tmp.setnchannels(1)
                    tmp.setsampwidth(2)
                    tmp.setframerate(sample_rate)
                    voice_obj.synthesize(chunk, tmp)
                buf.seek(44)
                wf.writeframes(buf.read())
                if i % 20 == 0 and i > 0:
                    log.info(f"  ... {i}/{len(chunks)} chunks")

        mp3 = _wav_to_mp3(wav_file, output_file)
        if mp3:
            wav_file.unlink(missing_ok=True)
            return True, f"OK -> {mp3.name} ({mp3.stat().st_size/1_048_576:.1f} MB, Piper)"
        return True, f"OK -> {wav_file.name} (Piper/WAV, {sample_rate}Hz)"

    except Exception as e:
        log.warning(f"  Piper failed: {e} – falling back to Edge-TTS")
        voice = list(EDGE_VOICES_SV.values())[0]["voice"]
        return narrate_edge(text, output_file, voice, speed)

# ── Edge-TTS engine ───────────────────────────────────────────────────────────

async def _edge_async(text: str, voice: str, speed: str, output_file: Path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=speed)
    await communicate.save(str(output_file))


def narrate_edge(text: str, output_file: Path, voice: str, speed: str) -> tuple:
    try:
        log.info(f"  Edge-TTS: {voice} (speed {speed})...")
        asyncio.run(_edge_async(text, voice, speed, output_file))
        return True, f"OK -> {output_file.name} ({output_file.stat().st_size/1_048_576:.1f} MB, Edge-TTS)"
    except Exception as e:
        return False, f"EXCEPTION Edge-TTS: {e}"

# ── ElevenLabs engine ─────────────────────────────────────────────────────────

def check_elevenlabs_quota(api_key: str) -> tuple:
    try:
        import urllib.request, json
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": api_key}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        limit = data.get("character_limit", 0)
        used  = data.get("character_count", 0)
        return True, limit - used
    except:
        return False, 0


def narrate_elevenlabs(text: str, output_file: Path, voice_id: str, speed: float) -> tuple:
    try:
        import urllib.request, json
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        payload = json.dumps({
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": speed},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            data=payload,
            headers={"Content-Type": "application/json",
                     "xi-api-key": api_key, "Accept": "audio/mpeg"}
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            output_file.write_bytes(r.read())
        return True, f"OK -> {output_file.name} ({output_file.stat().st_size/1_048_576:.1f} MB, ElevenLabs)"
    except Exception as e:
        return False, f"EXCEPTION ElevenLabs: {e}"


def fetch_elevenlabs_voices(api_key: str) -> list:
    try:
        import urllib.request, json
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": api_key}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return [(v["voice_id"], v["name"]) for v in data.get("voices", [])]
    except:
        return []

# ── WAV to MP3 ────────────────────────────────────────────────────────────────

def _wav_to_mp3(wav: Path, mp3: Path) -> Path | None:
    import shutil
    if not shutil.which("ffmpeg"):
        return None
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "4", str(mp3)],
        capture_output=True
    )
    return mp3 if result.returncode == 0 else None

# ── File discovery ────────────────────────────────────────────────────────────

def find_files(folder: Path, recursive: bool = False) -> list:
    if recursive:
        all_files = [p for p in folder.rglob("*") if p.suffix.lower() in SUPPORTED_FORMATS]
    else:
        all_files = [p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_FORMATS]
    return sorted([p for p in all_files if NARRATE_SUFFIX not in p.stem])


def select_files(files: list) -> list:
    if not files:
        return []
    print(f"\n── Files ({len(files)}) ──────────────────────────────────────")
    for i, f in enumerate(files, 1):
        size_kb = f.stat().st_size / 1024
        print(f"  {i:2}. {f.name}  ({size_kb:.0f} KB)")
    answer = input(t("select_files")).strip()
    if not answer:
        return files
    selected = []
    for part in answer.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(files):
                selected.append(files[idx])
    return selected if selected else files

# ── Voice test ────────────────────────────────────────────────────────────────

def voice_test(engine: str, voices: list, speed: str,
               source_file: Path = None, api_key: str = "") -> str:
    import shutil

    # Sample folder next to source file
    if source_file:
        sample_dir = source_file.parent / f"{source_file.stem}_SAMPLES"
    else:
        import tempfile
        sample_dir = Path(tempfile.mkdtemp())
    sample_dir.mkdir(exist_ok=True)

    # Get test text from source file (first 3 sentences)
    if source_file:
        try:
            raw = extract_text(source_file)
            sentences = [s.strip() for s in re.split(r'[.!?]+', raw) if len(s.strip()) > 20]
            test_text = ". ".join(sentences[:3]) + "."
        except:
            test_text = WISDOM_QUOTES["default"]
    else:
        test_text = WISDOM_QUOTES["default"]

    test_files = []
    print(f"\n── Voice test ────────────────────────────────────────")
    print(f"  Text: {test_text[:80]}...")
    print(f"  Saved to: {sample_dir.name}/")

    for voice_id, voice_name in voices:
        safe_name = sanitize_filename(voice_name)
        out = sample_dir / f"{safe_name}.mp3"
        print(f"  Generating: {voice_name}...")

        if engine == "edge":
            ok, _ = narrate_edge(test_text, out, voice_id, speed)
        elif engine == "elevenlabs":
            ok, _ = narrate_elevenlabs(test_text, out, voice_id, 1.0)
        else:
            ok = False

        if ok:
            tag_mp3(out, title=f"Voice sample – {voice_name}",
                    artist=voice_name.split()[0],
                    album=source_file.stem if source_file else "voice-sample",
                    comment=f"{engine} {voice_id} {speed}")
            test_files.append((voice_id, voice_name, out))
        else:
            print(f"  FAILED: {voice_name}")

    if not test_files:
        return voices[0][0]

    player = shutil.which("ffplay") or shutil.which("vlc") or shutil.which("mpv")
    print()
    for i, (vid, vname, f) in enumerate(test_files, 1):
        print(f"  {i}. {vname}  [{f.name}]")
        if player:
            ans = input(t("voice_test_play")).strip().lower()
            if ans != "n":
                subprocess.run([player, "-nodisp", "-autoexit", str(f)], capture_output=True)

    if not player:
        print(f"\n  Open files in {sample_dir} to listen.")

    print()
    if len(test_files) == 1:
        if not player:
            print("  (One voice available – open file manually to listen)")
        return test_files[0][0]

    val = input(t("voice_test_select", n=len(test_files))).strip()
    idx = int(val) - 1 if val.isdigit() and 1 <= int(val) <= len(test_files) else 0
    selected_id, selected_name, _ = test_files[idx]
    print(t("voice_test_selected", name=selected_name))
    return selected_id

# ── Engine/voice selection ────────────────────────────────────────────────────

def select_engine_and_voice(language: str, source_file: Path = None) -> tuple:
    print("\n── Engine ────────────────────────────────────────────")
    print("  1. Piper     (local, free)")
    print("  2. Edge-TTS  (internet, free)")
    print("  3. ElevenLabs (paid, best quality)")
    engine_val = input(t("engine_input")).strip() or "1"

    print("\n── Speed ──────────────────────────────────────────────")
    for k, (_, desc) in SPEEDS.items():
        print(f"  {k}. {desc}")
    speed_val = input(t("speed_input")).strip() or "3"
    speed_str, _ = SPEEDS.get(speed_val, SPEEDS["3"])
    speed_float  = 1.0 + float(speed_str.replace("%", "").replace("+", "")) / 100

    if engine_val == "1":
        print("\n── Piper voice ───────────────────────────────────────")
        for i, (k, v) in enumerate(PIPER_VOICES.items(), 1):
            print(f"  {i}. {v['name']} ({k})")
        voice_val  = input(t("voice_input")).strip() or "1"
        voice_keys = list(PIPER_VOICES.keys())
        idx        = int(voice_val) - 1 if voice_val.isdigit() and 1 <= int(voice_val) <= len(voice_keys) else 0
        voice_id   = voice_keys[idx]

        do_test = input(t("voice_test")).strip().lower()
        if do_test != "n":
            edge_voices = [(v["voice"], v["name"]) for v in EDGE_VOICES_SV.values()]
            voice_test("edge", edge_voices[:1], speed_str, source_file)

        return "piper", voice_id, speed_str, speed_float

    elif engine_val == "2":
        if language == "sv":
            voices = [(v["voice"], v["name"]) for v in EDGE_VOICES_SV.values()]
        else:
            voice_str = EDGE_VOICES_OTHER.get(language, "en-GB-SoniaNeural")
            voices    = [(voice_str, voice_str)]

        do_test = input(t("voice_test_plural")).strip().lower()
        if do_test != "n":
            voice_id = voice_test("edge", voices, speed_str, source_file)
        else:
            voice_id = voices[0][0]

        return "edge", voice_id, speed_str, speed_float

    else:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            print("ELEVENLABS_API_KEY missing. Falling back to Edge-TTS.")
            return "edge", list(EDGE_VOICES_SV.values())[0]["voice"], speed_str, speed_float

        print("\n  Fetching your ElevenLabs voices...")
        voices = fetch_elevenlabs_voices(api_key)
        if not voices:
            print("  Could not fetch voices. Check your API key.")
            return "edge", list(EDGE_VOICES_SV.values())[0]["voice"], speed_str, speed_float

        print("\n── ElevenLabs voices ─────────────────────────────────")
        for i, (vid, vname) in enumerate(voices[:10], 1):
            print(f"  {i}. {vname}")

        do_test = input("Test voices? [n/J]: ").strip().lower()
        if do_test != "n":
            voice_id = voice_test("elevenlabs", voices[:3], speed_str, source_file, api_key)
        else:
            val      = input(t("elevenlabs_select", n=min(10, len(voices)))).strip() or "1"
            idx      = int(val) - 1 if val.isdigit() else 0
            voice_id = voices[idx][0]

        return "elevenlabs", voice_id, speed_str, speed_float

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_folder = Path(sys.argv[1])
    if not input_folder.is_dir():
        log.error(f"Folder not found: {input_folder}")
        sys.exit(1)

    # Find files
    files     = find_files(input_folder, recursive=False)
    files_sub = find_files(input_folder, recursive=True)
    extra     = len(files_sub) - len(files)

    if extra > 0:
        print(f"\nFound {len(files)} file(s) in folder and {extra} in subfolders.")
        answer = input(t("search_subfolders")).strip().lower()
        if answer == "j":
            files = files_sub

    if not files:
        log.info(t("no_files"))
        return

    # File selection
    files = select_files(files)
    if not files:
        log.info(t("no_files_selected"))
        return

    # Count characters
    total_chars = 0
    for f in files:
        try:
            total_chars += len(extract_text(f))
        except:
            pass

    # Language selection
    print("\n── Language ──────────────────────────────────────────")
    lang_input = input(t("language_input")).strip().lower()
    language   = LANGUAGE_MAP.get(lang_input, lang_input) if lang_input else "sv"
    print(f"  Selected: {language}")

    # Engine/voice selection (skip voice test for batch)
    source_for_test = files[0] if len(files) == 1 else None
    if len(files) > 1:
        print(t("voice_test_skipped"))

    engine, voice_id, speed_str, speed_float = select_engine_and_voice(language, source_for_test)

    # ElevenLabs quota check
    if engine == "elevenlabs":
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        ok, remaining = check_elevenlabs_quota(api_key)
        print(f"\n── ElevenLabs quota ──────────────────────────────────")
        print(f"  This batch:      ~{total_chars:,} characters")
        if ok:
            print(f"  Remaining quota:  {remaining:,} characters")
            if total_chars > remaining:
                print(f"  WARNING: Batch exceeds your quota!")
            elif total_chars > remaining * 0.8:
                print(f"  NOTE: Batch uses >80% of remaining quota.")
        else:
            print(f"  Could not check quota – verify manually at elevenlabs.io")
        print(f"  NOTE: We cannot know how much you have used so far this month.")
        answer = input(t("elevenlabs_continue")).strip().lower()
        if answer != "j":
            print(t("elevenlabs_cancelled"))
            return

    # Save settings to state
    try:
        import json as _json
        state = {}
        if STATE_FILE.exists():
            state = _json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state["narrate_settings"] = {
            "engine": engine, "voice": voice_id,
            "speed": speed_str, "language": language
        }
        STATE_FILE.write_text(_json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except:
        pass

    log.info(f"clio-narrate-batch v{__version__}")
    log.info(f"Engine: {engine} | Voice: {voice_id} | Speed: {speed_str}")
    log.info(f"Starting batch – {len(files)} file(s) | ~{total_chars:,} characters")
    log.info(f"Folder: {input_folder}")
    log.info("-" * 60)

    succeeded = failed = skipped = 0
    total_start = time.time()

    for file in files:
        log.info(f"Processing: {file.name}")
        output_file = file.parent / f"{file.stem}{NARRATE_SUFFIX}.mp3"

        if output_file.exists():
            log.info(f"  Skipping – file already exists: {output_file.name}")
            skipped += 1
            continue

        text = extract_text(file)
        if not text.strip():
            log.warning(f"  No text found.")
            failed += 1
            continue

        log.info(f"  Text: {len(text):,} characters")
        start = time.time()

        if engine == "piper":
            ok, msg = narrate_piper(text, output_file, voice_id, speed_str)
        elif engine == "edge":
            ok, msg = narrate_edge(text, output_file, voice_id, speed_str)
        else:
            ok, msg = narrate_elevenlabs(text, output_file, voice_id, speed_float)

        elapsed = time.time() - start
        if ok:
            tag_mp3(output_file,
                title=file.stem,
                artist=voice_id.split("-")[-1] if "-" in voice_id else voice_id,
                album=input_folder.name,
                comment=f"{engine} {voice_id} {speed_str} {datetime.now().strftime('%Y-%m-%d')}",
                language="swe" if language == "sv" else language,
                track=f"{succeeded + skipped + 1}/{len(files)}",
            )
            log.info(f"  {msg} ({elapsed:.0f}s)")
            succeeded += 1
        else:
            log.error(f"  {msg}")
            failed += 1

    total = time.time() - total_start
    log.info("-" * 60)
    log.info(f"Done in {total:.0f}s – Succeeded: {succeeded} | Skipped: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    try:
        import mutagen
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "mutagen"], check=True)
    main()
