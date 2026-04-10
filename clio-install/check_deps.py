"""
check_deps.py — Beroendecheck för clio-install
Kör: python check_deps.py

clio-install använder enbart stdlib — inga externa paket krävs.
"""

import importlib
import sys

MODULE_NAME = "clio-install"

REQUIRED = [
    # (import-namn,    pip-paketnamn / kommentar)
    ("argparse",       "stdlib"),
    ("importlib",      "stdlib"),
    ("json",           "stdlib"),
    ("pathlib",        "stdlib"),
    ("subprocess",     "stdlib"),
    ("platform",       "stdlib"),
    ("shutil",         "stdlib"),
]


def check(verbose: bool = True) -> bool:
    missing = []
    for import_name, hint in REQUIRED:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(f"{import_name}  ({hint})")

    if missing:
        if verbose:
            print(f"\n[FEL] {MODULE_NAME} — saknade beroenden:")
            for pkg in missing:
                print(f"  {pkg}")
        return False

    if verbose:
        print(f"[OK]  {MODULE_NAME} — alla beroenden tillgängliga (stdlib)")
    return True


if __name__ == "__main__":
    ok = check(verbose=True)
    sys.exit(0 if ok else 1)
