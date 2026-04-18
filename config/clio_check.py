"""
clio_check.py
Environment check and setup for clio-tools.
Detects OS, checks dependencies, installs what it can, guides manual steps.

Usage:
    python config/clio_check.py
"""

import sys
import os
import json
import shutil
import platform
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

__version__ = "2.0.1"

STATE_FILE = Path(__file__).parent / "clio_state.json"

# ── Colors ────────────────────────────────────────────────────────────────────

OK  = "\033[92mOK\033[0m"
WAR = "\033[93mVARNING\033[0m"
ERR = "\033[91mERROR\033[0m"
GUL = "\033[93m"
GRÖ = "\033[92m"
NOR = "\033[0m"

# ── OS detection ──────────────────────────────────────────────────────────────

def detect_os() -> str:
    """Returns 'windows', 'mac', or 'linux'."""
    s = platform.system().lower()
    if s == "windows":
        return "windows"
    elif s == "darwin":
        return "mac"
    return "linux"

OS = detect_os()

# ── State ─────────────────────────────────────────────────────────────────────

def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except:
        return {}

def save_state(state: dict):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except:
        pass

# ── pip install helper ────────────────────────────────────────────────────────

def pip_install(package: str, quiet: bool = True) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", package]
    if quiet:
        cmd.append("-q")
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 and OS == "linux":
        # Ubuntu 23.04+ blockerar pip utan --break-system-packages
        cmd_bsp = cmd + ["--break-system-packages"]
        result = subprocess.run(cmd_bsp, capture_output=True)
    return result.returncode == 0

# ── Manual install instructions ───────────────────────────────────────────────

INSTALL_INSTRUCTIONS = {
    "tesseract": {
        "windows": "Download from https://github.com/UB-Mannheim/tesseract/wiki\n"
                   "         Choose 64-bit installer, check 'swe' language pack during install.\n"
                   "         Default path: C:\\Program Files\\Tesseract-OCR\\",
        "mac":     "brew install tesseract tesseract-lang",
        "linux":   "sudo apt install tesseract-ocr tesseract-ocr-swe tesseract-ocr-eng",
    },
    "ffmpeg": {
        "windows": "winget install ffmpeg\n"
                   "         Or: https://ffmpeg.org/download.html (add to PATH after install)",
        "mac":     "brew install ffmpeg",
        "linux":   "sudo apt install ffmpeg",
    },
    "exiftool": {
        "windows": "Download exiftool.exe from https://exiftool.org\n"
                   "         Rename 'exiftool(-k).exe' to 'exiftool.exe'\n"
                   "         Copy to C:\\Windows\\System32\\",
        "mac":     "brew install exiftool",
        "linux":   "sudo apt install libimage-exiftool-perl",
    },
    "git": {
        "windows": "winget install Git.Git\n"
                   "         Or: https://git-scm.com/download/win",
        "mac":     "brew install git",
        "linux":   "sudo apt install git",
    },
}

def print_install_instruction(tool: str):
    instr = INSTALL_INSTRUCTIONS.get(tool, {}).get(OS, "See tool documentation.")
    for i, line in enumerate(instr.split("\n")):
        prefix = "         " if i > 0 else "       → "
        print(f"{prefix}{line}")

# ── Checks ────────────────────────────────────────────────────────────────────

def check_python() -> bool:
    ver = sys.version_info[:2]
    ok = ver >= (3, 12)
    status = OK if ok else ERR
    print(f"  [{status}] Python {ver[0]}.{ver[1]} (requires 3.12+)")
    return ok


def check_pip_packages(auto_fix: bool = False) -> bool:
    REQUIRED = [
        ("ocrmypdf",      "16.0.0"),
        ("pillow",        "10.0.0"),
        ("pytesseract",   "0.3.10"),
        ("pypdf",         "4.0.0"),
        ("pymupdf",       "1.23.0"),
        ("faster-whisper","1.0.0"),
        ("yt-dlp",        "2024.1.0"),
        ("feedparser",    "6.0.0"),
        ("qdrant-client", "1.7.0"),
        ("openai",        "1.0.0"),
        ("pyyaml",        "6.0.0"),
        ("edge-tts",      "6.0.0"),
        ("mutagen",       "1.45.0"),
        ("python-docx",   "0.8.11"),
        ("pyexiftool",    "0.5.0"),
        ("python-dotenv", "1.0.0"),
        ("notion-client", "2.0.0"),
        ("anthropic",     "0.25.0"),
    ]

    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True, text=True
    )
    try:
        installed = {p["name"].lower(): p["version"] for p in json.loads(result.stdout)}
    except:
        installed = {}

    def ver_ok(inst, req):
        try:
            return tuple(int(x) for x in inst.split(".")[:3]) >= \
                   tuple(int(x) for x in req.split(".")[:3])
        except:
            return False

    all_ok = True
    for name, min_ver in REQUIRED:
        inst = installed.get(name.lower().replace("-", "_")) or installed.get(name.lower())
        if not inst:
            print(f"  [{ERR}] {name} – missing (requires {min_ver}+)")
            all_ok = False
            if auto_fix:
                print(f"       Installing {name}...", end="", flush=True)
                ok = pip_install(name)
                print(" done" if ok else " FAILED")
        elif not ver_ok(inst, min_ver):
            print(f"  [{WAR}] {name} {inst} – too old (requires {min_ver}+)")
            all_ok = False
            if auto_fix:
                print(f"       Upgrading {name}...", end="", flush=True)
                ok = pip_install(f"{name} --upgrade")
                print(" done" if ok else " FAILED")
        else:
            print(f"  [{OK}] {name} {inst}")
    return all_ok


def check_tesseract() -> bool:
    # Find tesseract
    paths = {
        "windows": [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"],
        "mac":     ["/usr/local/bin/tesseract", "/opt/homebrew/bin/tesseract"],
        "linux":   ["/usr/bin/tesseract"],
    }
    tess_cmd = shutil.which("tesseract")
    if not tess_cmd:
        for p in paths.get(OS, []):
            if Path(p).exists():
                tess_cmd = p
                break

    if not tess_cmd:
        print(f"  [{ERR}] Tesseract – not found")
        print_install_instruction("tesseract")
        return False

    result = subprocess.run([tess_cmd, "--version"], capture_output=True, text=True, errors="replace")
    ver_str = (result.stdout or result.stderr or "").splitlines()[0] if (result.stdout or result.stderr) else "unknown"
    print(f"  [{OK}] Tesseract – {ver_str.strip()}")

    # Check language packs
    tessdata = Path(tess_cmd).parent / "tessdata"
    all_ok = True
    for lang in ["swe", "eng"]:
        if (tessdata / f"{lang}.traineddata").exists():
            print(f"  [{OK}] Tesseract language: {lang}")
        else:
            print(f"  [{WAR}] Tesseract language missing: {lang}")
            if OS == "windows":
                print(f"       Copy {lang}.traineddata to {tessdata}")
            else:
                pkg = "tesseract-ocr-swe" if lang == "swe" else "tesseract-ocr-eng"
                print(f"       sudo apt install {pkg}")
            all_ok = False
    return all_ok


def check_ffmpeg() -> bool:
    cmd = shutil.which("ffmpeg")
    if cmd:
        result = subprocess.run([cmd, "-version"], capture_output=True, text=True, errors="replace")
        ver = result.stdout.splitlines()[0] if result.stdout else "unknown"
        print(f"  [{OK}] ffmpeg – {ver[:50]}")
        return True
    print(f"  [{WAR}] ffmpeg – not found (needed for MP3 output in clio-narrate)")
    print_install_instruction("ffmpeg")
    return False


def check_exiftool() -> bool:
    cmd = shutil.which("exiftool")
    if not cmd and OS == "windows":
        if Path(r"C:\Windows\System32\exiftool.exe").exists():
            cmd = r"C:\Windows\System32\exiftool.exe"
    if cmd:
        result = subprocess.run([cmd, "-ver"], capture_output=True, text=True, errors="replace")
        ver = result.stdout.strip() or result.stderr.strip()
        print(f"  [{OK}] exiftool {ver}")
        return True
    print(f"  [{WAR}] exiftool – not found (needed for image metadata in clio-vision)")
    print_install_instruction("exiftool")
    return False


def check_git() -> bool:
    cmd = shutil.which("git")
    if cmd:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True)
        print(f"  [{OK}] {result.stdout.strip()}")
        return True
    print(f"  [{WAR}] git – not found (recommended)")
    print_install_instruction("git")
    return False


# ── Ollama ───────────────────────────────────────────────────────────────────

def check_ollama() -> bool:
    import urllib.request
    import urllib.error

    # 1. Installerad?
    ollama_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    ollama_cmd  = shutil.which("ollama") or (str(ollama_path) if ollama_path.exists() else None)
    if not ollama_cmd:
        print(f"  [{WAR}] Ollama – inte installerat (krävs för lokal vision)")
        print(f"       → https://ollama.com/download")
        return False

    # 2. Kör?
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        print(f"  [{WAR}] Ollama – installerat men inte igång")
        print(f"       → Starta med: ollama serve")
        return False

    # 3. Modeller installerade?
    models = [m["name"] for m in data.get("models", [])]
    if not models:
        print(f"  [{ERR}] Ollama – igång men INGA modeller installerade")
        print(f"       → Kör: ollama pull llava")
        return False

    vision_models = [m for m in models if any(v in m for v in ("llava", "vision", "bakllava", "moondream"))]
    if not vision_models:
        print(f"  [{WAR}] Ollama – inga vision-modeller (llava saknas)")
        print(f"       Installerade: {', '.join(models)}")
        print(f"       → Kör: ollama pull llava")
    else:
        print(f"  [{OK}] Ollama – igång, vision-modell: {', '.join(vision_models)}")
    if len(models) > len(vision_models):
        others = [m for m in models if m not in vision_models]
        print(f"  [{OK}] Ollama – övriga modeller: {', '.join(others)}")
    return bool(vision_models)


# ── GPU detection ─────────────────────────────────────────────────────────────

def detect_gpu() -> dict:
    info = {"cuda": False, "cuda_version": None, "gpu_name": None,
            "backend": "faster-whisper-cpu", "device": "cpu"}
    try:
        import torch
        if torch.cuda.is_available():
            info["cuda"] = True
            info["cuda_version"] = torch.version.cuda
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["backend"] = "faster-whisper-gpu"
            info["device"] = "cuda"
    except ImportError:
        nvidia = shutil.which("nvidia-smi")
        if nvidia:
            r = subprocess.run([nvidia, "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, text=True, errors="replace")
            if r.returncode == 0 and r.stdout.strip():
                info["gpu_name"] = r.stdout.strip().splitlines()[0]
                info["backend"] = "faster-whisper-gpu"
                info["device"] = "cuda"
    return info


def check_gpu() -> dict:
    info = detect_gpu()
    if info["cuda"]:
        print(f"  [{OK}] GPU: {info['gpu_name']} (CUDA {info['cuda_version']})")
        print(f"  [{OK}] Whisper backend: faster-whisper (GPU)")
    elif info["gpu_name"]:
        print(f"  [{WAR}] GPU found: {info['gpu_name']} – CUDA not available via PyTorch")
        print(f"       PyTorch stöder inte Python 3.14 ännu (stöds för 3.9–3.12).")
        print(f"       Installera Python 3.12 parallellt: https://www.python.org/downloads/release/python-3120/")
        print(f"       Välj 'Windows installer (64-bit)'. Kryssa i 'Add to PATH' om du vill.")
        print(f"       Kör sedan med py -3.12: py -3.12 -m pip install torch --index-url https://download.pytorch.org/whl/cu121")
        print(f"  [{WAR}] Whisper backend: faster-whisper (CPU) until PyTorch is installed")
    else:
        print(f"  [{OK}] No GPU detected – Whisper will run on CPU")
        print(f"  [{OK}] Whisper backend: faster-whisper (CPU)")
    return info


def check_api_keys():
    anthropic = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic and anthropic.startswith("sk-ant-"):
        print(f"  [{OK}] ANTHROPIC_API_KEY set ({anthropic[:12]}...)")
    else:
        print(f"  [{WAR}] ANTHROPIC_API_KEY missing – needed for clio-vision")
        if OS == "windows":
            print(f"       setx ANTHROPIC_API_KEY sk-ant-...")
        else:
            print(f"       export ANTHROPIC_API_KEY=sk-ant-...")

    elevenlabs = os.environ.get("ELEVENLABS_API_KEY", "")
    if elevenlabs:
        print(f"  [{OK}] ELEVENLABS_API_KEY set")
    else:
        print(f"  [{WAR}] ELEVENLABS_API_KEY missing – optional, needed for ElevenLabs TTS")


# ── Voice samples ─────────────────────────────────────────────────────────────

def tagga_mp3(fil, title: str, artist: str, album: str = "clio-tools",
              genre: str = "Audiobook", comment: str = "", language: str = "swe"):
    try:
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, COMM, TLAN, ID3NoHeaderError
        try:
            tags = ID3(str(fil))
        except ID3NoHeaderError:
            tags = ID3()
        tags["TIT2"] = TIT2(encoding=3, text=title)
        tags["TPE1"] = TPE1(encoding=3, text=artist)
        tags["TALB"] = TALB(encoding=3, text=album)
        tags["TCON"] = TCON(encoding=3, text=genre)
        tags["TLAN"] = TLAN(encoding=3, text=language)
        if comment:
            tags["COMM"] = COMM(encoding=3, lang="swe", desc="", text=comment)
        tags.save(str(fil))
    except:
        pass


def _ledigt_diskutrymme_gb(path) -> float:
    return shutil.disk_usage(path).free / 1_073_741_824


def generate_voice_samples(silent: bool = False):
    voice_dir = Path(__file__).parent / "voice-samples"
    voice_dir.mkdir(exist_ok=True)

    SAMPLE_TEXT = (
        "Sofie säger: Det tysta ögonblicket bär ofta mer sanning än tusen ord. "
        "Mattias säger: Den som lyssnar noga hör mer än den som talar högt."
    )
    SPEEDS = [("-20%", "slow"), ("+0%", "normal"), ("+15%", "fast")]
    EDGE_VOICES = [
        ("sv-SE-SofieNeural",   "Sofie_sv"),
        ("sv-SE-MattiasNeural", "Mattias_sv"),
    ]
    PIPER_VOICES = [
        ("sv-nst",  "NST_sv"),
        ("sv-lisa", "Lisa_sv"),
    ]

    generated = 0

    # Edge-TTS samples
    try:
        import asyncio, edge_tts

        async def _edge(text, voice, rate, path):
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(str(path))

        for voice_id, name in EDGE_VOICES:
            for rate, speed_name in SPEEDS:
                out = voice_dir / f"{name}_{speed_name}.mp3"
                if not out.exists():
                    if not silent:
                        print(f"  Generating: {name} ({speed_name})...")
                    try:
                        asyncio.run(_edge(SAMPLE_TEXT, voice_id, rate, out))
                        tagga_mp3(out,
                            title=f"Voice sample – {name} ({speed_name})",
                            artist=name.split("_")[0],
                            comment=f"Edge-TTS {voice_id} {rate}")
                        generated += 1
                    except Exception as e:
                        if not silent:
                            print(f"  [{WAR}] {name} ({speed_name}): {e}")
    except ImportError:
        if not silent:
            print(f"  [{WAR}] edge-tts missing – run 'pip install edge-tts'")

    # Piper samples
    piper_missing = [n for _, n in PIPER_VOICES
                     if not (voice_dir / f"{n}_normal.mp3").exists()]
    if piper_missing and not silent:
        free_gb = _ledigt_diskutrymme_gb(voice_dir)
        print(f"\n  Piper voices missing (~60 MB/voice, {len(piper_missing)} voices = ~{len(piper_missing)*60} MB)")
        print(f"  Free disk space: {free_gb:.1f} GB")
        ans = input("  Download Piper voices? [J/n]: ").strip().lower()
        download_piper = ans != "n"
    else:
        download_piper = False

    if download_piper:
        PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
        PIPER_MODELS = {
            "sv-nst":  ("sv/sv_SE/nst/medium",  "sv_SE-nst-medium"),
            "sv-lisa": ("sv/sv_SE/lisa/medium", "sv_SE-lisa-medium"),
        }
        piper_dir = Path(__file__).parent / "piper-voices"
        piper_dir.mkdir(exist_ok=True)
        import urllib.request

        for voice_key, name in PIPER_VOICES:
            out = voice_dir / f"{name}_normal.mp3"
            if out.exists():
                continue
            url_path, file_base = PIPER_MODELS[voice_key]
            onnx = piper_dir / f"{file_base}.onnx"
            json_f = piper_dir / f"{file_base}.onnx.json"

            for src, dst in [
                (f"{PIPER_URL}/{url_path}/{file_base}.onnx?download=true", onnx),
                (f"{PIPER_URL}/{url_path}/{file_base}.onnx.json?download=true", json_f),
            ]:
                if not dst.exists():
                    if not silent:
                        print(f"  Downloading {dst.name}...")
                    try:
                        urllib.request.urlretrieve(src, str(dst))
                    except Exception as e:
                        if not silent:
                            print(f"  [{WAR}] Download failed: {e}")
                        break

            if onnx.exists() and json_f.exists():
                try:
                    import json as _json, wave, io
                    from piper.voice import PiperVoice
                    if not silent:
                        print(f"  Generating Piper sample: {name}...")
                    cfg = _json.loads(json_f.read_text(encoding="utf-8"))
                    sample_rate = cfg.get("audio", {}).get("sample_rate", 22050)
                    voice_obj = PiperVoice.load(str(onnx))
                    wav_out = voice_dir / f"{name}_normal.wav"
                    with wave.open(str(wav_out), 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        buf = io.BytesIO()
                        with wave.open(buf, 'wb') as tmp:
                            tmp.setnchannels(1)
                            tmp.setsampwidth(2)
                            tmp.setframerate(sample_rate)
                            voice_obj.synthesize(SAMPLE_TEXT, tmp)
                        buf.seek(44)
                        wf.writeframes(buf.read())
                    if shutil.which("ffmpeg"):
                        subprocess.run(["ffmpeg", "-y", "-i", str(wav_out),
                                       "-codec:a", "libmp3lame", "-q:a", "4", str(out)],
                                      capture_output=True)
                        wav_out.unlink(missing_ok=True)
                    else:
                        wav_out.rename(out.with_suffix('.wav'))
                    if out.exists():
                        tagga_mp3(out, title=f"Voice sample – {name}", artist=name.split("_")[0],
                                  comment=f"Piper {file_base}")
                        generated += 1
                except ModuleNotFoundError:
                    if not silent:
                        print(f"  [{WAR}] Piper saknas — installera med:")
                        print(f"       pip install piper-tts")
                        print(f"       OBS: piper-tts kräver Python 3.9–3.12.")
                        print(f"       Om du kör Python 3.14: py -3.12 -m pip install piper-tts")
                    break
                except Exception as e:
                    if not silent:
                        print(f"  [{WAR}] Piper sample failed: {e}")

    total = len(list(voice_dir.glob("*.mp3")))
    if not silent:
        if generated > 0:
            print(f"  [{OK}] {generated} new samples generated ({total} total in {voice_dir})")
        else:
            print(f"  [{OK}] All samples already generated ({total} files in {voice_dir})")


# ── Timeout input ─────────────────────────────────────────────────────────────

def input_with_timeout(prompt: str, timeout: int = 5) -> str:
    result = [""]
    stop = threading.Event()

    def countdown():
        for i in range(timeout, 0, -1):
            if stop.is_set():
                return
            print(f"\r{prompt}({i}s) ", end="", flush=True)
            time.sleep(1)
        stop.set()

    def read():
        try:
            result[0] = input()
        except:
            pass
        stop.set()

    threading.Thread(target=read, daemon=True).start()
    threading.Thread(target=countdown, daemon=True).start()
    stop.wait(timeout + 1)
    return result[0].strip().lower()


# ── Main check ────────────────────────────────────────────────────────────────

def check_environment(auto_fix: bool = False, silent: bool = False) -> bool:
    if not silent:
        print(f"\nclio_check v{__version__} – Environment check ({OS})")
        print("=" * 56)
        print("\nPython:")
    py_ok = check_python()

    if not silent:
        print("\nPip packages:")
    pip_ok = check_pip_packages(auto_fix=auto_fix)

    if not silent:
        print("\nTesseract OCR:")
    tess_ok = check_tesseract()

    if not silent:
        print("\nffmpeg:")
    ffmpeg_ok = check_ffmpeg()

    if not silent:
        print("\nexiftool:")
    check_exiftool()

    if not silent:
        print("\nGPU / Whisper backend:")
    gpu_info = check_gpu()

    if not silent:
        print("\nGit:")
    check_git()

    if not silent:
        print("\nOllama (clio-vision lokal motor):")
    check_ollama()

    if not silent:
        print("\nAPI keys:")
    check_api_keys()

    # Save hardware info to state
    state = read_state()
    state["hw"] = {
        "gpu": gpu_info.get("gpu_name"),
        "cuda": gpu_info.get("cuda"),
        "backend": gpu_info.get("backend"),
        "device": gpu_info.get("device"),
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    save_state(state)

    all_ok = py_ok and pip_ok and tess_ok
    if not silent:
        print("\n" + "=" * 56)
        if all_ok:
            print(f"[{OK}] Environment ready.")
        else:
            print(f"[{ERR}] Fix the issues above before running clio-tools.")
        print()

    if not silent:
        print("Voice samples (clio-narrate):")
    generate_voice_samples(silent=silent)

    return all_ok


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print(f"\nclio_check v{__version__}")
    print(f"Platform: {platform.system()} {platform.release()}")
    print("Checking clio-tools environment...\n")

    ok = check_environment(auto_fix=False)

    if not ok:
        ans = input_with_timeout(
            "\nAttempt automatic fix of pip packages? [J/n]: ",
            timeout=5
        )
        if ans != "n":
            print("\nFixing pip packages...\n")
            check_pip_packages(auto_fix=True)


if __name__ == "__main__":
    main()
