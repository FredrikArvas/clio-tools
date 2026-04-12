"""
editor.py — ffmpeg-klippning för clio-audio-edit.
Parsning av klipplista från annoterat manus och tillämpning via ffmpeg.
"""

import os
import re
import shutil
import sys
from pathlib import Path

from transcribe import format_timestamp


def _ffmpeg_bin() -> str:
    """Returnerar sökväg till ffmpeg-binären, med explicit fallback."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    # Vanliga Windows-platser
    candidates = [
        r"C:\Program Files\digiKam\ffmpeg.EXE",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise FileNotFoundError(
        "ffmpeg hittades inte. Lägg till ffmpeg i PATH eller verifiera installationen."
    )


def _set_ffmpeg_env() -> None:
    """Sätter PATH-miljövariabel så att ffmpeg-python hittar binären."""
    exe = _ffmpeg_bin()
    bin_dir = str(Path(exe).parent)
    if bin_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


# ---------------------------------------------------------------------------
# Parsning av annoterat manus
# ---------------------------------------------------------------------------

def parse_cut_list(annotated_path: Path) -> list[tuple[float, float]]:
    """
    Läser annoterat manus och extraherar klipplista.
    Returnerar lista av (start_sek, slut_sek)-tupler.
    """
    text = annotated_path.read_text(encoding="utf-8")

    pattern = r"\[KLIPP_START:\s*(\d{2}:\d{2}:\d{2})\s*\|\s*KLIPP_SLUT:\s*(\d{2}:\d{2}:\d{2})\]"
    matches = re.findall(pattern, text)

    def ts_to_sec(ts: str) -> float:
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)

    cuts = [(ts_to_sec(start), ts_to_sec(end)) for start, end in matches]

    if not cuts:
        print("\n[VARNING] Inga klippmarkeringar hittades i manuset.")
        print("          Kontrollera att formatet är: [KLIPP_START: HH:MM:SS | KLIPP_SLUT: HH:MM:SS]")
        sys.exit(1)

    print(f"\n[INFO] {len(cuts)} klipp hittade i manuset")
    return cuts


def cuts_to_keep_segments(cuts: list[tuple[float, float]], total_duration: float) -> list[tuple[float, float]]:
    """Inverterar klipplistan — returnerar de segment som ska BEHÅLLAS."""
    keep   = []
    cursor = 0.0

    for cut_start, cut_end in sorted(cuts):
        if cursor < cut_start:
            keep.append((cursor, cut_start))
        cursor = cut_end

    if cursor < total_duration:
        keep.append((cursor, total_duration))

    return keep


# ---------------------------------------------------------------------------
# Klippning med ffmpeg
# ---------------------------------------------------------------------------

def get_duration(audio_path: Path) -> float:
    """Hämtar ljudfilens längd i sekunder via ffmpeg -i (kräver inte ffprobe)."""
    import subprocess, re
    exe = _ffmpeg_bin()
    result = subprocess.run(
        [exe, "-i", str(audio_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout.decode("utf-8", errors="ignore")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", output)
    if not m:
        raise RuntimeError(f"Kunde inte läsa längd från: {audio_path}")
    h, m_, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + m_ * 60 + s


def apply_cuts(audio_path: Path, cuts: list[tuple[float, float]], output_path: Path) -> None:
    """
    Klipper ljudfilen med ffmpeg via concat-demuxer (explicit sökväg, ingen ffmpeg-python).
    Behåller de segment som INTE är i klipplistan.
    """
    import subprocess
    import tempfile

    exe           = _ffmpeg_bin()
    total         = get_duration(audio_path)
    keep_segments = cuts_to_keep_segments(cuts, total)

    print(f"\n[INFO] Klipper {len(cuts)} segment...")
    print(f"       Originalets längd:  {format_timestamp(total)}")

    if not keep_segments:
        print("[FEL] Inga segment att behålla — avbryter.")
        sys.exit(1)

    # Bygg concat-lista med inpoint/outpoint — inga tempfiler per segment
    temp_dir    = Path(tempfile.mkdtemp())
    concat_file = temp_dir / "concat.txt"
    lines = ["ffconcat version 1.0"]
    for start, end in keep_segments:
        lines.append(f"file '{str(audio_path).replace(chr(92), '/')}'")
        lines.append(f"inpoint {start:.3f}")
        lines.append(f"outpoint {end:.3f}")
    concat_file.write_text("\n".join(lines), encoding="utf-8")

    cmd = [
        exe, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(output_path),
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    concat_file.unlink()
    temp_dir.rmdir()

    if result.returncode != 0:
        err = result.stdout.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg misslyckades:\n{err[-800:]}")

    kept_duration = sum(e - s for s, e in keep_segments)
    removed       = total - kept_duration
    print(f"       Klippt längd:       {format_timestamp(kept_duration)}")
    print(f"       Borttaget:          {format_timestamp(removed)} ({removed/total*100:.0f}%)")
    print(f"\n[OK]  Sparat: {output_path.name}")


def save_cutlog(cuts: list[tuple[float, float]], output_path: Path) -> None:
    """Sparar klipplogg för dokumentation."""
    lines = ["# Klipplogg — clio-audio-edit\n"]
    for i, (start, end) in enumerate(cuts, 1):
        duration = end - start
        lines.append(
            f"Klipp {i:02d}: {format_timestamp(start)} --> {format_timestamp(end)} "
            f"({format_timestamp(duration)})"
        )
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"       Klipplogg sparat: {output_path.name}")
