"""
check_deps.py — Beroendecheck för clio-docs
Kör: python check_deps.py
"""
import importlib
import sys

MODULE_NAME = "clio-docs"

REQUIRED = [
    ("clio_core",    "clio-core  (pip install -e ../clio-core)"),
    ("ocrmypdf",     "ocrmypdf>=16.0.0"),
    ("pypdf",        "pypdf>=4.0.0"),
    ("fitz",         "pymupdf>=1.23.0"),
    ("pytesseract",  "pytesseract>=0.3.10"),
    ("PIL",          "Pillow>=10.0.0"),
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
