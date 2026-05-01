"""
pipeline/main.py — CE5 & UAP-analys-pipeline

Analysera videofiler med känt UAP-potentiell innehåll.
Kör på servern (EliteDesk) där Ollama och GPU finns.

Flöde:
  1. Extrahera frames (ffmpeg)
  2. Motion-delta → hitta anomali-frames
  3. LLaVA pre-screen → filtrera events lokalt
  4. Claude deep-analyze → analysera bekräftade events
  5. Rapport

Användning:
  python -m pipeline.main analyze --video /mnt/dropbox-disk/uap/inbox/ce5.mov
  python -m pipeline.main analyze --folder /mnt/dropbox-disk/uap/inbox/
  python -m pipeline.main analyze --video ce5.mov --no-ollama --fps 8
  python -m pipeline.main analyze --video ce5.mov --no-claude --keep-frames
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

# Se till att clio-uap ligger i path
_HERE = Path(__file__).parent
_UAP_DIR = _HERE.parent
_ROOT_DIR = _UAP_DIR.parent
for _p in [str(_ROOT_DIR), str(_UAP_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config
from frame_extractor import extract_frames, get_video_metadata
from pipeline.motion_delta import compute_deltas, cluster_events, print_delta_summary
from pipeline.ollama_screen import screen_events
from video_analyzer import analyze_frame, print_report, AnalysisResult, FrameResult

import anthropic

# Videotyper vi känner igen
VIDEO_EXTENSIONS = {".mov", ".mp4", ".avi", ".mkv", ".m4v", ".mpg", ".mpeg", ".mts", ".3gp"}


def _banner():
    print("=" * 64)
    print("  clio-uap pipeline — CE5 & UAP Videoanalys")
    print("=" * 64)


def analyze_single(
    video_path: str,
    fps: float,
    delta_threshold: float,
    gap_frames: int,
    use_ollama: bool,
    use_claude: bool,
    keep_frames: bool,
    start: str | None,
    end: str | None,
) -> AnalysisResult | None:
    """Analysera en enskild videofil genom hela pipeline."""
    p = Path(video_path)
    if not p.exists():
        print(f"[FEL] Filen finns inte: {video_path}")
        return None

    print(f"\n{'─'*64}")
    print(f"  Fil: {p.name}")
    print(f"{'─'*64}")

    # Metadata
    meta = get_video_metadata(video_path)
    duration = meta.get("duration", 0)
    if duration:
        mins = int(duration // 60)
        secs = int(duration % 60)
        print(f"  Längd  : {mins}:{secs:02d} | {meta.get('width','?')}x{meta.get('height','?')} | FPS: {meta.get('real_fps', '?')}")
    segment = f"{start}–{end}" if (start or end) else "hela videon"
    print(f"  Segment: {segment} | Extraherar {fps} frames/s\n")

    out_dir = tempfile.mkdtemp(prefix="uap_frames_")
    try:
        # ── Steg 1: Extrahera frames ──────────────────────────────────────
        frames = extract_frames(video_path, fps, out_dir, start=start, end=end)
        n = len(frames)
        print(f"[1/4] {n} frames extraherade")

        if n < 2:
            print("      För få frames — hoppar över.")
            return None

        # ── Steg 2: Motion-delta ──────────────────────────────────────────
        print(f"[2/4] Motion-delta (tröskel={delta_threshold})...")
        deltas = compute_deltas(frames, peak_threshold=delta_threshold)
        events = cluster_events(deltas, gap_frames=gap_frames)
        print_delta_summary(deltas, events)

        if not events:
            print("      Inga anomali-events hittades.\n")
            return AnalysisResult(video_path=video_path, metadata=meta)

        # ── Steg 3: Ollama pre-screen ─────────────────────────────────────
        candidate_events = []
        if use_ollama:
            print(f"[3/4] LLaVA pre-screen ({len(events)} events)...")
            candidate_events = screen_events(events)
        else:
            print(f"[3/4] Ollama hoppas över — skickar alla {len(events)} events till Claude")
            candidate_events = [(ev, {"confidence": 0.0, "description": "ej screenad"}) for ev in events]

        if not candidate_events:
            print("      Inga events klarade LLaVA-filtret.\n")
            return AnalysisResult(video_path=video_path, metadata=meta)

        # ── Steg 4: Claude deep-analyze ───────────────────────────────────
        result = AnalysisResult(video_path=video_path, metadata=meta)

        if use_claude:
            print(f"[4/4] Claude analyserar {len(candidate_events)} event(s)...")
            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)
            frame_counter = 0

            for ev, screen_result in candidate_events:
                print(f"\n  Event {ev.event_id} — {len(ev.frames)} frames (peak={ev.peak:.1f})")
                print(f"  LLaVA: {screen_result.get('description','')[:70]}")

                for fr_delta in ev.frames:
                    frame_counter += 1
                    fr = analyze_frame(client, fr_delta.frame_path, fr_delta.frame_index)
                    # Berika med delta-info
                    fr.frame_notes = (
                        f"[delta={fr_delta.peak_delta:.1f}] {fr.frame_notes}"
                    )
                    result.frame_results.append(fr)

            print(f"\n[4/4] Claude klar. {len(result.flagged_frames)} flaggade frames.\n")
        else:
            print("[4/4] Claude hoppas över (--no-claude)")
            # Lägg till event-frames i resultatet som ej analyserade
            for ev, _ in candidate_events:
                for fr_delta in ev.frames:
                    result.frame_results.append(FrameResult(
                        frame_path=fr_delta.frame_path,
                        frame_index=fr_delta.frame_index,
                        objects=[],
                        unknown_detected=True,
                        frame_notes=f"[delta={fr_delta.peak_delta:.1f}] ej Claude-analyserad",
                    ))

        return result

    finally:
        if not keep_frames:
            shutil.rmtree(out_dir, ignore_errors=True)


def cmd_analyze(args):
    """Analysera en eller flera videofiler."""
    _banner()

    # Samla videofiler
    video_files: list[str] = []
    if args.video:
        video_files = [args.video]
    elif args.folder:
        folder = Path(args.folder)
        video_files = sorted(
            str(f) for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        )
        if not video_files:
            print(f"[FEL] Inga videofiler hittades i: {args.folder}")
            return 1
        print(f"\n  Hittade {len(video_files)} videofiler i {args.folder}\n")

    all_results: list[AnalysisResult] = []

    for vf in video_files:
        result = analyze_single(
            video_path=vf,
            fps=args.fps,
            delta_threshold=args.delta_threshold,
            gap_frames=args.gap_frames,
            use_ollama=not args.no_ollama,
            use_claude=not args.no_claude,
            keep_frames=args.keep_frames,
            start=args.start,
            end=args.end,
        )
        if result:
            all_results.append(result)
            if result.frame_results:
                print_report(result)

    # Sammanfattning för batch
    if len(all_results) > 1:
        total_flagged = sum(len(r.flagged_frames) for r in all_results)
        print("=" * 64)
        print(f"  BATCH-SAMMANFATTNING: {len(all_results)} filer")
        print(f"  Totalt flaggade frames: {total_flagged}")
        print("=" * 64)

    # Odoo-utkast?
    flagged_results = [r for r in all_results if r.flagged_frames]
    if flagged_results and not args.no_odoo:
        answer = input(f"\nSkapa encounter-utkast i Odoo för {len(flagged_results)} fil(er)? [y/N]: ").strip().lower()
        if answer == "y":
            from odoo_sync import get_env, create_draft_encounter
            env = get_env()
            for r in flagged_results:
                fname = Path(r.video_path).stem
                summary = [
                    {"frame": fr.frame_index, "notes": fr.frame_notes, "objects": fr.objects}
                    for fr in r.flagged_frames
                ]
                odoo_id = create_draft_encounter(env, {
                    "title_en": f"[CE5] {fname}",
                    "notes": json.dumps(summary, ensure_ascii=False, indent=2),
                })
                if odoo_id:
                    print(f"  [OK] {fname} → Odoo encounter ID {odoo_id}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="clio-uap pipeline — CE5 & UAP-analys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command")

    a = sub.add_parser("analyze", help="Analysera video(er) med full pipeline")

    # Input
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", help="Sökväg till en videofil")
    src.add_argument("--folder", help="Mapp med videofiler (batch)")

    # Tidssegment
    a.add_argument("--start", default=None, help="Starttid, t.ex. '1:30' eller '90'")
    a.add_argument("--end",   default=None, help="Sluttid, t.ex. '2:00' eller '120'")

    # Frame-extraktion
    a.add_argument("--fps", type=float, default=4.0,
                   help="Frames per speluppspelningssekund (standard: 4)")

    # Motion-delta
    a.add_argument("--delta-threshold", type=float, default=12.0,
                   help="Cell-delta-tröskel för anomali-detektion (standard: 12)")
    a.add_argument("--gap-frames", type=int, default=4,
                   help="Max gap-frames inom ett event (standard: 4)")

    # Pipeline-steg
    a.add_argument("--no-ollama", action="store_true",
                   help="Hoppa över LLaVA pre-screen")
    a.add_argument("--no-claude", action="store_true",
                   help="Hoppa över Claude-analys (kör bara delta + Ollama)")
    a.add_argument("--no-odoo",   action="store_true",
                   help="Skapa inte encounter-utkast i Odoo")

    # Övrigt
    a.add_argument("--keep-frames", action="store_true",
                   help="Behåll extraherade frames efter analys")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return
    if args.command == "analyze":
        sys.exit(cmd_analyze(args))


if __name__ == "__main__":
    main()
