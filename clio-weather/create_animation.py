#!/usr/bin/env python3
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

from config import FRAMES_DIR

FMT = "%Y-%m-%d %H:%M"
STEM_FMT = "%Y-%m-%d_%H%M"


def parse_args():
    p = argparse.ArgumentParser(description="Skapa animation av Muskoe-radar")
    p.add_argument("--from", dest="from_dt", metavar="YYYY-MM-DD_HH:MM")
    p.add_argument("--to", dest="to_dt", metavar="YYYY-MM-DD_HH:MM")
    p.add_argument("--last", type=int, metavar="N", help="Senaste N frames")
    p.add_argument("--format", choices=["mp4", "gif"], default="mp4")
    p.add_argument("--fps", type=int, default=4)
    p.add_argument("--only-rain", action="store_true", help="Inkludera bara frames med regn")
    return p.parse_args()


def parse_stem(stem):
    """Parsar YYYY-MM-DD_HHMM_rain / YYYY-MM-DD_HHMM_dry / YYYY-MM-DD_HHMM."""
    if stem.endswith(("_rain", "_dry")):
        base = stem.rsplit("_", 1)[0]
        tag = stem.rsplit("_", 1)[1]
    else:
        base = stem
        tag = None
    return datetime.strptime(base, STEM_FMT), tag


def collect_frames(from_dt, to_dt, only_rain=False):
    frames = []
    for f in sorted(FRAMES_DIR.glob("*.png")):
        try:
            ts, tag = parse_stem(f.stem)
        except ValueError:
            continue
        if only_rain and tag != "rain":
            continue
        if from_dt <= ts <= to_dt:
            frames.append((ts, f))
    return frames


def make_mp4(frames, fps, output):
    list_path = Path("/tmp/clio_radar_frames.txt")
    dur = f"{1/fps:.4f}"
    with open(list_path, "w") as fh:
        for _, f in frames:
            fh.write(f"file '{f.resolve()}'\nduration {dur}\n")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", str(output),
        ],
        check=True,
    )


def make_gif(frames, fps, output):
    images = [Image.open(f) for _, f in frames]
    duration_ms = int(1000 / fps)
    images[0].save(
        output,
        save_all=True,
        append_images=images[1:],
        loop=0,
        duration=duration_ms,
        optimize=False,
    )


def main():
    args = parse_args()

    from_dt = datetime.strptime(args.from_dt, FMT) if args.from_dt else datetime.min
    to_dt = datetime.strptime(args.to_dt, FMT) if args.to_dt else datetime.max

    frames = collect_frames(from_dt, to_dt, only_rain=args.only_rain)
    if not frames:
        label = "regn-frames" if args.only_rain else "frames"
        print(f"Inga {label} hittades.", file=sys.stderr)
        sys.exit(1)

    if args.last:
        frames = frames[-args.last:]

    rain_label = " (endast regn)" if args.only_rain else ""
    print(f"Animerar {len(frames)} frames{rain_label}  ({frames[0][0]} -> {frames[-1][0]})")

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    suffix = "_rain" if args.only_rain else ""
    output = Path(__file__).parent / f"musko_radar_{ts}{suffix}.{args.format}"

    if args.format == "mp4":
        make_mp4(frames, args.fps, output)
    else:
        make_gif(frames, args.fps, output)

    print(f"Sparad: {output}")


if __name__ == "__main__":
    main()
