"""
kategorier.py — Regelbaserad kategorisering av transaktioner
Läser regler.json och tillämpar dem på okategoriserade transaktioner i DB.
Användning:
    python kategorier.py              # kör alla okategoriserade
    python kategorier.py --alla       # omkategorisera allt (ej manuella)
    python kategorier.py --visa       # visa regler utan att skriva
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

DB_PATH  = Path(__file__).parent / "familjekonomi.db"
REG_PATH = Path(__file__).parent / "regler.json"


def load_regler() -> list[dict]:
    with open(REG_PATH, encoding="utf-8") as f:
        return [r for r in json.load(f) if "monster" in r]


def kategorisera(con: sqlite3.Connection, regler: list[dict],
                 bara_okategoriserade: bool = True) -> dict:
    if bara_okategoriserade:
        rows = con.execute("""
            SELECT t.tx_id, t.text FROM transactions t
            LEFT JOIN tx_categorized c ON t.tx_id = c.tx_id
            WHERE c.tx_id IS NULL
        """).fetchall()
    else:
        # Hoppa över manuella
        rows = con.execute("""
            SELECT t.tx_id, t.text FROM transactions t
            LEFT JOIN tx_categorized c ON t.tx_id = c.tx_id
            WHERE c.kalla != 'manual' OR c.tx_id IS NULL
        """).fetchall()

    stats = {"matchade": 0, "omatchade": 0, "totalt": len(rows)}

    for tx_id, text in rows:
        matchad_cat = None
        for regel in regler:
            monster = regel["monster"]
            anvand_regex = regel.get("regex", False)
            if anvand_regex:
                if re.search(monster, text, re.IGNORECASE):
                    matchad_cat = regel["kategori"]
                    break
            else:
                if monster.lower() in text.lower():
                    matchad_cat = regel["kategori"]
                    break

        if matchad_cat is None:
            matchad_cat = "okand"
            stats["omatchade"] += 1
        else:
            stats["matchade"] += 1

        con.execute("""
            INSERT OR REPLACE INTO tx_categorized (tx_id, cat_id, confidence, kalla)
            VALUES (?, ?, ?, 'rule')
        """, (tx_id, matchad_cat, 1.0 if matchad_cat != "okand" else 0.0))

    con.commit()
    return stats


def main():
    parser = argparse.ArgumentParser(description="Kategorisera transaktioner")
    parser.add_argument("--alla", action="store_true",
                        help="Omkategorisera alla (ej manuella)")
    parser.add_argument("--visa", action="store_true",
                        help="Visa regler utan att skriva till DB")
    args = parser.parse_args()

    regler = load_regler()

    if args.visa:
        print(f"Laddade {len(regler)} regler:")
        for r in regler:
            print(f"  '{r['monster']}' → {r['kategori']} ({r['typ']})")
        return

    con = sqlite3.connect(DB_PATH)
    stats = kategorisera(con, regler, bara_okategoriserade=not args.alla)
    con.close()

    print(f"Kategorisering klar:")
    print(f"  Totalt behandlade: {stats['totalt']}")
    print(f"  Matchade:          {stats['matchade']}")
    print(f"  Okategoriserade:   {stats['omatchade']}")


if __name__ == "__main__":
    main()
