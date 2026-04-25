"""
migrate_articles.py
Engångsskript: kopierar seen_articles från SQLite → Odoo (clio.job.article).

Kör EFTER att clio_job-modulen uppgraderats till v3.0.0 (tabellen finns i Odoo).
Kör EN gång — dubbelposter skippas automatiskt (UNIQUE-constraint i Odoo).

Användning:
    python migrate_articles.py            # Migrera
    python migrate_articles.py --dry-run  # Visa vad som skulle migreras
    python migrate_articles.py --stats    # Visa nuvarande antal i SQLite och Odoo
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_BASE_DIR = Path(__file__).parent
_ROOT_DIR = _BASE_DIR.parent

for _p in [str(_BASE_DIR), str(_ROOT_DIR), str(_ROOT_DIR / "clio-core")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT_DIR / ".env")
    load_dotenv(_BASE_DIR / ".env")
except ImportError:
    pass

_DB_PATH = _BASE_DIR / "state.db"


def _read_sqlite() -> list[dict]:
    if not _DB_PATH.exists():
        print(f"[VARNING] {_DB_PATH} finns inte — ingenting att migrera.")
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT article_id, url, title, source, first_seen, match_score "
        "FROM seen_articles ORDER BY first_seen"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _odoo_connect():
    from clio_odoo import connect
    return connect()


def migrate(dry_run: bool = False) -> None:
    rows = _read_sqlite()
    if not rows:
        print("Inga rader att migrera.")
        return

    print(f"SQLite: {len(rows)} artiklar hittade.")

    if dry_run:
        print("[DRY-RUN] Inga ändringar görs. Första 5 rader:")
        for r in rows[:5]:
            print(f"  {r['first_seen'][:10]}  {r['source']:<20}  {r['title'][:60]}")
        return

    try:
        env = _odoo_connect()
    except Exception as e:
        print(f"[FEL] Kunde inte ansluta till Odoo: {e}", file=sys.stderr)
        sys.exit(1)

    Article = env["clio.job.article"]

    # Hämta redan befintliga IDs i Odoo för att skippa dubblar
    existing = {r["article_id"] for r in Article.search_read([], ["article_id"])}
    print(f"Odoo: {len(existing)} artiklar redan inlagda.")

    to_migrate = [r for r in rows if r["article_id"] not in existing]
    print(f"Att migrera: {len(to_migrate)} rader.")

    if not to_migrate:
        print("Inget nytt att migrera — klart!")
        return

    ok = 0
    fail = 0
    for r in to_migrate:
        try:
            Article.create({
                "article_id":  r["article_id"],
                "url":         r.get("url") or "",
                "title":       (r.get("title") or "")[:500],
                "source":      r.get("source") or "",
                "first_seen":  (r.get("first_seen") or "")[:19].replace("T", " "),
                "match_score": int(r.get("match_score") or -1),
                "is_matched":  int(r.get("match_score") or -1) >= 50,
            })
            ok += 1
        except Exception as e:
            print(f"  [FEL] {r['article_id'][:20]}: {e}")
            fail += 1

    print(f"\nKlart! {ok} migrerade, {fail} fel.")
    if fail == 0:
        print("\nDu kan nu säkert ta bort seen_articles ur SQLite om du vill,")
        print(f"eller behålla {_DB_PATH} som backup.")


def stats() -> None:
    rows = _read_sqlite()
    print(f"SQLite (seen_articles): {len(rows)} rader")
    if not rows:
        return
    sources = {}
    for r in rows:
        sources[r["source"]] = sources.get(r["source"], 0) + 1
    for s, n in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  {s:<25} {n:>6}")

    try:
        env = _odoo_connect()
        count = env["clio.job.article"].search_read([], ["id"])
        print(f"\nOdoo (clio.job.article): {len(count)} poster")
    except Exception as e:
        print(f"\nOdoo: kunde inte ansluta — {e}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Migrera seen_articles → Odoo")
    p.add_argument("--dry-run", action="store_true", help="Visa utan att ändra")
    p.add_argument("--stats", action="store_true", help="Visa statistik och avsluta")
    args = p.parse_args()

    if args.stats:
        stats()
    else:
        migrate(dry_run=args.dry_run)
