"""
Synkar PersonIOLRoles fran SSFTA -> ssf.iol.role i Odoo (ssf).
Anvander direkt psycopg2 for bulk-insert (193k poster via ORM ar for langsamt).

Korning:
    python3 sync_iol_roles.py
    python3 sync_iol_roles.py --db ssf_t2
    python3 sync_iol_roles.py --dry-run
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

import psycopg2
import pymssql
from dotenv import load_dotenv

PG_HOST = '172.18.0.3'
PG_PORT = 5432
PG_USER = 'odoo'
PG_PASS = 'odoo'
BATCH   = 2000


def _get_ssfta_conn():
    load_dotenv(Path(__file__).parent.parent / '.env.ssfta', override=False)
    return pymssql.connect(
        server=os.environ.get('SSFTA_MSSQL_HOST', 'localhost'),
        port=int(os.environ.get('SSFTA_MSSQL_PORT', 1433)),
        user=os.environ.get('SSFTA_MSSQL_USER', 'sa'),
        password=os.environ.get('SSFTA_MSSQL_PASSWORD', ''),
        database=os.environ.get('SSFTA_MSSQL_DB', 'SSFTADB'),
        charset='UTF-8',
    )


def main():
    parser = argparse.ArgumentParser(description='Synkar IOL-roller SSFTA -> Odoo')
    parser.add_argument('--db', default='ssf')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    # 1. Hamta fran SSFTA
    print('Hamtar PersonIOLRoles fran SSFTA...', flush=True)
    ms = _get_ssfta_conn()
    cur = ms.cursor(as_dict=True)
    cur.execute("""
        SELECT
            iol.role,
            p.rfid  AS person_rfid,
            o.rfid  AS org_rfid
        FROM PersonIOLRoles iol
        JOIN Persons       p ON iol.person       = p.ID
        JOIN Organizations o ON iol.organization = o.ID
        WHERE p.rfid IS NOT NULL
          AND o.rfid IS NOT NULL
    """)
    rows_raw = cur.fetchall()
    ms.close()
    print(f'  {len(rows_raw):,} rader med matchningsbara rfid-par.', flush=True)

    # 2. Bygg rfid -> partner_id-karta fran Postgres
    print('Bygger partner-kartor...', flush=True)
    pg = psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=args.db,
                          user=PG_USER, password=PG_PASS)
    pgcur = pg.cursor()
    pgcur.execute("SELECT ref, id FROM res_partner WHERE ref LIKE 'ssfta-%'")
    ref_to_id = {row[0]: row[1] for row in pgcur.fetchall()}
    print(f'  {len(ref_to_id):,} ssfta-partners i Odoo.', flush=True)

    # 3. Matcha
    print('Matchar poster...', flush=True)
    to_insert = []
    skipped   = 0
    for r in rows_raw:
        p_id = ref_to_id.get(f"ssfta-person-{r['person_rfid']}")
        o_id = ref_to_id.get(f"ssfta-{r['org_rfid']}")
        if not p_id or not o_id:
            skipped += 1
            continue
        to_insert.append((p_id, o_id, r['role'] or ''))

    print(f'  {len(to_insert):,} att skriva, {skipped:,} hoppade.', flush=True)

    if args.dry_run:
        print('[DRY-RUN] Inga andringar sparade.')
        pg.close()
        return

    # 4. Truncate + bulk insert (idempotent)
    print('Skriver till ssf_iol_role...', flush=True)
    pgcur.execute('TRUNCATE TABLE ssf_iol_role RESTART IDENTITY CASCADE')

    inserted = 0
    for i in range(0, len(to_insert), BATCH):
        batch = to_insert[i:i + BATCH]
        pgcur.executemany(
            'INSERT INTO ssf_iol_role (person_id, organization_id, role_name) VALUES (%s, %s, %s)',
            batch,
        )
        inserted += len(batch)
        if inserted % 20000 == 0 or inserted == len(to_insert):
            print(f'  {inserted:,}/{len(to_insert):,}...', flush=True)

    pg.commit()
    pg.close()
    print(f'Klar. {inserted:,} IOL-roller inlagda.', flush=True)


if __name__ == '__main__':
    main()
