"""frame_extractor.py — Extraherar frames ur video med ffmpeg."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def get_video_metadata(video_path: str) -> dict:
    """Kör ffprobe och returnerar duration, real_fps, creation_time, width, height."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(video_path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return {}

    meta: dict = {}
    fmt = data.get("format", {})
    meta["duration"] = float(fmt.get("duration", 0) or 0)
    meta["creation_time"] = fmt.get("tags", {}).get("creation_time", "")

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            meta["width"] = stream.get("width", 0)
            meta["height"] = stream.get("height", 0)
            r_fps_str = stream.get("r_frame_rate", "")
            if "/" in r_fps_str:
                num, den = r_fps_str.split("/")
                meta["real_fps"] = float(num) / float(den) if float(den) else 0.0
            break

    return meta


def extract_frames(
    video_path: str,
    fps: float,
    out_dir: str,
    start: str | None = None,
    end: str | None = None,
) -> list[str]:
    """Extrahera frames med ffmpeg.

    start/end kan anges som "MM:SS" eller sekunder (t.ex. "3:56" eller "236").
    Utan start/end analyseras hela videon.
    """
    os.makedirs(out_dir, exist_ok=True)
    out_pattern = os.path.join(out_dir, "frame_%04d.jpg")

    # -ss/-to efter -i ger frame-exakt klippning (absoluta tidstämplar från filens start)
    cmd = ["ffmpeg", "-i", str(video_path)]
    if start:
        cmd += ["-ss", start]
    if end:
        cmd += ["-to", end]
    cmd += ["-vf", f"fps={fps}", "-q:v", "2", out_pattern, "-y", "-loglevel", "error"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg misslyckades:\n{result.stderr.strip()}")

    frames = sorted(Path(out_dir).glob("frame_*.jpg"))
    return [str(f) for f in frames]
