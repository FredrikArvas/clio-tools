"""
sync_person_sectors.py — Synkar PersonSector (person↔gren) till ssf_person_sector.

340 000+ rader — ORM är för långsamt. Direkt batch-INSERT via psycopg2.

Env-variabler (.env.ssfta + .env):
  SSFTA_MSSQL_*   → SQL Server (SSFTA)
  ODOO_PG_DSN     → psycopg2-DSN till Odoo-databasen
                    Exempel: "dbname=ssf host=localhost user=odoo password=SECRET"
  ODOO_DB         → används om ODOO_PG_DSN saknas (dbname, övriga defaultar)

Körning:
    python3 sync_person_sectors.py             # live
    python3 sync_person_sectors.py --dry-run
    python3 sync_person_sectors.py --db ssf_t2
"""

from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import pymssql
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

BATCH = 2000


# ── Env-laddning ───────────────────────────────────────────────────────────────

def _load_envs():
    base = Path(__file__).parent.parent
    for f in [base / ".env.ssfta", base / ".env"]:
        if f.exists():
            load_dotenv(f, override=False)


def _ssfta_conn():
    return pymssql.connect(
        server=os.environ.get("SSFTA_MSSQL_HOST", "localhost"),
        port=int(os.environ.get("SSFTA_MSSQL_PORT", "1433")),
        user=os.environ.get("SSFTA_MSSQL_USER", "sa"),
        password=os.environ.get("SSFTA_MSSQL_PASSWORD", ""),
        database=os.environ.get("SSFTA_MSSQL_DB", "SSFTADB"),
        charset="UTF-8",
    )


def _pg_conn(db: str | None = None):
    dsn = os.environ.get("ODOO_PG_DSN")
    if dsn:
        return psycopg2.connect(dsn)
    dbname = db or os.environ.get("ODOO_DB", "ssf")
    return psycopg2.connect(
        dbname=dbname,
        host=os.environ.get("ODOO_PG_HOST", "localhost"),
        user=os.environ.get("ODOO_PG_USER", "odoo"),
        password=os.environ.get("ODOO_PG_PASSWORD", ""),
    )


# ── SSFTA-hämtning ─────────────────────────────────────────────────────────────

def fetch_person_sectors() -> list[tuple[str, int]]:
    """Returnerar lista av (rfid, sector_ssfta_id)."""
    conn = _ssfta_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.rfid, ps.Sector
        FROM PersonSector ps
        JOIN Persons p ON p.ID = ps.Person
        WHERE p.rfid IS NOT NULL AND p.rfid != ''
    """)
    rows = [(rfid.upper(), sector) for rfid, sector in cur.fetchall()]
    conn.close()
    print(f"  {len(rows)} PersonSector-rader från SSFTA")
    return rows


# ── Odoo-uppslagstabeller ──────────────────────────────────────────────────────

def _build_person_map(env) -> dict[str, int]:
    """rfid.upper() → res.partner.id (ssfta-person-*)"""
    prefix = "ssfta-person-"
    partners = env["res.partner"].search_read(
        [("ref", "like", prefix), ("active", "in", [True, False])],
        ["id", "ref"],
    )
    m = {}
    for p in partners:
        ref = (p.get("ref") or "")
        if ref.startswith(prefix):
            rfid = ref[len(prefix):].upper()
            m[rfid] = p["id"]
    print(f"  {len(m)} person-partners i Odoo")
    return m


def _build_sector_map(env) -> dict[int, int]:
    """ssfta_id → ssf.sector.id"""
    rows = env["ssf.sector"].search_read([], ["id", "ssfta_id"])
    m = {r["ssfta_id"]: r["id"] for r in rows if r["ssfta_id"]}
    print(f"  {len(m)} sektorer i Odoo")
    return m


# ── Batch-insert ───────────────────────────────────────────────────────────────

def insert_batches(pg, pairs: list[tuple[int, int]], dry_run: bool) -> tuple[int, int]:
    """INSERT INTO ssf_person_sector ON CONFLICT DO NOTHING. Returnerar (insatt, konflikt)."""
    if dry_run:
        print(f"  [DRY] Skulle infoga {len(pairs)} rader (ON CONFLICT DO NOTHING)")
        return len(pairs), 0

    cur = pg.cursor()
    inserted = 0
    conflicts = 0
    for start in range(0, len(pairs), BATCH):
        batch = pairs[start:start + BATCH]
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO ssf_person_sector (person_id, sector_id) VALUES %s ON CONFLICT DO NOTHING",
            batch,
        )
        inserted += cur.rowcount if cur.rowcount >= 0 else len(batch)
        conflicts += len(batch) - (cur.rowcount if cur.rowcount >= 0 else len(batch))
    pg.commit()
    cur.close()
    return inserted, conflicts


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    _load_envs()

    parser = argparse.ArgumentParser(description="Synkar PersonSector → ssf_person_sector")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None, help="Odoo-databasnamn (override ODOO_DB)")
    args = parser.parse_args()

    print("Hämtar PersonSector från SSFTA...")
    raw = fetch_person_sectors()

    print("Ansluter till Odoo (ORM)...")
    env = connect(db=args.db)

    print("Bygger uppslagstabeller...")
    person_map = _build_person_map(env)
    sector_map = _build_sector_map(env)

    print("Matchar rader...")
    pairs: list[tuple[int, int]] = []
    missing_person = missing_sector = 0
    for rfid, sector_ssfta_id in raw:
        pid = person_map.get(rfid)
        sid = sector_map.get(sector_ssfta_id)
        if not pid:
            missing_person += 1
            continue
        if not sid:
            missing_sector += 1
            continue
        pairs.append((pid, sid))
    print(f"  {len(pairs)} par att infoga | saknar person: {missing_person} | saknar sektor: {missing_sector}")

    print("Ansluter till Odoo-PostgreSQL (direkt)...")
    pg = _pg_conn(db=args.db or os.environ.get("ODOO_DB", "ssf"))

    print("Infogar batchar...")
    inserted, conflicts = insert_batches(pg, pairs, args.dry_run)
    pg.close()

    print(f"\nKlar: {inserted} insatta, {conflicts} konflikter (redan finns)")
    if args.dry_run:
        print("  (--dry-run, ingen data skrevs)")


if __name__ == "__main__":
    main()
