"""
check_deps.py — Beroendecheck för clio-core
Kör: python check_deps.py

clio-core använder enbart stdlib. Kontrollerar att paketet är importerbart
och att kärnmodulerna finns.
"""

import importlib
import importlib.metadata
import sys

MODULE_NAME = "clio-core"

REQUIRED = [
    # (import-namn,         kommentar)
    ("clio_core",           "pip install -e ./clio-core  ELLER  pip install -e ../clio-core"),
    ("clio_core.utils",     "del av clio-core-paketet"),
    ("clio_core.banner",    "del av clio-core-paketet"),
]


def check(verbose: bool = True) -> bool:
    missing = []
    for import_name, hint in REQUIRED:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(f"{import_name}  →  {hint}")

    if missing:
        if verbose:
            print(f"\n[FEL] {MODULE_NAME} — saknade beroenden:")
            for item in missing:
                print(f"  {item}")
        return False

    if verbose:
        try:
            ver = importlib.metadata.version("clio-core")
            print(f"[OK]  {MODULE_NAME} {ver} — alla moduler importerbara")
        except Exception:
            print(f"[OK]  {MODULE_NAME} — alla moduler importerbara")
    return True


if __name__ == "__main__":
    ok = check(verbose=True)
    sys.exit(0 if ok else 1)
