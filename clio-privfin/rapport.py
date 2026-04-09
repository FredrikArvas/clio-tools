#!/usr/bin/env python3
"""
rapport.py — Rapportgenerator för familjekonomi.db
Version: 1.0 | 2026-04-09

Användning:
    python rapport.py media              # mediaprenumerationer
    python rapport.py el                 # elkostnader
    python rapport.py okategoriserade    # visa vad som saknar kategori
    python rapport.py manad 2026-01      # alla transaktioner en månad
    python rapport.py kategori mat       # alla transaktioner i kategori
    python rapport.py transfers          # interna transfereringar
    python rapport.py sammanstallning    # översikt alla kategorier
"""

import sqlite3
import sys
from pathlib import Path

# Windows-terminal: tvinga UTF-8 för att hantera emojis
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).parent / "familjekonomi.db"


def get_conn():
    if not DB_PATH.exists():
        print(f"Databasen hittades inte: {DB_PATH}")
        print("Kör import.py först.")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


def sep():
    print("-" * 60)


def kr(belopp):
    return f"{belopp:,.2f} kr".replace(",", " ").replace(".", ",")


def rapport_media(conn):
    """Testfall 1: Mediaprenumerationer"""
    print("\n📺 MEDIAPRENUMERATIONER")
    sep()
    rows = conn.execute("""
        SELECT t.datum, t.text, t.belopp, a.namn AS konto
        FROM transactions t
        JOIN accounts a ON t.account_id = a.account_id
        JOIN tx_categorized tc ON t.tx_id = tc.tx_id
        JOIN categories c ON tc.cat_id = c.cat_id
        WHERE c.cat_id = 'media'
        ORDER BY t.datum DESC
    """).fetchall()

    if not rows:
        print("Inga mediaprenumerationer hittade — lägg till fler konton eller regler.")
        return

    total = 0
    for datum, text, belopp, konto in rows:
        print(f"  {datum}  {text:<30} {kr(belopp):>12}  [{konto}]")
        total += belopp

    sep()
    print(f"  Totalt: {kr(total)}")

    # Per tjänst
    print("\n  Per tjänst (estimat, senaste förekomsten):")
    tjanster = conn.execute("""
        SELECT t.text, COUNT(*) as antal, SUM(t.belopp) as totalt, AVG(t.belopp) as snitt
        FROM transactions t
        JOIN tx_categorized tc ON t.tx_id = tc.tx_id
        WHERE tc.cat_id = 'media'
        GROUP BY t.text
        ORDER BY SUM(t.belopp)
    """).fetchall()
    for text, antal, totalt, snitt in tjanster:
        print(f"  {text:<30} {antal} ggr  snitt {kr(snitt):>10}/mån  totalt {kr(totalt):>12}")


def rapport_el(conn):
    """Testfall 2: Elkostnader"""
    print("\n⚡ ELKOSTNADER")
    sep()
    rows = conn.execute("""
        SELECT t.datum, t.text, t.belopp, c.namn, a.namn AS konto
        FROM transactions t
        JOIN accounts a ON t.account_id = a.account_id
        JOIN tx_categorized tc ON t.tx_id = tc.tx_id
        JOIN categories c ON tc.cat_id = c.cat_id
        WHERE c.cat_id IN ('el-nat', 'el-handel')
        ORDER BY t.datum DESC
    """).fetchall()

    if not rows:
        print("Inga eltransaktioner hittade — importera hushållskonton.")
        return

    total = 0
    for datum, text, belopp, kategori, konto in rows:
        print(f"  {datum}  {text:<30} {kr(belopp):>12}  {kategori}")
        total += belopp

    sep()
    print(f"  Totalt el: {kr(total)}")

    # Nät vs handel
    for cat in ['el-nat', 'el-handel']:
        sub = conn.execute("""
            SELECT SUM(t.belopp) FROM transactions t
            JOIN tx_categorized tc ON t.tx_id = tc.tx_id
            WHERE tc.cat_id = ?
        """, (cat,)).fetchone()[0]
        if sub:
            label = "Nät (Vattenfall)" if cat == "el-nat" else "Handel (Godel)"
            print(f"  {label}: {kr(sub)}")


def rapport_okategoriserade(conn):
    """Visa transaktioner utan kategori — för att bygga fler regler."""
    print("\n❓ OKATEGORISERADE TRANSAKTIONER")
    sep()
    rows = conn.execute("""
        SELECT t.datum, t.text, t.belopp, a.namn
        FROM transactions t
        JOIN accounts a ON t.account_id = a.account_id
        WHERE t.tx_id NOT IN (SELECT tx_id FROM tx_categorized)
        ORDER BY ABS(t.belopp) DESC
    """).fetchall()

    if not rows:
        print("  Alla transaktioner är kategoriserade! 🎉")
        return

    print(f"  {len(rows)} okategoriserade transaktioner:\n")
    for datum, text, belopp, konto in rows:
        print(f"  {datum}  {text:<35} {kr(belopp):>12}  [{konto}]")


def rapport_manad(conn, manad):
    """Alla transaktioner en given månad (YYYY-MM)."""
    print(f"\n📅 TRANSAKTIONER {manad}")
    sep()
    rows = conn.execute("""
        SELECT t.datum, t.text, t.belopp, a.namn, COALESCE(c.namn, '?') AS kat, COALESCE(c.typ, '?') AS typ
        FROM transactions t
        JOIN accounts a ON t.account_id = a.account_id
        LEFT JOIN tx_categorized tc ON t.tx_id = tc.tx_id
        LEFT JOIN categories c ON tc.cat_id = c.cat_id
        WHERE t.datum LIKE ?
        ORDER BY t.datum, t.belopp
    """, (f"{manad}%",)).fetchall()

    income = expense = transfer = 0
    for datum, text, belopp, konto, kat, typ in rows:
        print(f"  {datum}  {text:<30} {kr(belopp):>12}  {kat}")
        if typ == "income":
            income += belopp
        elif typ == "expense":
            expense += belopp
        elif typ == "transfer":
            transfer += belopp

    sep()
    print(f"  Inkomster:     {kr(income)}")
    print(f"  Utgifter:      {kr(expense)}")
    print(f"  Transfereringar: {kr(transfer)}")
    print(f"  Netto:         {kr(income + expense)}")


def rapport_sammanstallning(conn):
    """Översikt per kategori."""
    print("\n📊 SAMMANSTÄLLNING PER KATEGORI")
    sep()
    rows = conn.execute("""
        SELECT c.typ, c.namn, COUNT(*) as antal, SUM(t.belopp) as totalt
        FROM transactions t
        JOIN tx_categorized tc ON t.tx_id = tc.tx_id
        JOIN categories c ON tc.cat_id = c.cat_id
        GROUP BY c.cat_id
        ORDER BY c.typ, SUM(t.belopp)
    """).fetchall()

    current_typ = None
    for typ, namn, antal, totalt in rows:
        if typ != current_typ:
            print(f"\n  [{typ.upper()}]")
            current_typ = typ
        print(f"  {namn:<30} {antal:>4} tx   {kr(totalt):>14}")


def rapport_transfers(conn):
    """Visa alla interna transfereringar."""
    print("\n🔄 INTERNA TRANSFERERINGAR")
    sep()
    rows = conn.execute("""
        SELECT t.datum, t.text, t.belopp, a.namn
        FROM transactions t
        JOIN accounts a ON t.account_id = a.account_id
        JOIN tx_categorized tc ON t.tx_id = tc.tx_id
        JOIN categories c ON tc.cat_id = c.cat_id
        WHERE c.typ = 'transfer'
        ORDER BY t.datum DESC
    """).fetchall()

    for datum, text, belopp, konto in rows:
        print(f"  {datum}  {text:<35} {kr(belopp):>12}  [{konto}]")


KOMMANDON = {
    "media": rapport_media,
    "el": rapport_el,
    "okategoriserade": rapport_okategoriserade,
    "transfers": rapport_transfers,
    "sammanstallning": rapport_sammanstallning,
}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    kommando = sys.argv[1].lower()
    conn = get_conn()

    if kommando == "manad":
        manad = sys.argv[2] if len(sys.argv) > 2 else "2026-01"
        rapport_manad(conn, manad)
    elif kommando in KOMMANDON:
        KOMMANDON[kommando](conn)
    else:
        print(f"Okänt kommando: {kommando}")
        print(f"Tillgängliga: {', '.join(KOMMANDON.keys())}, manad YYYY-MM")

    print()
    conn.close()


if __name__ == "__main__":
    main()
