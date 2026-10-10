"""
adjust_lrc.py — Genererar LRC-fil från transkript + klipplogg.

Räknar om tidkoderna i transkriptet relativt den klippta ljudfilen:
  - Segment som faller inom ett klipp utelämnas
  - Övriga segments tidkoder justeras med ackumulerad bortklippt tid

Användning:
  python adjust_lrc.py --transcript session_transcript.txt --cutlog session_cutlog.txt
  python adjust_lrc.py --transcript session_transcript.txt --cutlog session_cutlog.txt \\
      --title "Fridas session" --artist "Coaching" --output session.lrc
"""

import argparse
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_hms(ts: str) -> float:
    """Konverterar 'HH:MM:SS' till sekunder (float)."""
    parts = ts.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Ogiltigt tidformat: {ts!r}")
    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    return h * 3600 + m * 60 + s


def _parse_cutlog(path: Path) -> list[tuple[float, float]]:
    """
    Läser cutlog och returnerar lista av (start_sec, end_sec).
    Hoppas över kommentarsrader (börjar med #) och tomma rader.
    """
    clips = []
    pattern = re.compile(
        r"Klipp\s+\d+:\s+(\d{2}:\d{2}:\d{2})\s+-->\s+(\d{2}:\d{2}:\d{2})"
    )
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pattern.search(line)
        if m:
            clips.append((_parse_hms(m.group(1)), _parse_hms(m.group(2))))
    return clips


def _parse_transcript(path: Path) -> list[tuple[float, str]]:
    """
    Läser transkript och returnerar lista av (start_sec, text).
    Förväntat format: [HH:MM:SS] text
    """
    segments = []
    pattern = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            segments.append((_parse_hms(m.group(1)), m.group(2).strip()))
    return segments


# ---------------------------------------------------------------------------
# Tidkodsomräkning
# ---------------------------------------------------------------------------

def _is_clipped(t: float, clips: list[tuple[float, float]]) -> bool:
    """Returnerar True om tidpunkten t faller inom ett klipp."""
    return any(start <= t < end for start, end in clips)


def _cumulative_removed(t: float, clips: list[tuple[float, float]]) -> float:
    """Beräknar total bortklippt tid före tidpunkten t."""
    removed = 0.0
    for start, end in clips:
        if end <= t:
            removed += end - start
        elif start < t:
            removed += t - start
    return removed


def adjust_timestamps(
    segments: list[tuple[float, str]],
    clips: list[tuple[float, float]],
) -> list[tuple[float, str]]:
    """
    Filtrerar bort segment i klippta intervall och justerar
    återstående segments tidkoder relativt den klippta filen.
    """
    adjusted = []
    for t, text in segments:
        if _is_clipped(t, clips):
            continue
        new_t = t - _cumulative_removed(t, clips)
        adjusted.append((max(0.0, new_t), text))
    return adjusted


# ---------------------------------------------------------------------------
# LRC-generering
# ---------------------------------------------------------------------------

def _fmt_lrc_timestamp(seconds: float) -> str:
    """Konverterar sekunder till LRC-format [mm:ss.xx]."""
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = total_s // 60
    return f"[{m:02d}:{s:02d}.{cs:02d}]"


def build_lrc(
    segments: list[tuple[float, str]],
    title: str = "",
    artist: str = "",
) -> str:
    lines = []
    if title:
        lines.append(f"[ti:{title}]")
    if artist:
        lines.append(f"[ar:{artist}]")
    if lines:
        lines.append("")
    for t, text in segments:
        lines.append(f"{_fmt_lrc_timestamp(t)}{text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="adjust_lrc — Genererar LRC från transkript + klipplogg",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exempel:
  python adjust_lrc.py --transcript session_transcript.txt --cutlog session_cutlog.txt
  python adjust_lrc.py --transcript session_transcript.txt --cutlog session_cutlog.txt \\
      --title "Sessionsnamn" --artist "Coach" --output session.lrc
        """,
    )
    parser.add_argument("--transcript", type=Path, required=True,
                        help="Transkriptfil (_transcript.txt)")
    parser.add_argument("--cutlog",     type=Path, required=True,
                        help="Klipplogg (_cutlog.txt)")
    parser.add_argument("--output",     type=Path,
                        help="LRC-utfil (default: <transkript-stem>.lrc)")
    parser.add_argument("--title",      type=str, default="",
                        help="[ti:] tagg i LRC-filen")
    parser.add_argument("--artist",     type=str, default="",
                        help="[ar:] tagg i LRC-filen")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    for path, label in [(args.transcript, "transkript"), (args.cutlog, "klipplogg")]:
        if not path.exists():
            print(f"[FEL] Filen finns inte ({label}): {path}")
            sys.exit(1)

    clips = _parse_cutlog(args.cutlog)
    segments = _parse_transcript(args.transcript)

    if not clips:
        print("[VARNING] Inga klipp hittades i cutlog — LRC genereras utan tidsjustering.")
    if not segments:
        print("[FEL] Inga segment hittades i transkriptet.")
        sys.exit(1)

    adjusted = adjust_timestamps(segments, clips)

    output = args.output or args.transcript.with_name(
        args.transcript.stem.replace("_transcript", "") + ".lrc"
    )
    lrc_text = build_lrc(adjusted, title=args.title, artist=args.artist)
    output.write_text(lrc_text, encoding="utf-8")

    clipped_count = len(segments) - len(adjusted)
    print(f"[OK]  {len(adjusted)} segment → {output.name}")
    print(f"       {clipped_count} segment utelämnade (faller inom klipp)")
    print(f"       {len(clips)} klipp kompenserade i tidkoderna")


if __name__ == "__main__":
    main()
