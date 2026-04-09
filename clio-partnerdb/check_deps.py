"""
check_deps.py — Verify clio-partnerdb dependencies and DB health.
Follows the clio-tools check_deps pattern.
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Force UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def check() -> list[str]:
    errors = []

    # Python version
    if sys.version_info < (3, 9):
        errors.append(f"Python 3.9+ required, found {sys.version}")

    # sqlite3 (stdlib)
    try:
        import sqlite3
        _ = sqlite3.sqlite_version
    except ImportError:
        errors.append("sqlite3 not available (stdlib — should never happen)")

    # python-gedcom
    try:
        from gedcom.parser import Parser  # noqa: F401
    except ImportError:
        errors.append("python-gedcom not installed — run: pip install python-gedcom")

    # DB file and schema
    try:
        import db as _db
        db_path = _db.get_db_path()
        if not os.path.exists(db_path):
            print(f"  ℹ DB not yet created at {db_path} — will be created on first connect()")
            return errors  # not an error
        else:
            conn = _db.connect(db_path)
            version = _db.schema_version(conn)
            conn.close()
            if version < 1:
                errors.append(f"DB schema version {version} is outdated — run connect() to migrate")
    except Exception as e:
        errors.append(f"DB check failed: {e}")

    return errors


def main(argv=None):
    print("clio-partnerdb dependency check")
    print("-" * 40)
    errors = check()
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        import db as _db
        db_path = _db.get_db_path()
        print(f"  ✓ Python {sys.version.split()[0]}")
        print(f"  ✓ sqlite3")
        print(f"  ✓ python-gedcom")
        print(f"  ✓ DB: {db_path}")
        print("\nAll checks passed.")


if __name__ == "__main__":
    main()
