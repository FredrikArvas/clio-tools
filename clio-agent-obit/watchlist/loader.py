"""
watchlist/loader.py — Load watch entries for clio-agent-obit.

Sprint 2: Reads from clio-partnerdb (SQLite) via matcher.load_entries_from_db().
          CSV loading kept for backwards compatibility and testing.

The canonical data source is now the DB. CSV is an export/import format.
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Optional

# partnerdb path
_PARTNERDB = os.path.join(os.path.dirname(__file__), "..", "..", "clio-partnerdb")
sys.path.insert(0, _PARTNERDB)
import db as _partnerdb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from matcher import WatchlistEntry, load_entries_from_db


def load_watchlist_from_db(owner_email: str,
                            db_path: Optional[str] = None) -> list[WatchlistEntry]:
    """Load watch entries for an owner from partnerdb."""
    conn = _partnerdb.connect(db_path)
    return load_entries_from_db(conn, owner_email)


def load_watchlist(path: str) -> list[WatchlistEntry]:
    """
    Load from CSV (legacy / testing path).
    Used by test_runner.py and for round-trip verification.
    """
    VALID_PRIORITIES = {"viktig", "normal", "bra_att_veta"}

    entries: list[WatchlistEntry] = []
    if not os.path.exists(path):
        raise FileNotFoundError(f"Watch list not found: {path}")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(line for line in f if not line.lstrip().startswith("#"))
        for i, row in enumerate(reader, start=2):
            try:
                entry = _parse_csv_row(row, i, VALID_PRIORITIES)
                if entry:
                    entries.append(entry)
            except Exception as e:
                print(f"[watchlist] Warning row {i}: {e} — skipping")

    return entries


def _parse_csv_row(row: dict, line: int, valid_priorities: set) -> Optional[WatchlistEntry]:
    efternamn = row.get("efternamn", "").strip()
    fornamn   = row.get("fornamn", "").strip()
    if not efternamn or not fornamn:
        return None

    prioritet = row.get("prioritet", "normal").strip().lower()
    if prioritet not in valid_priorities:
        prioritet = "normal"

    kalla = row.get("kalla", "manuell").strip().lower()

    fodelsear: Optional[int] = None
    fodelsear_str = row.get("fodelsear", "").strip()
    fodelsear_approx = False
    if fodelsear_str:
        try:
            fodelsear = int(fodelsear_str)
            if not (1880 <= fodelsear <= 2010):
                print(f"[watchlist] Row {line}: birth year {fodelsear} seems unlikely")
        except ValueError:
            pass

    # Support fodelsear_approx column for test cases
    approx_str = row.get("fodelsear_approx", "").strip()
    if approx_str:
        try:
            fodelsear = int(approx_str)
            fodelsear_approx = True
        except ValueError:
            pass

    hemort = row.get("hemort", "").strip() or None

    return WatchlistEntry(
        efternamn=efternamn,
        fornamn=fornamn,
        fodelsear=fodelsear,
        hemort=hemort,
        prioritet=prioritet,
        kalla=kalla,
        fodelsear_approx=fodelsear_approx,
    )


def append_entry(entry: WatchlistEntry, path: str) -> None:
    """Append to CSV (used by legacy callers and invitation export)."""
    existing = load_watchlist(path) if os.path.exists(path) else []
    key = (entry.efternamn.lower(), entry.fornamn.lower())
    for e in existing:
        if (e.efternamn.lower(), e.fornamn.lower()) == key:
            return

    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["efternamn", "fornamn", "fodelsear", "hemort", "prioritet", "kalla"]
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "efternamn": entry.efternamn,
            "fornamn":   entry.fornamn,
            "fodelsear": entry.fodelsear or "",
            "hemort":    entry.hemort or "",
            "prioritet": entry.prioritet,
            "kalla":     entry.kalla,
        })
