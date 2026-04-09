"""
watchlist/import_contacts.py — Importerar adressbok CSV till watchlist

Tar en CSV-export från adressboken (sorterad på kontaktfrekvens)
och mappar kolumnerna till watchlist-format.

Prioritet baseras på position i listan (frekvens-sorterad):
  Topp 20%  → "viktig"
  Nästa 40% → "normal"
  Resten    → "bra_att_veta"

CC: Exportformatet från din adressbok behöver verifieras.
    Google Contacts exporterar t.ex. med kolumnnamnen:
    "Given Name", "Family Name", "E-mail 1 - Value" etc.
    Justera COLUMN_MAP nedan efter faktisk export.

Körning:
    python import_contacts.py --contacts path/to/contacts.csv
    python import_contacts.py --contacts path/to/contacts.csv --dry-run
    python import_contacts.py --contacts path/to/contacts.csv --preview-columns
"""

from __future__ import annotations

import argparse
import csv
import sys
from typing import Optional

from loader import append_entry
from matcher import WatchlistEntry

# CC: Justera dessa kolumnnamn efter hur din adressbok-export ser ut.
# Kör med --preview-columns för att se kolumnnamnen i din fil.
COLUMN_MAP = {
    "fornamn":   ["Given Name", "Förnamn", "First Name", "fornamn"],
    "efternamn": ["Family Name", "Efternamn", "Last Name", "Surname", "efternamn"],
    "hemort":    ["City", "Stad", "Ort", "hemort"],
    # Födelseår finns sällan i adressböcker — lämnas tomt
}


def _find_column(row: dict, candidates: list[str]) -> Optional[str]:
    """Hittar rätt kolumnnamn ur en lista av kandidater."""
    for c in candidates:
        if c in row:
            return row[c].strip() or None
    return None


def determine_priority(index: int, total: int) -> str:
    """Beräknar prioritet baserat på position i frekvens-sorterad lista."""
    ratio = index / total if total > 0 else 1
    if ratio < 0.20:
        return "viktig"
    elif ratio < 0.60:
        return "normal"
    else:
        return "bra_att_veta"


def parse_contacts(contacts_path: str) -> list[WatchlistEntry]:
    """Parsar adressbok-CSV och returnerar WatchlistEntry-lista."""
    entries: list[WatchlistEntry] = []
    skipped = 0

    with open(contacts_path, newline="", encoding="utf-8-sig") as f:
        # utf-8-sig hanterar BOM från Windows-exporterade filer
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)

    for i, row in enumerate(rows):
        fornamn = _find_column(row, COLUMN_MAP["fornamn"])
        efternamn = _find_column(row, COLUMN_MAP["efternamn"])

        if not fornamn or not efternamn:
            skipped += 1
            continue

        hemort = _find_column(row, COLUMN_MAP["hemort"])
        prioritet = determine_priority(i, total)

        entry = WatchlistEntry(
            efternamn=efternamn,
            fornamn=fornamn,
            fodelsear=None,   # Adressböcker har sällan födelseår
            hemort=hemort,
            prioritet=prioritet,
            kalla="adressbok",
        )
        entries.append(entry)

    print(f"[import_contacts] Hittade {len(entries)} kontakter, hoppade över {skipped}")
    return entries


def preview_columns(contacts_path: str) -> None:
    """Visar kolumnnamnen i CSV-filen för att hjälpa med COLUMN_MAP."""
    with open(contacts_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        print("Kolumner i filen:")
        for col in reader.fieldnames or []:
            print(f"  '{col}'")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Importera adressbok CSV till watchlist.csv")
    p.add_argument("--contacts", required=True, help="Sökväg till adressbok-CSV")
    p.add_argument("--dry-run", action="store_true", help="Visa utan att skriva")
    p.add_argument("--preview-columns", action="store_true", help="Visa kolumnnamn i filen")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.preview_columns:
        preview_columns(args.contacts)
        return

    entries = parse_contacts(args.contacts)

    if args.dry_run:
        print(f"\n--- DRY RUN: {len(entries)} poster skulle läggas till ---")
        for e in entries[:20]:
            print(f"  [{e.prioritet}] {e.fornamn} {e.efternamn} ({e.hemort or '?'})")
        if len(entries) > 20:
            print(f"  ... och {len(entries) - 20} till")
        return

    added = 0
    for entry in entries:
        try:
            append_entry(entry)
            added += 1
        except Exception as ex:
            print(f"[import_contacts] Fel: {ex}")

    print(f"[import_contacts] Klart. {added} poster tillagda i watchlist.csv")


if __name__ == "__main__":
    main()
