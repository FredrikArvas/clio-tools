"""
editor.py — ffmpeg-klippning för clio-audio-edit.
Parsning av klipplista från annoterat manus och tillämpning via ffmpeg.
"""

import re
import sys
from pathlib import Path

from transcribe import format_timestamp


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
    """Hämtar ljudfilens längd i sekunder via ffmpeg."""
    import ffmpeg
    probe = ffmpeg.probe(str(audio_path))
    return float(probe["format"]["duration"])


def apply_cuts(audio_path: Path, cuts: list[tuple[float, float]], output_path: Path) -> None:
    """
    Klipper ljudfilen med ffmpeg.
    Behåller de segment som INTE är i klipplistan.
    """
    import ffmpeg

    total         = get_duration(audio_path)
    keep_segments = cuts_to_keep_segments(cuts, total)

    print(f"\n[INFO] Klipper {len(cuts)} segment...")
    print(f"       Originalets längd:  {format_timestamp(total)}")

    if not keep_segments:
        print("[FEL] Inga segment att behålla — avbryter.")
        sys.exit(1)

    try:
        (
            ffmpeg
            .filter(
                [ffmpeg.input(str(audio_path), ss=s, to=e) for s, e in keep_segments],
                "concat",
                n=len(keep_segments),
                v=0,
                a=1,
            )
            .output(str(output_path))
            .overwrite_output()
            .run(quiet=True)
        )
    except Exception:
        print("       (Försöker alternativ klippmetod...)")
        _apply_cuts_concat(audio_path, keep_segments, output_path)
        return

    kept_duration = sum(e - s for s, e in keep_segments)
    removed       = total - kept_duration
    print(f"       Klippt längd:       {format_timestamp(kept_duration)}")
    print(f"       Borttaget:          {format_timestamp(removed)} ({removed/total*100:.0f}%)")
    print(f"\n[OK]  Sparat: {output_path.name}")


def _apply_cuts_concat(audio_path: Path, keep_segments: list[tuple[float, float]], output_path: Path) -> None:
    """
    Fallback-klippning via tempfiler + concat-lista.
    Används om filter_complex-metoden misslyckas.
    """
    import ffmpeg
    import tempfile

    temp_dir      = Path(tempfile.mkdtemp())
    segment_files = []

    for i, (start, end) in enumerate(keep_segments):
        seg_path = temp_dir / f"seg_{i:04d}.wav"
        (
            ffmpeg
            .input(str(audio_path), ss=start, to=end)
            .output(str(seg_path), acodec="pcm_s16le")
            .overwrite_output()
            .run(quiet=True)
        )
        segment_files.append(seg_path)

    concat_list = temp_dir / "concat.txt"
    with open(concat_list, "w") as f:
        for seg in segment_files:
            f.write(f"file '{seg}'\n")

    (
        ffmpeg
        .input(str(concat_list), format="concat", safe=0)
        .output(str(output_path), acodec="pcm_s16le")
        .overwrite_output()
        .run(quiet=True)
    )

    for seg in segment_files:
        seg.unlink()
    concat_list.unlink()
    temp_dir.rmdir()

    total = sum(e - s for s, e in keep_segments)
    print(f"[OK]  Sparat: {output_path.name} ({format_timestamp(total)})")


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
