"""
clio_vision.py
Analyzes images using Claude Vision API or Ollama (local).
Produces a MD file per image with description, tags and metadata.

Supported formats: jpg, jpeg, png, webp, gif

Usage:
    python clio_vision.py <input-folder>

Example:
    python clio_vision.py "C:\\Users\\fredr\\Pictures\\Archive"

Output per image:
    - imagename_VISION.md – description, tags, master data
    - clio_vision.log – log file in script folder

Environment:
    ANTHROPIC_API_KEY  – required for Claude Vision engine
"""

import sys
import io
import re
import os

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import time
import base64
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime

# Load .env from repo root (clio-tools/.env)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).parent.parent / ".env", override=True)
except ImportError:
    pass  # python-dotenv not installed; fall back to os.environ

from clio_core.utils import sanitize_filename, t

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "2.0.1"

VISION_SUFFIX    = "_VISION"
SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
LOG_FILE         = Path(__file__).parent / "clio_vision.log"
API_URL          = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL     = "claude-sonnet-4-20250514"
CLAUDE_HAIKU     = "claude-haiku-4-5-20251001"
OLLAMA_MODEL     = "llava"  # Default Ollama vision model
MAX_TOKENS       = 1500
EXIFTOOL_EXE     = Path(__file__).parent / "exiftool-13.54_64" / "exiftool.exe"
MAX_DIMENSION    = {          # longest side in pixels — optimal per engine
    "claude": 1568,           # Anthropic internal cap, beyond this = wasted tokens
    "haiku":  1568,
    "ollama": 1024,
}

SYSTEM_PROMPT = """Du är ett arkiveringsverktyg som analyserar bilder och extraherar strukturerad metadata.

Svara alltid på svenska och använd detta exakta JSON-format utan backticks eller förklaringar:
{
  "description": "En detaljerad beskrivning av vad bilden visar (2-4 meningar)",
  "tags": ["tagg1", "tagg2", "tagg3"],
  "masterdata": {
    "location": "Plats om känd, annars null",
    "date": "Datum eller tidsperiod om känt, annars null",
    "people": ["namn1", "namn2"],
    "objects": ["objekt1", "objekt2"],
    "text_in_image": "Eventuell text som syns i bilden, annars null",
    "category": "Ett av: fotografi, illustration, dokument, karta, diagram, skärmbild, annat",
    "quality": "Ett av: hög, medel, låg"
  }
}"""

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

# ── Claude Vision API ─────────────────────────────────────────────────────────

def analyze_with_claude(image_file: Path, api_key: str, model: str = CLAUDE_MODEL) -> tuple:
    try:
        import urllib.request, urllib.error

        image_bytes = image_file.read_bytes()
        image_b64   = base64.standard_b64encode(image_bytes).decode("utf-8")

        media_types = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png",  ".webp": "image/webp",
            ".gif": "image/gif",
        }
        media_type = media_types.get(image_file.suffix.lower(), "image/jpeg")

        payload = json.dumps({
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": image_b64
                    }},
                    {"type": "text", "text": "Analyze this image and return structured metadata in JSON format."}
                ]
            }]
        }).encode("utf-8")

        req = urllib.request.Request(API_URL, data=payload, headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }, method="POST")

        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        text = result["content"][0]["text"].strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        data = json.loads(text)
        return True, data, "OK"

    except Exception as e:
        return False, {}, f"Claude API error: {e}"


# ── Ollama (local) ────────────────────────────────────────────────────────────

def list_ollama_models() -> list:
    """Returns list of installed Ollama model names, or empty list on error."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def warmup_ollama(model: str = OLLAMA_MODEL, retries: int = 5, wait: int = 15) -> bool:
    """Pre-load Ollama model into memory. Retries with delay if Ollama is recovering.
    Returns True on success, False if all attempts fail."""
    import urllib.request
    import urllib.error

    # Snabbkontroll: om inga modeller alls → ge direkt, meningslöst att vänta
    models = list_ollama_models()
    if not models:
        log.error("Inga Ollama-modeller installerade. Kör: ollama pull llava")
        return False
    if model not in models and not any(m.startswith(model) for m in models):
        log.error(f"Modellen '{model}' hittades inte i Ollama. Installerade: {', '.join(models)}")
        log.error(f"Kör: ollama pull {model}")
        return False

    payload = json.dumps({
        "model": model, "prompt": "ping", "stream": False, "keep_alive": -1,
    }).encode("utf-8")

    for attempt in range(1, retries + 1):
        try:
            log.info(f"Ollama: laddar {model} i RAM (kan ta 30–60s på CPU)...")
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            import threading, datetime as _dt
            _done = threading.Event()
            def _clock():
                start = _dt.datetime.now()
                while not _done.is_set():
                    elapsed = int((_dt.datetime.now() - start).total_seconds())
                    now = _dt.datetime.now().strftime("%H:%M:%S")
                    print(f"\r  ⏳ {now}  ({elapsed}s)   ", end="", flush=True)
                    _done.wait(1)
                print("\r" + " " * 30 + "\r", end="", flush=True)
            t = threading.Thread(target=_clock, daemon=True)
            t.start()
            with urllib.request.urlopen(req, timeout=300) as resp:
                resp.read()
            _done.set()
            t.join()
            log.info("Ollama model pre-loaded.")
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404 and attempt < retries:
                log.warning(f"Ollama warmup 404 (försök {attempt}/{retries}) — väntar {wait}s för att Ollama ska återhämta sig...")
                time.sleep(wait)
            else:
                log.warning(f"Ollama warmup misslyckades: {e}")
                return False
        except Exception as e:
            log.warning(f"Ollama warmup misslyckades: {e}")
            return False
    return False


def analyze_with_ollama(image_file: Path, model: str = OLLAMA_MODEL) -> tuple:
    import urllib.request
    import urllib.error

    def _do_request(image_file: Path, model: str) -> tuple:
        image_bytes = image_file.read_bytes()
        image_b64   = base64.standard_b64encode(image_bytes).decode("utf-8")

        payload = json.dumps({
            "model": model,
            "prompt": "Analysera denna bild på svenska. Returnera ENDAST giltig JSON: {\"description\": \"...\", \"tags\": [], \"masterdata\": {\"location\": null, \"date\": null, \"people\": [], \"objects\": [], \"text_in_image\": null, \"category\": \"photograph\", \"quality\": \"medium\"}}",
            "images": [image_b64],
            "stream": False,
            "keep_alive": -1,
            "format": "json",
            "options": {
                "num_predict": 400,
                "num_ctx": 2048,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read().decode("utf-8")

        # Ollama returnerar ibland NDJSON (ett JSON-objekt per rad) trots stream=False.
        # Försök single-parse först; faller tillbaka på rad-för-rad-ackumulering.
        try:
            result = json.loads(raw)
            text = result.get("response", "").strip()
        except json.JSONDecodeError:
            parts = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    parts.append(chunk.get("response", ""))
                except json.JSONDecodeError:
                    pass
            text = "".join(parts).strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return True, data, "OK"
        return False, {}, "No JSON in Ollama response"

    try:
        return _do_request(image_file, model)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.warning("Ollama 404 — Ollama verkar ha kraschat. Väntar på återhämtning (warmup med retry)...")
            ok = warmup_ollama(model)
            if ok:
                try:
                    return _do_request(image_file, model)
                except Exception as retry_e:
                    return False, {}, f"Ollama error (efter retry): {retry_e}"
            return False, {}, "Ollama ej tillgänglig efter warmup-retry — hoppar över bilden"
        return False, {}, f"Ollama error: {e}"
    except Exception as e:
        return False, {}, f"Ollama error: {e}"

# ── DigiKam XMP metadata ──────────────────────────────────────────────────────

def read_digikam_metadata(image_file: Path) -> dict:
    """Reads face tags, other metadata written by DigiKam, and EXIF dates via exiftool."""
    meta = {"people": [], "tags": [], "rating": None, "exif_date": None}
    try:
        import exiftool
        with exiftool.ExifToolHelper(executable=str(EXIFTOOL_EXE)) as et:
            data = et.get_metadata(str(image_file))[0]
            # DigiKam face regions
            regions = data.get("XMP:RegionName", [])
            if isinstance(regions, str):
                regions = [regions]
            meta["people"] = [r for r in regions if r]
            # Tags
            subjects = data.get("XMP:Subject") or data.get("IPTC:Keywords") or []
            if isinstance(subjects, str):
                subjects = [subjects]
            meta["tags"] = [t for t in subjects if t]
            # Rating
            meta["rating"] = data.get("XMP:Rating") or data.get("EXIF:Rating")
            # EXIF date (when shutter clicked)
            date_str = data.get("EXIF:DateTimeOriginal") or data.get("EXIF:CreateDate")
            if date_str:
                try:
                    meta["exif_date"] = datetime.strptime(str(date_str)[:19], "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass
    except:
        pass
    return meta


def _parse_date_from_filename(stem: str):
    """Tries to extract a date from common filename patterns. Returns datetime or None."""
    patterns = [
        r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})",  # 20190604, 2019-06-04, 2019_06_04
    ]
    for pat in patterns:
        m = re.search(pat, stem)
        if m:
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                    return datetime(y, mo, d)
            except ValueError:
                pass
    return None


def check_dates(image_file: Path, meta: dict) -> list:
    """Checks date consistency across EXIF, filename, and filesystem. Returns list of warnings."""
    warnings = []
    exif_date = meta.get("exif_date")
    filename_date = _parse_date_from_filename(image_file.stem)
    now = datetime.now()

    try:
        mtime = datetime.fromtimestamp(image_file.stat().st_mtime)
    except OSError:
        mtime = None

    if exif_date:
        # EXIF date unreasonably old (before consumer digital cameras)
        if exif_date.year < 1990:
            warnings.append(f"EXIF-datum {exif_date.year} är före digitalkamerornas tid — kameraklockan troligen aldrig ställd")
        # EXIF date in the future
        elif exif_date > now:
            warnings.append(f"EXIF-datum {exif_date.date()} ligger i framtiden — kameraklockan troligen felställd")
        # mtime older than EXIF (physically impossible)
        if mtime and mtime.date() < exif_date.date():
            warnings.append(
                f"Filen modifierades ({mtime.date()}) innan EXIF-datumet ({exif_date.date()}) — datumen är inkonsekventa"
            )
        # Filename date vs EXIF date
        if filename_date and abs((exif_date - filename_date).days) > 1:
            warnings.append(
                f"Filnamnet antyder {filename_date.date()} men EXIF säger {exif_date.date()} — kontrollera"
            )
    elif filename_date:
        # Have filename date but no EXIF — just note it
        warnings.append(
            f"Inget EXIF-datum hittades. Filnamnet antyder {filename_date.date()}"
        )

    return warnings


def write_vision_metadata(image_file: Path, data: dict):
    """Writes vision analysis results back to image XMP metadata.

    DigiKam läser sedan dessa vid nästa 'Read metadata from files':
      - XMP:Subject         → nyckelord/taggar
      - XMP:Description     → bildtext/caption
      - XMP:Location        → plats
      - XMP:PersonInImage   → personer utan ansiktsregion (IPTC Ext)
    """
    try:
        import exiftool
        md = data.get("masterdata", {})
        tags = data.get("tags", []) if isinstance(data.get("tags"), list) else []
        people = md.get("people", []) if isinstance(md.get("people"), list) else []

        params = [
            "-P",                   # bevara filsystemets ändringstid
            "-overwrite_original",  # inga .jpg_original-backupfiler
        ]

        # Taggar → XMP:Subject (DigiKam-nyckelord)
        for tag in tags:
            if isinstance(tag, str) and tag.strip():
                params.append(f"-XMP:Subject+={tag.strip()}")

        # Plats
        if md.get("location") and isinstance(md["location"], str):
            params.append(f"-XMP:Location={md['location']}")

        # Beskrivning
        if data.get("description") and isinstance(data["description"], str):
            params.append(f"-XMP:Description={data['description']}")

        # Personer → XMP:Subject (som nyckelord) + XMP:PersonInImage
        for person in people:
            if isinstance(person, str) and person.strip():
                params.append(f"-XMP:Subject+={person.strip()}")
                params.append(f"-XMP-iptcExt:PersonInImage+={person.strip()}")

        if len(params) <= 2:  # bara -P och -overwrite_original, inget att skriva
            return

        with exiftool.ExifToolHelper(executable=str(EXIFTOOL_EXE)) as et:
            et.execute(*params, str(image_file))
    except Exception as e:
        log.debug(f"write_vision_metadata failed: {e}")

# ── Build MD output ───────────────────────────────────────────────────────────

def build_md(image_file: Path, data: dict, digikam: dict, analysis_date: str, date_warnings: list = None) -> str:
    def _str_list(items):
        """Coerce list items to strings (Ollama may return dicts, ints, or other non-list types)."""
        if not isinstance(items, (list, tuple)):
            return []  # Ollama returnerade int/str/None istället för lista — ignorera
        result = []
        for item in items:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                result.append(item.get("name") or item.get("value") or str(item))
            else:
                result.append(str(item))
        return result

    md   = data.get("masterdata", {})
    tags = list(set(_str_list(data.get("tags", [])) + digikam.get("tags", [])))
    desc = data.get("description", "")

    # Merge people from vision + DigiKam
    people = list(set(_str_list(md.get("people", [])) + digikam.get("people", [])))

    lines = []
    lines.append(f"# {image_file.stem}\n")
    lines.append(f"- **Source:** {image_file.name}")
    lines.append(f"- **Analysis date:** {analysis_date}")
    lines.append(f"- **Category:** {md.get('category', 'unknown')}")
    lines.append(f"- **Quality:** {md.get('quality', 'unknown')}")
    if digikam.get("rating"):
        lines.append(f"- **Rating:** {'★' * int(digikam['rating'])}")
    lines.append("")

    if tags:
        lines.append(f"**Tags:** {', '.join(tags)}\n")

    lines.append("---\n")
    lines.append("## Description\n")
    lines.append(desc)
    lines.append("\n---\n")
    lines.append("## Master data\n")

    if md.get("location"):
        lines.append(f"- **Location:** {md['location']}")
    if md.get("date"):
        lines.append(f"- **Date:** {md['date']}")
    if people:
        lines.append(f"- **People:** {', '.join(people)}")
    if md.get("objects"):
        lines.append(f"- **Objects:** {', '.join(_str_list(md['objects']))}")
    if md.get("text_in_image"):
        lines.append(f"\n**Text in image:**\n> {md['text_in_image']}")

    if date_warnings:
        lines.append("\n---\n")
        lines.append("## Datumvarningar\n")
        for w in date_warnings:
            lines.append(f"- {w}")

    lines.append("\n---\n")
    lines.append("## Raw data (JSON)\n")
    lines.append("```json")
    lines.append(json.dumps(data, ensure_ascii=False, indent=2))
    lines.append("```")

    return "\n".join(lines)

# ── File discovery ────────────────────────────────────────────────────────────

def is_local(path: Path) -> bool:
    """Returns False if the file is a Dropbox online-only (cloud-only) placeholder."""
    try:
        import ctypes
        FILE_ATTRIBUTE_OFFLINE     = 0x1000
        FILE_ATTRIBUTE_SPARSE_FILE = 0x0200
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:  # INVALID_FILE_ATTRIBUTES
            return True  # can't tell, assume local
        return not bool(attrs & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_SPARSE_FILE))
    except Exception:
        return True  # non-Windows or ctypes unavailable — assume local


def find_images(folder: Path, recursive: bool = False) -> list:
    if recursive:
        all_files = [p for p in folder.rglob("*") if p.suffix.lower() in SUPPORTED_FORMATS]
    else:
        all_files = [p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_FORMATS]
    return sorted([p for p in all_files if VISION_SUFFIX not in p.stem])

# ── Image resizing ───────────────────────────────────────────────────────────

def resize_for_api(image_file: Path, max_dim: int) -> Path | None:
    """Creates a resized JPEG temp copy with longest side <= max_dim px.
    Returns path to temp file, or None if already small enough / on error.
    Caller is responsible for deleting the temp file."""
    try:
        import tempfile
        from PIL import Image as _Image

        img = _Image.open(image_file).convert("RGB")
        w, h = img.size

        if max(w, h) <= max_dim:
            return None  # already fits — no temp needed

        scale = max_dim / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = img.resize((new_w, new_h), _Image.LANCZOS)

        tmp_path = image_file.parent / f"_clio_tmp_{image_file.stem}.jpg"
        resized.save(tmp_path, "JPEG", quality=85)
        return tmp_path

    except Exception as e:
        log.debug(f"resize_for_api failed: {e}")
        return None


# ── CLI / argparse ────────────────────────────────────────────────────────────

def parse_args(argv=None):
    """Parse CLI arguments. All interactive prompts can be bypassed via flags.

    Agent-ready usage (no prompts):
        python clio_vision.py <folder> --engine ollama --write-back --recursive --yes
    """
    import argparse
    p = argparse.ArgumentParser(
        description="clio-vision — analysera bilder med AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("folder", help="Mapp med bilder att analysera")
    p.add_argument(
        "--engine", choices=["claude", "haiku", "ollama"],
        help="Vision-motor (hoppar över interaktiv meny)",
    )
    p.add_argument(
        "--write-back", dest="write_back", action="store_true", default=None,
        help="Skriv taggar/beskrivning till bildens XMP-metadata",
    )
    p.add_argument(
        "--no-write-back", dest="write_back", action="store_false",
        help="Skriv inte till XMP-metadata",
    )
    p.add_argument(
        "--recursive", "-r", action="store_true", default=None,
        help="Inkludera undermappar",
    )
    p.add_argument(
        "--yes", "-y", action="store_true", default=False,
        help="Svara ja på alla bekräftelsefrågor (kostnad, etc.)",
    )
    return p.parse_args(argv)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    args = parse_args(argv)

    input_folder = Path(args.folder)
    if not input_folder.is_dir():
        log.error(f"Folder not found: {input_folder}")
        sys.exit(1)

    # Engine selection
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # Find ollama executable — check PATH first, then known Windows install location
    import shutil
    _ollama_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    _ollama_cmd  = str(_ollama_path) if _ollama_path.exists() else "ollama"
    ollama_installed = _ollama_path.exists() or shutil.which("ollama") is not None

    ollama_available = False
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        ollama_available = True
    except:
        pass

    # ── Engine: CLI-flagga eller interaktiv meny ──
    if args.engine:
        engine_choice = {"claude": "1", "haiku": "2", "ollama": "3"}[args.engine]
    else:
        print("\n── Vision engine ─────────────────────────────────────")
        if api_key:
            print("  1. Claude Sonnet  (bäst kvalitet, ~$0.02/bild)")
            print("  2. Claude Haiku   (bulk, ~$0.01/bild)")
        else:
            print("  1. Claude Sonnet  (ANTHROPIC_API_KEY not set)")
            print("  2. Claude Haiku   (ANTHROPIC_API_KEY not set)")
        if ollama_available:
            print("  3. Ollama         (lokalt, gratis, lägre kvalitet)")
        elif ollama_installed:
            print(f"  3. Ollama         (inte igång – starta med: {_ollama_cmd} serve)")
        else:
            print("  3. Ollama         (ej installerat – ladda ner: https://ollama.com/download)")
        default_engine = "1" if api_key else ("3" if ollama_available else "1")
        engine_choice = input(t("vision_engine_input", default=default_engine)).strip() or default_engine

    if engine_choice == "3":
        if not ollama_available:
            if ollama_installed:
                log.error(f"Ollama är inte igång. Starta med: {_ollama_cmd} serve")
            else:
                log.error("Ollama är inte installerat.")
                log.error("  Ladda ner: https://ollama.com/download")
                log.error("  Installera en modell: ollama pull llava")
                log.error("  Starta sedan: ollama serve")
            sys.exit(1)
        engine = "ollama"
        log.info(f"Engine: Ollama ({OLLAMA_MODEL})")
    elif engine_choice == "2" and api_key:
        engine = "haiku"
        log.info(f"Engine: Claude Haiku ({CLAUDE_HAIKU})")
    elif api_key:
        engine = "claude"
        log.info(f"Engine: Claude Sonnet ({CLAUDE_MODEL})")
    else:
        log.error("No vision engine available. Set ANTHROPIC_API_KEY or start Ollama.")
        sys.exit(1)

    # ── Undermappar: CLI-flagga eller interaktiv fråga ──
    images     = find_images(input_folder, recursive=False)
    images_sub = find_images(input_folder, recursive=True)
    extra      = len(images_sub) - len(images)

    if extra > 0:
        if args.recursive:
            images = images_sub
        elif args.recursive is None:  # inte satt via flagga → fråga
            print(f"\nFound {len(images)} image(s) in folder and {extra} in subfolders.")
            answer = input("Search subfolders too? [n/J]: ").strip().lower()
            if answer == "j":
                images = images_sub

    if not images:
        log.info("No images to process.")
        return

    # ── Filtrera bort redan analyserade bilder upfront ──
    already_done = [img for img in images if (img.parent / f"{img.stem}{VISION_SUFFIX}.md").exists()]
    images = [img for img in images if img not in set(already_done)]
    if already_done:
        log.info(f"Already analyzed: {len(already_done)} — skipping. {len(images)} remaining.")
    if not images:
        log.info("All images already analyzed.")
        return

    # ── Kostnadsgodkännande: --yes eller interaktiv bekräftelse ──
    if engine in ("claude", "haiku"):
        cost_per = 0.02 if engine == "claude" else 0.01
        model_name = "Claude Sonnet" if engine == "claude" else "Claude Haiku"
        est_cost = len(images) * cost_per
        if not args.yes:
            print(f"\n{len(images)} image(s) to analyze with {model_name}.")
            print(t("vision_cost_estimate", cost=est_cost))
            answer = input("Continue? [n/J]: ").strip().lower()
            if answer != "j":
                print("Cancelled.")
                return

    # ── Write-back: CLI-flagga eller interaktiv fråga ──
    if args.write_back is not None:
        write_back = args.write_back
    else:
        write_back = False
        try:
            import exiftool
            answer = input("Write tags back to image XMP metadata? [n/J]: ").strip().lower()
            write_back = answer == "j" or answer == ""
        except ImportError:
            pass

    analysis_date = datetime.now().strftime("%Y-%m-%d")
    log.info(f"clio-vision v{__version__}")
    log.info(f"Starting batch – {len(images)} image(s)")
    log.info(f"Folder: {input_folder}")
    log.info("-" * 60)

    if engine == "ollama":
        log.info("Pre-loading Ollama model...")
        warmup_ollama()

    succeeded = failed = skipped = 0
    total_start = time.time()

    for image in images:
        log.info(f"Processing: {image.name}")
        start = time.time()

        vision_file = image.parent / f"{image.stem}{VISION_SUFFIX}.md"
        if vision_file.exists():
            log.info(f"  Skipping – already analyzed: {vision_file.name}")
            skipped += 1
            continue

        if not is_local(image):
            log.info(f"  Skipping – Dropbox online-only (not downloaded): {image.name}")
            skipped += 1
            continue

        temp_file = None
        analyze_target = image

        try:
            max_dim = MAX_DIMENSION.get(engine, 1568)
            temp_file = resize_for_api(image, max_dim)
            if temp_file:
                orig_kb = image.stat().st_size // 1024
                tmp_kb  = temp_file.stat().st_size // 1024
                log.info(f"  Nedskalad: {orig_kb} KB → {tmp_kb} KB (max {max_dim}px)")
                analyze_target = temp_file

            # Read DigiKam metadata if available
            digikam = read_digikam_metadata(image)
            if digikam["people"]:
                log.info(f"  DigiKam faces: {', '.join(digikam['people'])}")

            # Analyze (always from analyze_target, write back to original image)
            if engine == "haiku":
                ok, data, message = analyze_with_claude(analyze_target, api_key, model=CLAUDE_HAIKU)
            elif engine == "claude":
                ok, data, message = analyze_with_claude(analyze_target, api_key)
            else:
                ok, data, message = analyze_with_ollama(analyze_target)

            elapsed = time.time() - start

            if ok:
                # Merge DigiKam data
                if digikam["people"]:
                    data.setdefault("masterdata", {})
                    raw = data["masterdata"].get("people", [])
                    existing = raw if isinstance(raw, list) else []
                    data["masterdata"]["people"] = existing
                    for person in digikam["people"]:
                        if person not in existing:
                            existing.append(person)

                date_warnings = check_dates(image, digikam)
                if date_warnings:
                    for w in date_warnings:
                        log.info(f"  Datumvarning: {w}")

                md_text = build_md(image, data, digikam, analysis_date, date_warnings)
                vision_file.write_text(md_text, encoding="utf-8")

                if write_back:
                    write_vision_metadata(image, data)

                size_kb = vision_file.stat().st_size / 1024
                log.info(f"  OK -> {vision_file.name} ({size_kb:.0f} KB, {elapsed:.0f}s)")
                succeeded += 1
            else:
                log.error(f"  {message} ({elapsed:.0f}s)")
                failed += 1

        except Exception as e:
            elapsed = time.time() - start
            log.error(f"  Oväntat fel: {e} ({elapsed:.0f}s)")
            failed += 1

        finally:
            # Always clean up temp file
            if temp_file and temp_file.exists():
                temp_file.unlink(missing_ok=True)

        # Brief pause to avoid rate limiting
        if len(images) > 1 and engine == "claude":
            time.sleep(0.5)

    total = time.time() - total_start
    log.info("-" * 60)
    log.info(f"Done in {total:.0f}s – Succeeded: {succeeded} | Skipped: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    main()
