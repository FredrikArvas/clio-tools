"""
sync_fis_from_results.py -- Bootstrappar ssf.fis.competitor från befintliga ssf.result-poster.

Fas 1 (detta skript): ingen FIS API-åtkomst krävs.
  - Tävlingsdata hämtas från Odoo (ssf.result, synkad från SSFTA)
  - Person-koppling hämtas direkt från SSFTA via JOIN Results -> Persons (rfid)
  - FIS-koden är join-nyckeln när FIS API:et blir tillgängligt i fas 2

Logik:
  1. SSFTA: hämta fis_code -> rfid-mappning (Results JOIN Persons)
  2. Odoo: rfid -> res.partner.id
  3. Odoo: hämta ssf.result -> discipline_id via result_list -> ccd
  4. Gruppera per (fis_code, discipline_id), ta senaste fis_points
  5. Upsert ssf.fis.competitor med person_id satt där matchning finns

Körning:
    python3 sync_fis_from_results.py --db ssf [--dry-run] [--nation SWE]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pymssql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

BATCH = 500


# ── SSFTA-anslutning ──────────────────────────────────────────────────────────

def _load_ssfta_env() -> dict:
    env_path = Path(__file__).parent.parent / ".env.ssfta"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    return {
        "host": os.environ.get("SSFTA_MSSQL_HOST", "localhost"),
        "port": int(os.environ.get("SSFTA_MSSQL_PORT", "1433")),
        "db": os.environ.get("SSFTA_MSSQL_DB", "SSFTADB"),
        "user": os.environ.get("SSFTA_MSSQL_USER", "sa"),
        "password": os.environ.get("SSFTA_MSSQL_PASSWORD", ""),
    }


def _get_conn():
    cfg = _load_ssfta_env()
    return pymssql.connect(
        server=cfg["host"], port=cfg["port"],
        user=cfg["user"], password=cfg["password"],
        database=cfg["db"], charset="UTF-8",
    )


# ── Odoo-hjälpare ─────────────────────────────────────────────────────────────

def _m2o_id(val):
    """Normalisera Many2one-värde från search_read ([id, name] eller False) till int eller False."""
    if isinstance(val, (list, tuple)):
        return val[0]
    return val or False


def _upsert(Model, rows: list[dict], key1: str, key2: str, dry_run: bool) -> tuple[int, int]:
    """Upsert med sammansatt nyckel (key1, key2). key2 kan vara Many2one (returneras som [id,name])."""
    created = updated = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]

        key1_vals = list({r[key1] for r in batch})
        existing_recs = Model.search_read([[key1, "in", key1_vals]], [key1, key2, "id"])
        existing = {(r[key1], _m2o_id(r[key2])): r["id"] for r in existing_recs}

        to_create = [r for r in batch if (r[key1], r.get(key2)) not in existing]
        to_update = [(existing[(r[key1], r.get(key2))], r) for r in batch if (r[key1], r.get(key2)) in existing]

        if to_create and not dry_run:
            Model.create(to_create)
        created += len(to_create)

        for odoo_id, row in to_update:
            if not dry_run:
                Model.browse(odoo_id).write(row)
        updated += len(to_update)

    return created, updated


# ── Person-matchning via SSFTA ────────────────────────────────────────────────

def build_fis_person_map(env, nation: str) -> dict[str, int]:
    """Returnerar {fis_code_str: res.partner.id} via SSFTA Results JOIN Persons."""
    print(f"  SSFTA: hämtar fis_code -> rfid för nation={nation} ...")
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT DISTINCT CAST(r.FisCode AS VARCHAR(20)) AS FisCode, p.rfid
        FROM Results r
        JOIN Persons p ON p.ID = r.Person
        WHERE r.FisCode IS NOT NULL
          AND r.FisCode != 0
          AND r.Nation = %s
          AND r.Person IS NOT NULL
    """, (nation,))
    rows = cur.fetchall()
    conn.close()
    print(f"  SSFTA: {len(rows)} unika (fis_code, rfid)-par hittades")

    if not rows:
        return {}

    # Bygg rfid -> fis_code och slå upp res.partner
    rfid_to_fis: dict[str, str] = {}
    for r in rows:
        rfid = str(r["rfid"]).upper() if r["rfid"] else None
        if rfid:
            rfid_to_fis[rfid] = r["FisCode"]

    refs = [f"ssfta-person-{rfid}" for rfid in rfid_to_fis]
    print(f"  Odoo: slår upp {len(refs)} res.partner via ref ...")

    fis_to_partner: dict[str, int] = {}
    for i in range(0, len(refs), BATCH):
        batch_refs = refs[i:i + BATCH]
        partners = env["res.partner"].search_read(
            [("ref", "in", batch_refs)], ["ref", "id"]
        )
        for p in partners:
            rfid = p["ref"].replace("ssfta-person-", "")
            fis_code = rfid_to_fis.get(rfid)
            if fis_code:
                fis_to_partner[fis_code] = p["id"]

    print(f"  Person-matchning: {len(fis_to_partner)} av {len(rows)} FIS-koder länkade till res.partner")
    return fis_to_partner


# ── Huvudfunktion ─────────────────────────────────────────────────────────────

def build_fis_competitors(env, nation: str, dry_run: bool):
    # Fas 1: person-matchning via SSFTA
    fis_to_partner = build_fis_person_map(env, nation)

    # Fas 2: hämta results från Odoo
    print(f"  Hämtar ssf.result för nation={nation} med fis_code ...")
    results = env["ssf.result"].search_read(
        [("fis_code", "!=", 0), ("nation", "=", nation)],
        ["fis_code", "fis_points", "nation", "result_list_id"],
        limit=0,
    )
    print(f"  Hittade {len(results)} result-rader")
    if not results:
        return

    # Bygg result_list_id -> discipline_id via ccd
    rl_ids = list({r["result_list_id"][0] for r in results if r["result_list_id"]})
    print(f"  Slår upp {len(rl_ids)} result-listor ...")
    rl_recs = env["ssf.result.list"].search_read([("id", "in", rl_ids)], ["id", "ccd_id"])
    rl_to_ccd = {r["id"]: (_m2o_id(r["ccd_id"])) for r in rl_recs}

    ccd_ids = list({ccd for ccd in rl_to_ccd.values() if ccd})
    print(f"  Slår upp {len(ccd_ids)} CCD-poster ...")
    ccd_recs = env["ssf.comp.ccd"].search_read(
        [("id", "in", ccd_ids)], ["id", "discipline_id", "competition_id"]
    )
    ccd_to_disc = {r["id"]: _m2o_id(r["discipline_id"]) for r in ccd_recs}
    ccd_to_comp = {r["id"]: _m2o_id(r["competition_id"]) for r in ccd_recs}

    comp_ids = list({c for c in ccd_to_comp.values() if c})
    print(f"  Slår upp {len(comp_ids)} tävlingsdatum ...")
    comp_recs = env["ssf.competition"].search_read([("id", "in", comp_ids)], ["id", "date"])
    comp_to_date = {r["id"]: r["date"] for r in comp_recs}

    rl_to_disc = {}
    rl_to_date = {}
    for rl_id, ccd_id in rl_to_ccd.items():
        if not ccd_id:
            continue
        rl_to_disc[rl_id] = ccd_to_disc.get(ccd_id)
        comp_id = ccd_to_comp.get(ccd_id)
        rl_to_date[rl_id] = comp_to_date.get(comp_id) if comp_id else None

    # Gruppera per (fis_code, discipline_id)
    best: dict[tuple, dict] = {}
    for r in results:
        fis_code = str(r["fis_code"]) if r["fis_code"] else None
        if not fis_code:
            continue
        rl_id = _m2o_id(r["result_list_id"])
        disc_id = rl_to_disc.get(rl_id) if rl_id else None
        date_str = rl_to_date.get(rl_id) if rl_id else None
        try:
            pts = float(r["fis_points"]) if r["fis_points"] else 0.0
        except (ValueError, TypeError):
            pts = 0.0

        key = (fis_code, disc_id)
        if key not in best or (date_str and date_str > (best[key]["date"] or "")):
            best[key] = {
                "fis_code": fis_code,
                "discipline_id": disc_id,
                "nation": r["nation"] or nation,
                "fis_points": pts,
                "date": date_str,
            }

    print(f"  Unika (fis_code, disciplin)-kombinationer: {len(best)}")

    rows = []
    for data in best.values():
        row = {
            "fis_code": data["fis_code"],
            "nation": data["nation"],
            "fis_points": data["fis_points"],
            "source": "ssfta_derived",
        }
        partner_id = fis_to_partner.get(data["fis_code"])
        if partner_id:
            row["person_id"] = partner_id
        if data.get("discipline_id"):
            row["discipline_id"] = data["discipline_id"]
        if data.get("date"):
            row["list_date"] = data["date"]
        rows.append(row)

    linked = sum(1 for r in rows if "person_id" in r)
    print(f"  Av {len(rows)} poster: {linked} länkade till res.partner, {len(rows)-linked} utan koppling")
    print(f"  Upsert {len(rows)} poster till ssf.fis.competitor ...")
    c, u = _upsert(env["ssf.fis.competitor"], rows, "fis_code", "discipline_id", dry_run)
    print(f"  Resultat: {c} skapade, {u} uppdaterade")


def main():
    parser = argparse.ArgumentParser(description="Bootstrap ssf.fis.competitor fran ssf.result")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None)
    parser.add_argument("--nation", default="SWE", help="Filtrera pa nation (default: SWE)")
    args = parser.parse_args()

    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"{mode}Bootstrap FIS-akare fran ssf.result -> ssf.fis.competitor ({env.db})")
    print(f"  Nation: {args.nation}")

    build_fis_competitors(env, args.nation, args.dry_run)
    print("Klar.")


if __name__ == "__main__":
    main()
