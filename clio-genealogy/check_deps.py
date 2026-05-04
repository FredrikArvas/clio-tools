"""
check_deps.py — Beroendecheck för clio-research
Kör: python check_deps.py
"""
import importlib
import sys

MODULE_NAME = "clio-research"

REQUIRED = [
    ("notion_client", "notion-client>=2.2.1"),
    ("requests",      "requests>=2.31.0"),
    ("dotenv",        "python-dotenv>=1.0.0"),
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
