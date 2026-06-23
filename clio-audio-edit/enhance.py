#!/usr/bin/env python3
"""
enhance.py — Brusreducering och volymsnormalisering för clio-audio-edit.

Steg:
  1. noisereduce (statistisk brusprofilering)
  2. loudnorm via ffmpeg (EBU R128)

Användning:
  python enhance.py --input session.wav
  python enhance.py --input session.wav --prop-decrease 0.9 --loudnorm-target -12
  python enhance.py --input session.wav --no-loudnorm
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_PROP_DECREASE  = 0.75
DEFAULT_LOUDNORM_TARGET = -14.0
DEFAULT_LOUDNORM_TP     = -1.0


def reduce_noise(input_path: Path, output_path: Path, prop_decrease: float) -> None:
    try:
        import noisereduce as nr
        import soundfile as sf
        import numpy as np
    except ImportError as e:
        print(f"[FEL] Saknat beroende: {e}")
        print("      Installera med: pip install noisereduce soundfile")
        sys.exit(1)

    print(f"[1/2] Brusreducering  (prop_decrease={prop_decrease}) ...")
    data, rate = sf.read(str(input_path))
    reduced = nr.reduce_noise(y=data, sr=rate, prop_decrease=prop_decrease, stationary=False)
    sf.write(str(output_path), reduced.astype(np.float32), rate)


def loudnorm(input_path: Path, output_path: Path, target_lufs: float, true_peak: float) -> None:
    print(f"[2/2] Loudnorm  (target={target_lufs} LUFS, TP={true_peak}) ...")
    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("[FEL] ffmpeg hittades inte i PATH")
        sys.exit(1)

    cmd = [
        ffmpeg, "-y", "-i", str(input_path),
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11",
        "-ar", "22050", "-c:a", "pcm_s16le",
        str(output_path),
    ]
    result = subprocess.run(cmd, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(f"[FEL] ffmpeg:\n{result.stderr.decode()[-400:]}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Brusreducering + volymsnormalisering")
    parser.add_argument("--input",           required=True, type=Path)
    parser.add_argument("--output",          type=Path, default=None,
                        help="Utfil (default: <stem>_enhanced.wav)")
    parser.add_argument("--prop-decrease",   type=float, default=DEFAULT_PROP_DECREASE,
                        help=f"Brusreduceringsstyrka 0–1  (default: {DEFAULT_PROP_DECREASE})")
    parser.add_argument("--loudnorm-target", type=float, default=DEFAULT_LOUDNORM_TARGET,
                        help=f"Målnivå i LUFS  (default: {DEFAULT_LOUDNORM_TARGET})")
    parser.add_argument("--loudnorm-tp",     type=float, default=DEFAULT_LOUDNORM_TP,
                        help=f"True peak i dBFS  (default: {DEFAULT_LOUDNORM_TP})")
    parser.add_argument("--no-loudnorm",     action="store_true",
                        help="Hoppa över loudnorm-steget")
    parser.add_argument("--no-nr",           action="store_true",
                        help="Hoppa över brusreducering (bara loudnorm)")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[FEL] Filen finns inte: {args.input}")
        sys.exit(1)

    suffix = "_enhanced"
    if args.no_nr:
        suffix = "_loud"
    output = args.output or args.input.with_stem(args.input.stem + suffix)

    if args.no_nr:
        loudnorm(args.input, output, args.loudnorm_target, args.loudnorm_tp)
    elif args.no_loudnorm:
        reduce_noise(args.input, output, args.prop_decrease)
    else:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            reduce_noise(args.input, tmp_path, args.prop_decrease)
            loudnorm(tmp_path, output, args.loudnorm_target, args.loudnorm_tp)
        finally:
            tmp_path.unlink(missing_ok=True)

    print(f"[OK]  {output.name}")


if __name__ == "__main__":
    main()
