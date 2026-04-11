#!/usr/bin/env python3
"""
clio-audio-edit.py — Del av clio-tools
Transkriberar, annoterar och klipper ljudinspelningar.

Flöde:
  1. faster-whisper transkriberar med tidsstämplar
  2. Claude API annoterar transkriptet med klippförslag
  3. Du granskar och justerar det annoterade manuset
  4. ffmpeg klipper mot godkänt manus

Användning:
  python clio-audio-edit.py --input session.wav --profile remote_viewing
  python clio-audio-edit.py --apply session_annotated.txt --input session.wav
  python clio-audio-edit.py --input session.wav --profile remote_viewing --no-claude
  python clio-audio-edit.py --list-profiles
"""

import argparse
import sys
from pathlib import Path

SUPPORTED_FORMATS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".mp4"}

# ANSI-färger
_GRN = "\033[92m"
_YEL = "\033[93m"
_CYN = "\033[96m"
_GRY = "\033[90m"
_BLD = "\033[1m"
_NRM = "\033[0m"

_WIDTH = 60


def _hr() -> None:
    print(f"{_CYN}{'─' * _WIDTH}{_NRM}")


def _section(title: str, lines: list[str]) -> None:
    print()
    _hr()
    print(f"  {_BLD}{title}{_NRM}")
    _hr()
    for line in lines:
        print(f"  {line}")
    _hr()


# ---------------------------------------------------------------------------
# Mappval + filval
# ---------------------------------------------------------------------------

def select_folder() -> Path | None:
    """Visar senaste mapp och låter användaren bekräfta eller ange ny."""
    from state import load_state, MODULE_NAME

    state  = load_state()
    last   = state.get("last_folder", {}).get(MODULE_NAME, "")
    recent = [f for f in reversed(state.get("recent_folders", [])) if f != last]

    if last:
        short = ("..." + last[-50:]) if len(last) > 53 else last
        _section("Senaste mapp", [
            f"{_YEL}J{_NRM}  {short}",
            f"{_GRY}n{_NRM}  Välj annan mapp",
        ])
        answer = input("Använd samma? [J/n]: ").strip().lower()
        if answer in ("", "j", "ja", "y", "yes"):
            return Path(last)

    if recent:
        lines = []
        for i, f in enumerate(recent[:5], 1):
            short = ("..." + f[-50:]) if len(f) > 53 else f
            lines.append(f"{_YEL}{i}{_NRM}  {short}")
        lines.append(f"{_GRY}0{_NRM}  Ange ny mapp")
        _section("Senast använda mappar", lines)
        val = input(f"Välj [0-{min(5, len(recent))}]: ").strip()
        if val.isdigit() and 1 <= int(val) <= len(recent[:5]):
            return Path(recent[int(val) - 1])

    folder = input("\nMapp med ljudfiler: ").strip().strip('"')
    return Path(folder) if folder else None


def select_audio_file(folder: Path) -> Path | list[Path] | None:
    """
    Listar ljudfiler i mappen med storlek.
    Returnerar en fil, en lista (Alla), eller None (Tillbaka).
    """
    while True:
        files = sorted(
            [p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_FORMATS],
            key=lambda p: p.name.lower(),
        )

        if not files:
            print(f"\n[VARNING] Inga ljudfiler hittades i: {folder}")
            return None

        lines = []
        for i, f in enumerate(files, 1):
            size_mb = f.stat().st_size / 1_048_576
            lines.append(f"{_YEL}{i:>2}{_NRM}  {f.name}  {_GRY}{size_mb:.1f} MB{_NRM}")
        lines.append("")
        lines.append(f"{_GRN} A{_NRM}  Alla filer ({len(files)} st)")
        lines.append(f"{_GRY} 0{_NRM}  Tillbaka — välj annan mapp")

        short = ("..." + str(folder)[-46:]) if len(str(folder)) > 49 else str(folder)
        _section(f"Ljudfiler  {_GRY}{short}{_NRM}", lines)

        val = input("Välj: ").strip().lower()

        if val == "0":
            return None
        if val == "a":
            return files
        if val.isdigit() and 1 <= int(val) <= len(files):
            chosen = files[int(val) - 1]
            print(f"\n  {_GRN}>{_NRM} {chosen.name}")
            return chosen

        print("  Ogiltigt val — försök igen.")


# ---------------------------------------------------------------------------
# Env + beroendekontroll
# ---------------------------------------------------------------------------

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=True)
    except ImportError:
        pass


def check_dependencies() -> None:
    missing = []

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        missing.append("faster-whisper>=1.0.0  →  pip install faster-whisper")

    try:
        import anthropic  # noqa: F401
    except ImportError:
        missing.append("anthropic              →  pip install anthropic")

    try:
        import ffmpeg  # noqa: F401
    except ImportError:
        missing.append("ffmpeg-python          →  pip install ffmpeg-python")

    if missing:
        print("\n[FEL] clio-audio-edit — saknade beroenden:")
        for m in missing:
            print(f"   {m}")
        print()
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="clio-audio-edit — Transkribera, annotera och klipp ljudinspelningar",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exempel:
  python clio-audio-edit.py --input session.wav --profile remote_viewing
  python clio-audio-edit.py --input session.wav --profile family_memory --no-claude
  python clio-audio-edit.py --apply session_annotated.txt --input session.wav
  python clio-audio-edit.py --list-profiles
        """,
    )
    parser.add_argument("--input",    type=Path, help="Ljudfil att bearbeta")
    parser.add_argument("--profile",  type=str,  default="remote_viewing",
                        help="Klippprofil (default: remote_viewing)")
    parser.add_argument("--apply",    type=Path, help="Applicera klipp från annoterat manus")
    parser.add_argument("--no-claude", action="store_true",
                        help="Hoppa över Claude-annotering — transkribera bara")
    parser.add_argument("--model",    type=str,  default="medium",
                        help="Whisper-modell: tiny, base, small, medium, large (default: medium)")
    parser.add_argument("--language", type=str,  default="sv",
                        help="Språk för transkribering (default: sv)")
    parser.add_argument("--list-profiles", action="store_true",
                        help="Lista tillgängliga profiler")
    return parser


def main(argv: list[str] | None = None) -> None:
    _load_env()
    check_dependencies()

    parser = build_parser()
    args   = parser.parse_args(argv)

    from state import save_last_folder
    from transcribe import transcribe, segments_to_text, save_transcript
    from annotate import annotate_with_claude, save_annotated
    from editor import parse_cut_list, apply_cuts, save_cutlog

    if args.list_profiles:
        from profiles import list_profiles
        list_profiles()
        sys.exit(0)

    # --apply: läs annoterat manus och klipp
    if args.apply:
        if not args.input:
            print("[FEL] --apply kräver också --input <originalljudfil>")
            sys.exit(1)

        for path, label in [(args.apply, "annoterat manus"), (args.input, "ljudfil")]:
            if not path.exists():
                print(f"[FEL] Filen finns inte ({label}): {path}")
                sys.exit(1)

        cuts         = parse_cut_list(args.apply)
        output_path  = args.input.with_stem(args.input.stem + "_edited")
        cutlog_path  = args.input.with_stem(args.input.stem + "_cutlog").with_suffix(".txt")

        apply_cuts(args.input, cuts, output_path)
        save_cutlog(cuts, cutlog_path)
        sys.exit(0)

    # Interaktivt mappval om --input saknas
    if not args.input:
        while True:
            folder = select_folder()
            if not folder or not folder.is_dir():
                print("[FEL] Ingen giltig mapp vald.")
                sys.exit(1)
            save_last_folder(str(folder))

            selection = select_audio_file(folder)
            if selection is None:
                continue
            break

        audio_files = selection if isinstance(selection, list) else [selection]
    else:
        if not args.input.exists():
            print(f"[FEL] Filen finns inte: {args.input}")
            sys.exit(1)
        audio_files = [args.input]

    for audio_path in audio_files:
        if not audio_path.exists():
            print(f"[FEL] Filen finns inte: {audio_path}")
            continue

        stem            = audio_path.stem
        transcript_path = audio_path.with_stem(stem + "_transcript").with_suffix(".txt")
        annotated_path  = audio_path.with_stem(stem + "_annotated").with_suffix(".txt")

        segments = transcribe(audio_path, model_size=args.model, language=args.language)
        save_transcript(segments, transcript_path)

        if args.no_claude:
            print("\n[OK]  --no-claude: Lägg till klippmarkeringar manuellt i transkriptet.")
            print(f"      Format: [KLIPP_START: HH:MM:SS | KLIPP_SLUT: HH:MM:SS]")
            print(f"      Kör sedan: python clio-audio-edit.py --apply {transcript_path} --input {audio_path}")
            continue

        transcript_text = segments_to_text(segments)
        annotated_text  = annotate_with_claude(transcript_text, args.profile)
        save_annotated(annotated_text, annotated_path)

    print("\n[OK]  Klart. Granska manuset och kör sedan --apply.")


if __name__ == "__main__":
    main()
