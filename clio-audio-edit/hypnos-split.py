#!/usr/bin/env python3
"""
hypnos-split.py  —  Delar upp en hypnossession i segment och tar bort pauser.

Steg:
  1. Kör silencedetect på hela filen (en analys-pass)
  2. Extraherar namngivna segment med långa pauser borttagna

Segments-filen (JSON):
  [
    {"name": "01_induktion", "start": "00:36:18", "end": "00:55:56"},
    ...
  ]

Användning:
  python hypnos-split.py --input session.wav --segments segments.json
  python hypnos-split.py --input session.wav --segments segments.json --silence-db -30 --silence-dur 5
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def ts_to_sec(ts: str) -> float:
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(ts)


def sec_to_hms(s: float) -> str:
    h  = int(s // 3600)
    m  = int((s % 3600) // 60)
    sc = s % 60
    return f"{h:02d}:{m:02d}:{sc:05.2f}"


def detect_silences(audio_path: Path, noise_db: float, min_dur: float) -> list[tuple[float, float]]:
    print(f"\n[1/2] Analyserar pauser  ({noise_db} dB, min {min_dur}s) ...")
    cmd = [
        "ffmpeg", "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    output = result.stderr

    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", output)]
    ends   = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)",   output)]

    pairs = list(zip(starts, ends[: len(starts)]))
    if len(starts) > len(ends):
        pairs.append((starts[-1], float("inf")))

    print(f"       {len(pairs)} pauser hittade")
    return pairs


def extract_segment(
    audio_path:   Path,
    seg_name:     str,
    seg_start:    float,
    seg_end:      float,
    silences:     list[tuple[float, float]],
    output_dir:   Path,
    silence_tail: float,
) -> Path | None:
    """Extraherar ett segment och klipper bort långa pauser inom det."""

    seg_silences = sorted(
        (max(s, seg_start), min(e, seg_end))
        for s, e in silences
        if s < seg_end and e > seg_start and e > s
    )

    keep   = []
    cursor = seg_start
    for sil_start, sil_end in seg_silences:
        if sil_start > cursor:
            # Lägg till lite svans av tystnad för naturligt flöde
            keep_end = min(sil_start + silence_tail, sil_end)
            keep.append((cursor, keep_end))
        cursor = max(cursor, sil_end)
    if cursor < seg_end:
        keep.append((cursor, seg_end))

    if not keep:
        print(f"    [VARNING] {seg_name}: ingenting att behålla — hoppar över")
        return None

    temp_dir    = Path(tempfile.mkdtemp())
    concat_file = temp_dir / "concat.txt"
    lines = ["ffconcat version 1.0"]
    for start, end in keep:
        if end > start + 0.1:
            lines.append(f"file '{str(audio_path)}'")
            lines.append(f"inpoint {start:.3f}")
            lines.append(f"outpoint {end:.3f}")
    concat_file.write_text("\n".join(lines), encoding="utf-8")

    out_name = f"{audio_path.stem}_{seg_name}.wav"
    out_path = output_dir / out_name

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    try:
        concat_file.unlink()
        temp_dir.rmdir()
    except OSError:
        pass

    if result.returncode != 0:
        print(f"    [FEL] ffmpeg:\n{result.stderr[-600:]}")
        return None

    orig_dur = seg_end - seg_start
    kept_dur = sum(e - s for s, e in keep)
    removed  = orig_dur - kept_dur
    pct      = removed / orig_dur * 100 if orig_dur > 0 else 0
    print(f"    [OK]  {out_name}")
    print(f"          Original: {sec_to_hms(orig_dur)}  →  "
          f"Kvar: {sec_to_hms(kept_dur)}  "
          f"(borttaget: {sec_to_hms(removed)}, {pct:.0f}%)")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dela upp hypnossession i segment och ta bort pauser"
    )
    parser.add_argument("--input",        required=True, type=Path)
    parser.add_argument("--segments",     required=True, type=Path)
    parser.add_argument("--silence-db",   type=float, default=-35.0,
                        help="Tröskel för tystnad i dB  (default: -35)")
    parser.add_argument("--silence-dur",  type=float, default=4.0,
                        help="Minsta tystnadslängd i sek  (default: 4.0)")
    parser.add_argument("--silence-tail", type=float, default=0.6,
                        help="Svans av tystnad att behålla i sek  (default: 0.6)")
    parser.add_argument("--output-dir",   type=Path,  default=None)
    args = parser.parse_args()

    for p, label in [(args.input, "ljudfil"), (args.segments, "segmentfil")]:
        if not p.exists():
            print(f"[FEL] Filen finns inte ({label}): {p}")
            sys.exit(1)

    segments   = json.loads(args.segments.read_text(encoding="utf-8"))
    output_dir = args.output_dir or args.input.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    silences = detect_silences(args.input, args.silence_db, args.silence_dur)

    print(f"\n[2/2] Extraherar {len(segments)} segment ...")
    for seg in segments:
        name  = seg["name"]
        start = ts_to_sec(seg["start"])
        end   = ts_to_sec(seg["end"])
        print(f"\n  {name}  ({sec_to_hms(start)} → {sec_to_hms(end)})")
        extract_segment(
            args.input, name, start, end,
            silences, output_dir, args.silence_tail,
        )

    print("\n[OK]  Klar.\n")


if __name__ == "__main__":
    main()
