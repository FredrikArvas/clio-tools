"""
check_deps.py — Beroendecheck för clio-agent-mail
Kör: python check_deps.py

Kontrollerar att alla paket som krävs för just detta delprogram är installerade.
Används även av check_all.py i projektroten.
"""

import importlib
import sys

MODULE_NAME = "clio-agent-mail"

REQUIRED = [
    # (import-namn,       pip-paketnamn)
    ("anthropic",         "anthropic>=0.25.0"),
    ("dotenv",            "python-dotenv>=1.0.0"),
    ("notion_client",     "notion-client>=2.2.1"),
    ("clio_core",         "clio-core  (pip install -e ../clio-core  eller git+URL)"),
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
