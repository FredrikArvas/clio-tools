"""video_analyzer.py — Frame-by-frame UAP-analys med Claude Vision."""

from __future__ import annotations

import base64
import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

import config
from frame_extractor import extract_frames, get_video_metadata

_SYSTEM_PROMPT = """\
Du analyserar enskilda frames från en slow-motion-video för UAP-forskning (Unidentified Anomalous Phenomena).
Identifiera alla synliga objekt i framen och klassificera dem.

Svara ALLTID med valid JSON och ingenting annat (inga markdown-fences, ingen inledande text):
{"objects": [{"label": str, "category": str, "confidence": float, "notes": str}], "unknown_detected": bool, "frame_notes": str}

Tillåtna kategorier: aircraft | bird | drone | satellite | cloud | building | vehicle | natural | unknown
Sätt unknown_detected till true om något objekt har kategorin "unknown" ELLER om du ser något du inte kan förklara.
confidence är 0.0–1.0 (1.0 = helt säker).
"""


@dataclass
class FrameResult:
    frame_path: str
    frame_index: int
    objects: list[dict]
    unknown_detected: bool
    frame_notes: str
    raw_response: str = ""
    parse_error: bool = False


@dataclass
class AnalysisResult:
    video_path: str
    metadata: dict
    frame_results: list[FrameResult] = field(default_factory=list)

    @property
    def flagged_frames(self) -> list[FrameResult]:
        return [f for f in self.frame_results if f.unknown_detected]


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def analyze_frame(client: anthropic.Anthropic, image_path: str, frame_index: int) -> FrameResult:
    """Analysera en enskild frame med Claude Vision. Returnerar FrameResult."""
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    msg = client.messages.create(
        model=config.VIDEO_VISION_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data,
                    },
                },
                {"type": "text", "text": "Analysera denna frame. Svara med JSON endast."},
            ],
        }],
    )

    raw = msg.content[0].text
    try:
        data = json.loads(_strip_json_fences(raw))
        return FrameResult(
            frame_path=image_path,
            frame_index=frame_index,
            objects=data.get("objects", []),
            unknown_detected=bool(data.get("unknown_detected", False)),
            frame_notes=data.get("frame_notes", ""),
            raw_response=raw,
        )
    except (json.JSONDecodeError, KeyError, AttributeError):
        return FrameResult(
            frame_path=image_path,
            frame_index=frame_index,
            objects=[],
            unknown_detected=False,
            frame_notes="",
            raw_response=raw,
            parse_error=True,
        )


def analyze_video(
    video_path: str,
    fps: float | None = None,
    keep_frames: bool = False,
    start: str | None = None,
    end: str | None = None,
) -> AnalysisResult:
    """Extrahera frames och analysera varje med Claude Vision."""
    effective_fps = fps if fps is not None else config.VIDEO_FRAMES_PER_SEC
    # api_key=None → SDK använder ANTHROPIC_API_KEY från miljön automatiskt
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)

    print(f"\n[analyze] Video: {video_path}")
    metadata = get_video_metadata(video_path)
    duration = metadata.get("duration", 0)
    if duration:
        print(f"[analyze] Längd: {duration:.1f}s | {metadata.get('width', '?')}x{metadata.get('height', '?')}")
    segment = f"{start}–{end}" if (start or end) else "hela videon"
    print(f"[analyze] Segment: {segment} | {effective_fps} frames/s")

    out_dir = tempfile.mkdtemp(prefix="uap_frames_")
    try:
        frames = extract_frames(video_path, effective_fps, out_dir, start=start, end=end)
        n = len(frames)
        print(f"[analyze] {n} frames extraherade. Startar analys...\n")

        result = AnalysisResult(video_path=video_path, metadata=metadata)
        parse_errors = 0

        for i, frame_path in enumerate(frames, 1):
            print(f"  [{i:3d}/{n}] Analyserar frame {i}...", end="\r")
            fr = analyze_frame(client, frame_path, i)
            result.frame_results.append(fr)
            if fr.parse_error:
                parse_errors += 1

        flagged_count = len(result.flagged_frames)
        print(f"\n[analyze] Klar. {flagged_count} flaggade frames", end="")
        if parse_errors:
            print(f", {parse_errors} parse-fel", end="")
        print(".\n")
        return result
    finally:
        if not keep_frames:
            shutil.rmtree(out_dir, ignore_errors=True)


def print_report(result: AnalysisResult) -> None:
    """Skriv ut analysrapport till terminalen."""
    flagged = result.flagged_frames
    total = len(result.frame_results)

    print("=" * 64)
    print(f"  UAP Videoanalys — {Path(result.video_path).name}")
    print("=" * 64)
    print(f"  Analyserade frames : {total}")
    print(f"  Flaggade frames    : {len(flagged)}")
    duration = result.metadata.get("duration", 0)
    if duration:
        print(f"  Videolängd        : {duration:.1f}s")
    real_fps = result.metadata.get("real_fps", 0)
    if real_fps:
        print(f"  Inspelad FPS      : {real_fps:.0f}")
    print()

    if not flagged:
        print("  Inga okända objekt detekterade.\n")
        return

    print(f"  {'Frame':<7} {'Synliga objekt':<38} {'Notering'}")
    print(f"  {'-'*7} {'-'*38} {'-'*36}")
    for fr in flagged:
        all_labels = ", ".join(o.get("label", "?") for o in fr.objects[:4])
        notes_short = fr.frame_notes[:36] if fr.frame_notes else ""
        print(f"  {fr.frame_index:<7} {all_labels:<38} {notes_short}")

        unknowns = [o for o in fr.objects if o.get("category") == "unknown"]
        for uo in unknowns:
            conf = uo.get("confidence", 0.0)
            uo_notes = uo.get("notes", "")[:56]
            print(f"  {'':7}   → OKÄNT: {uo.get('label', '?')} (conf={conf:.2f}) {uo_notes}")
    print()
