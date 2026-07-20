"""
transcribe.py — Transkribering för clio-audio-edit.
Hanterar faster-whisper, RTF-kalibrering och tidsformatering.
"""

import threading
import time
from datetime import datetime
from pathlib import Path

from state import load_state, save_state

_GRN = "\033[92m"
_YEL = "\033[93m"
_CYN = "\033[96m"
_GRY = "\033[90m"
_BLD = "\033[1m"
_NRM = "\033[0m"


# ---------------------------------------------------------------------------
# Tidsformat
# ---------------------------------------------------------------------------

def format_timestamp(seconds: float) -> str:
    """Konverterar sekunder till HH:MM:SS"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_dur(seconds: float) -> str:
    """Kortare tidsformat för visning: '2 min 34 sek' eller '45 sek'."""
    s = int(seconds)
    if s < 60:
        return f"{s} sek"
    return f"{s // 60} min {s % 60:02d} sek"


# ---------------------------------------------------------------------------
# RTF-kalibrering (real-time factor per modell+språk)
# ---------------------------------------------------------------------------

def _perf_key(model_size: str, language: str) -> str:
    return f"rtf_{model_size}_{language}"


def _load_rtf(model_size: str, language: str) -> float | None:
    """Hämtar sparad RTF för modell+språk, eller None."""
    state = load_state()
    return state.get("audio_edit_perf", {}).get(_perf_key(model_size, language))


def _save_rtf(model_size: str, language: str, audio_sec: float, wall_sec: float) -> None:
    """Sparar RTF + historik i state efter avslutad körning."""
    state = load_state()
    perf = state.setdefault("audio_edit_perf", {})
    key  = _perf_key(model_size, language)
    rtf  = audio_sec / wall_sec

    perf[key] = round(rtf, 4)
    hist = perf.setdefault(f"{key}_history", [])
    hist.append({
        "date":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        "rtf":       round(rtf, 4),
        "audio_sec": round(audio_sec),
        "wall_sec":  round(wall_sec),
    })
    perf[f"{key}_history"] = hist[-10:]
    save_state(state)


def _spinner_run(label: str, fn, audio_sec: float, model_size: str, language: str):
    """
    Kör fn() i en bakgrundstråd och visar spinner + förfluten tid + ETA.
    Sparar RTF när klart. Returnerar fn():s returvärde.
    """
    SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    result  = [None]
    err     = [None]
    done    = threading.Event()

    def worker():
        try:
            result[0] = fn()
        except Exception as e:
            err[0] = e
        finally:
            done.set()

    rtf    = _load_rtf(model_size, language)
    start  = time.time()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    i = 0
    while not done.wait(timeout=0.12):
        elapsed = time.time() - start
        if rtf:
            eta = (audio_sec / rtf) - elapsed
            eta_str = f"  ETA {_fmt_dur(max(0, eta))}" if eta > 2 else f"  {_GRN}snart klar…{_NRM}"
        else:
            eta_str = f"  {_GRY}(kalibreras — första körning){_NRM}"
        line = f"  {_CYN}{SPIN[i % len(SPIN)]}{_NRM}  {_fmt_dur(elapsed)}{eta_str}"
        print(f"\r{line}          ", end="", flush=True)
        i += 1

    wall_sec = time.time() - start
    print(f"\r  {_GRN}✓{_NRM}  {_fmt_dur(wall_sec)} totalt                              ")

    if err[0]:
        raise err[0]

    _save_rtf(model_size, language, audio_sec, wall_sec)
    return result[0]


def _audio_duration(audio_path: Path) -> float:
    """Hämtar ljudfilens längd i sekunder via ffmpeg. Returnerar 0.0 vid fel."""
    import ffmpeg
    try:
        probe = ffmpeg.probe(str(audio_path))
        return float(probe["format"]["duration"])
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Transkribering
# ---------------------------------------------------------------------------

_KB_MODELS = {
    "small":  "KBLab/kb-whisper-small",
    "medium": "KBLab/kb-whisper-medium",
    "large":  "KBLab/kb-whisper-large",
}
_FALLBACK_MODEL = "large-v3"


def detect_language(audio_path: Path) -> tuple[str, float]:
    """
    Detekterar språk via faster-whisper tiny på de första 30 sek.
    Returnerar (språkkod, konfidens) t.ex. ("sv", 0.97).
    """
    from faster_whisper import WhisperModel
    print(f"\n[INFO] Detekterar språk i {_BLD}{audio_path.name}{_NRM}  {_GRY}(tiny-modell){_NRM}")
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    _, info = model.transcribe(str(audio_path), language=None, beam_size=1)
    lang, conf = info.language, info.language_probability
    label = f"{_GRN}svenska → KB-Whisper{_NRM}" if lang == "sv" else f"{_CYN}{lang} → Whisper {_FALLBACK_MODEL}{_NRM}"
    print(f"       Detekterat: {_BLD}{lang}{_NRM}  konfidens {conf:.0%}  →  {label}")
    return lang, conf


def transcribe(audio_path: Path, model_size: str = "medium", language: str = "sv") -> list[dict]:
    """
    Transkriberar ljudfil med faster-whisper.
    language="auto" kör språkdetektering och väljer modell därefter.
    Visar spinner + ETA och kalibrerar maskinhastighet automatiskt.
    """
    from faster_whisper import WhisperModel

    if language == "auto":
        language, _ = detect_language(audio_path)

    model_id  = _KB_MODELS.get(model_size, model_size) if language == "sv" else _FALLBACK_MODEL
    audio_sec = _audio_duration(audio_path)
    rtf       = _load_rtf(model_size, language)

    print(f"\n[INFO] Transkriberar {_BLD}{audio_path.name}{_NRM}")
    print(f"       Modell: {model_id}  |  Språk: {language}  |  Ljudlängd: {_fmt_dur(audio_sec)}")
    if rtf:
        print(f"       Beräknad tid: ~{_fmt_dur(audio_sec / rtf)}  {_GRY}(baserat på tidigare körning){_NRM}")
    else:
        print(f"       Beräknad tid: {_GRY}okänd — kalibreras nu{_NRM}")
    print()

    def _run():
        model = WhisperModel(model_id, device="cpu", compute_type="int8")
        raw_segs, _ = model.transcribe(str(audio_path), beam_size=5, language=language)
        return [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
            for seg in raw_segs
        ]

    segments = _spinner_run(audio_path.name, _run, audio_sec, model_size, language)
    print(f"       {len(segments)} segment transkriberade")
    return segments


def segments_to_text(segments: list[dict]) -> str:
    """Formaterar segment till läsbart transkript med tidsstämplar."""
    lines = []
    for seg in segments:
        ts = format_timestamp(seg["start"])
        lines.append(f"[{ts}] {seg['text']}")
    return "\n".join(lines)


def save_transcript(segments: list[dict], output_path: Path) -> None:
    text = segments_to_text(segments)
    output_path.write_text(text, encoding="utf-8")
    print(f"       Transkript sparat: {output_path.name}")
