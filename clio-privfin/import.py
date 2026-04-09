#!/usr/bin/env python3
"""
import.py — Importerar Danske Bank XML och CSV till familjekonomi.db
Version: 1.0 | 2026-04-09

Användning:
    python import.py <fil.xml|fil.csv> --konto "Bilkontot" --agare "Fredrik"
    python import.py data/raw/ --konto "Bilkontot" --agare "Fredrik"  # hel mapp

Kontoutdragen ligger i: F:\\Dropbox\\ftg\\arvas_koncernen\\60_bokföring\\kontoutdrag\\
"""

import sqlite3
import hashlib
import json
import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET

DB_PATH = Path(__file__).parent / "familjekonomi.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
REGLER_PATH = Path(__file__).parent / "regler.json"

NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}


def init_db(conn):
    """Initierar databasen med schema om den inte finns."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def ensure_account(conn, account_id, namn, agare, bank="Danske Bank", typ="checking"):
    """Skapar kontot om det inte finns."""
    conn.execute("""
        INSERT OR IGNORE INTO accounts (account_id, namn, bank, typ, agare)
        VALUES (?, ?, ?, ?, ?)
    """, (account_id, namn, bank, typ, agare))
    conn.commit()


def make_tx_id(account_id, datum, belopp, text):
    """Skapar ett unikt ID per transaktion baserat på innehållet."""
    raw = f"{account_id}|{datum}|{belopp}|{text}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def parse_belopp(s):
    """Konverterar '39.111,00' eller '-4.124,29' till float."""
    s = s.strip().replace("\xa0", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".")
    return float(s)


def parse_xml(filepath, account_id, importfil):
    """Parsare för Danske Bank XML (SpreadsheetML-format)."""
    with open(filepath, encoding="windows-1252") as f:
        content = f.read()

    root = ET.fromstring(content)
    ws = root.find(".//ss:Worksheet", NS)
    table = ws.find("ss:Table", NS)
    rows = table.findall("ss:Row", NS)

    records = []
    for row in rows[1:]:  # hoppa över header
        cells = row.findall("ss:Cell", NS)
        vals = []
        for cell in cells:
            data = cell.find("ss:Data", NS)
            vals.append(data.text if data is not None else "")

        if len(vals) < 4:
            continue

        datum, text, belopp_raw, saldo_raw = vals[0], vals[1], vals[2], vals[3]
        status = vals[4] if len(vals) > 4 else ""
        avstamd = vals[5] if len(vals) > 5 else ""

        try:
            belopp = float(belopp_raw) if belopp_raw else 0.0
            saldo = float(saldo_raw) if saldo_raw else None
        except ValueError:
            belopp = parse_belopp(belopp_raw)
            saldo = parse_belopp(saldo_raw) if saldo_raw else None

        tx_id = make_tx_id(account_id, datum, belopp, text)
        records.append((tx_id, account_id, datum, text, belopp, saldo,
                        status, avstamd, importfil,
                        datetime.now().strftime("%Y-%m-%d")))
    return records


def parse_csv(filepath, account_id, importfil):
    """Parsare för Danske Bank CSV (semikolon, windows-1252)."""
    import csv
    records = []
    with open(filepath, encoding="windows-1252", newline="") as f:
        reader = csv.reader(f, delimiter=";", quotechar='"')
        header = next(reader)

        for row in reader:
            if len(row) < 4:
                continue
            datum, text, belopp_raw, saldo_raw = row[0], row[1], row[2], row[3]
            status = row[4] if len(row) > 4 else ""
            avstamd = row[5] if len(row) > 5 else ""

            belopp = parse_belopp(belopp_raw)
            saldo = parse_belopp(saldo_raw) if saldo_raw else None

            tx_id = make_tx_id(account_id, datum, belopp, text)
            records.append((tx_id, account_id, datum, text, belopp, saldo,
                            status, avstamd, importfil,
                            datetime.now().strftime("%Y-%m-%d")))
    return records


def insert_transactions(conn, records):
    """Infogar transaktioner, hoppar över dubletter (INSERT OR IGNORE)."""
    inserted = 0
    skipped = 0
    for rec in records:
        result = conn.execute("""
            INSERT OR IGNORE INTO transactions
            (tx_id, account_id, datum, text, belopp, saldo, status, avstamd, importfil, importdatum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rec)
        if result.rowcount:
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    return inserted, skipped


def apply_rules(conn):
    """Applicerar regler från regler.json på okategoriserade transaktioner."""
    with open(REGLER_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # Säkerställ att kategorier finns
    for kat in data["kategorier"]:
        conn.execute("""
            INSERT OR IGNORE INTO categories (cat_id, namn, typ, farg)
            VALUES (?, ?, ?, ?)
        """, (kat["cat_id"], kat["namn"], kat["typ"], kat.get("farg", "")))

    regler = data["regler"]
    kategoriserade = 0

    # Hämta okategoriserade transaktioner
    rows = conn.execute("""
        SELECT tx_id, text FROM transactions
        WHERE tx_id NOT IN (SELECT tx_id FROM tx_categorized)
    """).fetchall()

    for tx_id, text in rows:
        for regel in regler:
            if regel["monster"].lower() in text.lower():
                conn.execute("""
                    INSERT OR IGNORE INTO tx_categorized (tx_id, cat_id, confidence, kalla, kommentar)
                    VALUES (?, ?, 1.0, 'rule', ?)
                """, (tx_id, regel["cat_id"], regel.get("kommentar", "")))
                kategoriserade += 1
                break  # första matchande regel vinner

    conn.commit()
    return kategoriserade


def extract_account_id_from_filename(filename):
    """Försöker extrahera kontonummer från filnamn som 'Bilkontot-12010376889-20260409.xml'"""
    m = re.search(r"-(\d{8,})-", filename)
    return m.group(1) if m else None


def main():
    parser = argparse.ArgumentParser(description="Importera Danske Bank-kontoutdrag")
    parser.add_argument("fil", help="XML- eller CSV-fil, eller mapp med filer")
    parser.add_argument("--konto", required=True, help="Kontonamn, t.ex. 'Bilkontot'")
    parser.add_argument("--agare", required=True, help="Fredrik | Ulrika | Gemensamt")
    parser.add_argument("--bank", default="Danske Bank")
    parser.add_argument("--typ", default="checking", help="checking | savings | credit | loan")
    parser.add_argument("--db", default=str(DB_PATH), help="Sökväg till SQLite-databasen")
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = sqlite3.connect(db_path)
    init_db(conn)

    # Samla filer
    fil_path = Path(args.fil)
    filer = []
    if fil_path.is_dir():
        filer = list(fil_path.glob("*.xml")) + list(fil_path.glob("*.csv"))
    else:
        filer = [fil_path]

    # Filtrera bort CSV om XML med samma namn finns (undvik dubletter)
    xml_stammar = {f.stem for f in filer if f.suffix.lower() == ".xml"}
    filer = [f for f in filer if not (f.suffix.lower() == ".csv" and f.stem in xml_stammar)]

    print(f"Importerar {len(filer)} fil(er) till {db_path.name}")

    totalt_in = 0
    totalt_skip = 0

    for fil in filer:
        account_id = extract_account_id_from_filename(fil.name) or args.konto.lower().replace(" ", "_")
        ensure_account(conn, account_id, args.konto, args.agare, args.bank, args.typ)

        if fil.suffix.lower() == ".xml":
            records = parse_xml(fil, account_id, fil.name)
        elif fil.suffix.lower() == ".csv":
            records = parse_csv(fil, account_id, fil.name)
        else:
            print(f"  Hoppar {fil.name} — okänt format")
            continue

        ins, skip = insert_transactions(conn, records)
        print(f"  {fil.name}: {ins} nya, {skip} dubletter")
        totalt_in += ins
        totalt_skip += skip

    kat = apply_rules(conn)
    print(f"\nSummering:")
    print(f"  Importerade: {totalt_in} transaktioner")
    print(f"  Dubletter:   {totalt_skip}")
    print(f"  Kategoriserade: {kat} (regelmotor)")

    conn.close()


if __name__ == "__main__":
    main()
