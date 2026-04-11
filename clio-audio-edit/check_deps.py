"""
check_deps.py — Beroendecheck för clio-audio-edit
Kör: python check_deps.py
"""
import importlib
import shutil
import sys

MODULE_NAME = "clio-audio-edit"

REQUIRED = [
    ("faster_whisper", "faster-whisper>=1.0.0"),
    ("anthropic",      "anthropic"),
    ("ffmpeg",         "ffmpeg-python"),
    ("dotenv",         "python-dotenv>=1.0.0"),
]


def check(verbose: bool = True) -> bool:
    missing = []

    for import_name, install_hint in REQUIRED:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(install_hint)

    # ffmpeg-binären måste också finnas i PATH
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg (binär i PATH — https://ffmpeg.org/download.html)")

    if missing:
        if verbose:
            print(f"\n[FEL] {MODULE_NAME} — saknade beroenden:")
            for pkg in missing:
                print(f"  pip install {pkg}")
        return False

    if verbose:
        print(f"[OK]  {MODULE_NAME} — alla beroenden installerade")
    return True


if __name__ == "__main__":
    ok = check(verbose=True)
    sys.exit(0 if ok else 1)
