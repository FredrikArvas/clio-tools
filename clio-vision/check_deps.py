"""
check_deps.py — Beroendecheck för clio-vision
Kör: python check_deps.py
"""
import importlib
import sys

MODULE_NAME = "clio-vision"

REQUIRED = [
    ("clio_core",     "clio-core  (pip install -e ../clio-core)"),
    ("anthropic",     "anthropic>=0.25.0"),
    ("dotenv",        "python-dotenv>=1.0.0"),
    ("PIL",           "Pillow>=10.0.0"),
    ("exiftool",      "pyexiftool>=0.5.0"),
]


def check(verbose: bool = True) -> bool:
    missing = []
    for import_name, install_hint in REQUIRED:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(install_hint)

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
