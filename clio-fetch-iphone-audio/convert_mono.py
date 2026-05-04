#!/usr/bin/env python3
"""
convert_mono.py — Konverterar WAV-filer till mono 22 050 Hz.

Skapar <stem>_mono.wav bredvid originalet. Hoppar över filer som
redan har en _mono-version (inkrementellt). Originalet rörs ej.

Användning:
    python convert_mono.py
    python convert_mono.py --dry-run
    python convert_mono.py --dest "C:/Users/fredr/Dropbox/Audio/iPhone-inspelningar"
    python convert_mono.py --rate 16000   # Whisper föredrar 16 kHz för tal
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_DEST = r"C:\Users\fredr\Dropbox\Audio\iPhone-inspelningar"
DEFAULT_RATE = 22050


def check_ffmpeg() -> str:
    """Returnerar sökväg till ffmpeg eller avslutar med felmeddelande."""
    path = shutil.which("ffmpeg")
    if not path:
        print("FEL: ffmpeg hittades inte i PATH.")
        print("Installera via: winget install ffmpeg  (eller lägg till i PATH)")
        sys.exit(1)
    return path


def find_wavs(dest: Path) -> list[Path]:
    """Returnerar alla WAV-filer som inte redan är _mono-versioner."""
    return sorted(
        p for p in dest.glob("*.wav")
        if not p.stem.endswith("_mono")
    )


def already_converted(wav: Path) -> bool:
    mono = wav.with_name(wav.stem + "_mono.wav")
    return mono.exists() and mono.stat().st_size > 0


def convert(ffmpeg: str, src: Path, rate: int) -> bool:
    """Kör ffmpeg-konvertering. Returnerar True vid success."""
    dst = src.with_name(src.stem + "_mono.wav")
    tmp = src.with_name(src.stem + "_mono.tmp.wav")
    try:
        result = subprocess.run(
            [
                ffmpeg, "-y", "-i", str(src),
                "-ac", "1",
                "-ar", str(rate),
                str(tmp),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"\n  FEL (ffmpeg exit {result.returncode}):")
            # ffmpeg skriver info till stderr — visa sista raderna
            for line in result.stderr.splitlines()[-5:]:
                print(f"  {line}")
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(dst)
        return True
    except Exception as e:
        print(f"\n  FEL: {e}")
        tmp.unlink(missing_ok=True)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WAV → mono _mono.wav (inkrementell konvertering)"
    )
    parser.add_argument("--dest",    default=DEFAULT_DEST, help="Källmapp med WAV-filer")
    parser.add_argument("--rate",    default=DEFAULT_RATE, type=int,
                        help=f"Samplingsfrekvens i Hz (default: {DEFAULT_RATE})")
    parser.add_argument("--dry-run", action="store_true",  help="Visa vad som skulle konverteras")
    args = parser.parse_args()

    dest = Path(args.dest)
    if not dest.exists():
        print(f"FEL: Mappen finns inte: {dest}")
        sys.exit(1)

    ffmpeg = check_ffmpeg()

    wavs       = find_wavs(dest)
    to_convert = [w for w in wavs if not already_converted(w)]
    skipped    = len(wavs) - len(to_convert)

    total_mb = sum(w.stat().st_size for w in to_convert) / 1_048_576
    print(
        f"Hittade {len(wavs)} WAV-filer  |  "
        f"{len(to_convert)} att konvertera ({total_mb:.0f} MB)  |  "
        f"{skipped} redan klara"
    )

    if not to_convert:
        print("Allt redan konverterat.")
        return

    if args.dry_run:
        print("\n-- dry-run, ingen konvertering --")
        for w in to_convert:
            mb = w.stat().st_size / 1_048_576
            print(f"  {w.name}  ({mb:.1f} MB)  →  {w.stem}_mono.wav")
        return

    errors = 0
    for i, wav in enumerate(to_convert, 1):
        mb = wav.stat().st_size / 1_048_576
        print(f"[{i}/{len(to_convert)}] {wav.name}  ({mb:.1f} MB)", end="  ", flush=True)
        ok = convert(ffmpeg, wav, args.rate)
        if ok:
            mono = wav.with_name(wav.stem + "_mono.wav")
            mono_mb = mono.stat().st_size / 1_048_576
            print(f"→ {mono.name} ({mono_mb:.1f} MB) ✓")
        else:
            errors += 1

    print(
        f"\nKlar. {len(to_convert) - errors} konverterade, "
        f"{errors} fel, {skipped} hoppades över."
    )
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
