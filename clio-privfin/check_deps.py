"""
check_deps.py — Beroendecheck för clio-privfin
Kör: python check_deps.py

clio-privfin använder enbart stdlib (sqlite3, json, argparse, re, pathlib).
Kontrollerar att databasen är åtkomlig om den finns.
"""

import importlib
import sys
from pathlib import Path

MODULE_NAME = "clio-privfin"

REQUIRED = [
    ("sqlite3",  "stdlib"),
    ("json",     "stdlib"),
    ("argparse", "stdlib"),
    ("re",       "stdlib"),
    ("pathlib",  "stdlib"),
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
            print(f"\n[FEL] {MODULE_NAME} — saknade stdlib-moduler:")
            for item in missing:
                print(f"  {item}")
        return False

    # Kolla om databasen finns (inte ett fel om den saknas — skapas vid import)
    db_path = Path(__file__).parent / "familjekonomi.db"
    if verbose:
        if db_path.exists():
            size_kb = db_path.stat().st_size // 1024
            print(f"[OK]  {MODULE_NAME} — alla stdlib-moduler OK")
            print(f"      Databas: {db_path} ({size_kb} KB)")
        else:
            print(f"[OK]  {MODULE_NAME} — alla stdlib-moduler OK")
            print(f"      Databas saknas — skapas automatiskt vid: python import.py <fil>")
    return True


if __name__ == "__main__":
    ok = check(verbose=True)
    sys.exit(0 if ok else 1)
