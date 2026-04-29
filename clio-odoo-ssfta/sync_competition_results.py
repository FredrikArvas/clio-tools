"""
sync_competition_results.py -- Synkar ResultLists, Results och Entries per tävling.

Triggas on-demand per tävling (inte dagligt).

Körning:
    python3 sync_competition_results.py --competition-id 60490
    python3 sync_competition_results.py --event-id 47709    # alla tavlingar under evenemang
    python3 sync_competition_results.py --competition-id 60490 --dry-run
    python3 sync_competition_results.py --competition-id 60490 --db ssf_t2
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

BATCH = 1000


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


def _upsert(Model, rows: list[dict], key: str = "ssfta_id", dry_run: bool = False) -> tuple[int, int]:
    created = updated = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        ids = [r[key] for r in batch]
        existing = {r[key]: r["id"] for r in Model.search_read([[key, "in", ids]], [key, "id"])}
        to_create = [r for r in batch if r[key] not in existing]
        to_update = [(existing[r[key]], r) for r in batch if r[key] in existing]
        if to_create and not dry_run:
            Model.create(to_create)
        created += len(to_create)
        for odoo_id, row in to_update:
            if not dry_run:
                Model.browse(odoo_id).write(row)
        updated += len(to_update)
    return created, updated


def _get_competition_ssfta_ids(env, competition_ids: list[int] = None, event_ids: list[int] = None) -> list[int]:
    """Resolve Odoo competition records and return their ssfta_ids."""
    domain = []
    if competition_ids:
        domain = [("ssfta_id", "in", competition_ids)]
    elif event_ids:
        domain = [("event_id.ssfta_id", "in", event_ids)]
    recs = env["ssf.competition"].search_read(domain, ["ssfta_id", "id"])
    return [(r["ssfta_id"], r["id"]) for r in recs]


def sync_result_lists(env, comp_ssfta_id: int, ccd_map: dict, dry_run: bool) -> dict:
    """Returns resultlist ssfta_id -> odoo_id map for this competition."""
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT rl.ID, rl.CompetitionClassDiscipline, rl.Final,
               rl.Class, rl.Discipline,
               rl.ParticipantsRegistered, rl.ParticipantsStarted, rl.ParticipantsCompleted
        FROM ResultLists rl
        JOIN CompetitionClassDiscipline ccd ON ccd.ID = rl.CompetitionClassDiscipline
        WHERE ccd.Competition = %d
    """ % comp_ssfta_id)
    rows_raw = cur.fetchall()
    conn.close()

    rows = []
    for r in rows_raw:
        ccd_id = ccd_map.get(r["CompetitionClassDiscipline"])
        if not ccd_id:
            continue
        rows.append({
            "ssfta_id": r["ID"],
            "ccd_id": ccd_id,
            "final": r["Final"] or 0,
            "class_name": r["Class"] or "",
            "discipline_name": r["Discipline"] or "",
            "participants_registered": r["ParticipantsRegistered"] or 0,
            "participants_started": r["ParticipantsStarted"] or 0,
            "participants_completed": r["ParticipantsCompleted"] or 0,
        })

    c, u = _upsert(env["ssf.result.list"], rows, dry_run=dry_run)
    print(f"    ResultLists: {c} skapade, {u} uppdaterade")

    rl_map = {r["ssfta_id"]: r["id"] for r in env["ssf.result.list"].search_read(
        [("ssfta_id", "in", [r["ssfta_id"] for r in rows])], ["ssfta_id", "id"]
    )}
    return rl_map


def sync_results(env, comp_ssfta_id: int, rl_map: dict, dry_run: bool):
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT r.ID, r.ResultList, r.Person, r.Rank, r.Bib, r.FisCode,
               r.Firstname, r.Lastname, r.BirthYear, r.Nation, r.Gender,
               r.Club, r.ClubID, r.Status, r.Time, r.Difference,
               r.Points, r.FisPoints, r.DisplayOrder
        FROM Results r
        JOIN ResultLists rl ON rl.ID = r.ResultList
        JOIN CompetitionClassDiscipline ccd ON ccd.ID = rl.CompetitionClassDiscipline
        WHERE ccd.Competition = %d
    """ % comp_ssfta_id)
    rows_raw = cur.fetchall()
    conn.close()

    # Person map: ssfta person ID -> res.partner id
    person_ssfta_ids = list({r["Person"] for r in rows_raw if r["Person"]})
    person_map = {}
    if person_ssfta_ids:
        refs = [f"ssfta-person-{pid}" for pid in person_ssfta_ids]
        partners = env["res.partner"].search_read([("ref", "in", refs)], ["ref", "id"])
        for p in partners:
            ssfta_id = int(p["ref"].split("-")[-1])
            person_map[ssfta_id] = p["id"]

    # Club map: ssfta org ID -> res.partner id
    club_ssfta_ids = list({r["ClubID"] for r in rows_raw if r["ClubID"]})
    club_odoo_map = {}
    if club_ssfta_ids:
        conn2 = _get_conn()
        cur2 = conn2.cursor(as_dict=True)
        placeholders = ",".join(str(i) for i in club_ssfta_ids)
        cur2.execute(f"SELECT ID, rfid FROM Organizations WHERE ID IN ({placeholders})")
        for row in cur2.fetchall():
            if row["rfid"]:
                ref = f"ssfta-{row['rfid']}"
                partners = env["res.partner"].search_read([("ref", "=", ref)], ["id"])
                if partners:
                    club_odoo_map[row["ID"]] = partners[0]["id"]
        conn2.close()

    rows = []
    for r in rows_raw:
        rl_id = rl_map.get(r["ResultList"])
        if not rl_id:
            continue
        rows.append({
            "ssfta_id": r["ID"],
            "result_list_id": rl_id,
            "person_id": person_map.get(r["Person"]) or False,
            "rank": r["Rank"] or 0,
            "bib": r["Bib"] or 0,
            "fis_code": r["FisCode"] or 0,
            "firstname": r["Firstname"] or "",
            "lastname": r["Lastname"] or "",
            "birth_year": r["BirthYear"] or 0,
            "nation": r["Nation"] or "",
            "gender": r["Gender"] or "",
            "club": r["Club"] or "",
            "club_id": club_odoo_map.get(r["ClubID"]) or False,
            "status": r["Status"] or "",
            "time": r["Time"] or "",
            "difference": r["Difference"] or "",
            "points": r["Points"] or "",
            "fis_points": r["FisPoints"] or "",
            "display_order": r["DisplayOrder"] or 0,
        })

    c, u = _upsert(env["ssf.result"], rows, dry_run=dry_run)
    print(f"    Results:     {c} skapade, {u} uppdaterade  (totalt {len(rows)})")


def sync_entries(env, comp_ssfta_id: int, ccd_map: dict, dry_run: bool):
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("""
        SELECT e.ID, e.CompetitionClassDiscipline, e.Person, e.Organization,
               e.EntryDate, e.EntryFee, e.PaidFee, e.PaymentStatus,
               e.Unregistered, e.UnregDate, e.Note
        FROM Entries e
        JOIN CompetitionClassDiscipline ccd ON ccd.ID = e.CompetitionClassDiscipline
        WHERE ccd.Competition = %d
    """ % comp_ssfta_id)
    rows_raw = cur.fetchall()
    conn.close()

    person_ssfta_ids = list({r["Person"] for r in rows_raw if r["Person"]})
    person_map = {}
    if person_ssfta_ids:
        refs = [f"ssfta-person-{pid}" for pid in person_ssfta_ids]
        partners = env["res.partner"].search_read([("ref", "in", refs)], ["ref", "id"])
        for p in partners:
            pid = int(p["ref"].split("-")[-1])
            person_map[pid] = p["id"]

    org_ssfta_ids = list({r["Organization"] for r in rows_raw if r["Organization"]})
    org_map = {}
    if org_ssfta_ids:
        conn2 = _get_conn()
        cur2 = conn2.cursor(as_dict=True)
        placeholders = ",".join(str(i) for i in org_ssfta_ids)
        cur2.execute(f"SELECT ID, rfid FROM Organizations WHERE ID IN ({placeholders})")
        for row in cur2.fetchall():
            if row["rfid"]:
                ref = f"ssfta-{row['rfid']}"
                partners = env["res.partner"].search_read([("ref", "=", ref)], ["id"])
                if partners:
                    org_map[row["ID"]] = partners[0]["id"]
        conn2.close()

    rows = []
    for r in rows_raw:
        ccd_id = ccd_map.get(r["CompetitionClassDiscipline"])
        if not ccd_id:
            continue
        rows.append({
            "ssfta_id": r["ID"],
            "ccd_id": ccd_id,
            "person_id": person_map.get(r["Person"]) or False,
            "organization_id": org_map.get(r["Organization"]) or False,
            "entry_date": r["EntryDate"].strftime("%Y-%m-%d %H:%M:%S") if r["EntryDate"] else False,
            "entry_fee": r["EntryFee"] or 0,
            "paid_fee": r["PaidFee"] or 0,
            "payment_status": r["PaymentStatus"] or 0,
            "unregistered": bool(r["Unregistered"]),
            "unreg_date": r["UnregDate"].strftime("%Y-%m-%d %H:%M:%S") if r["UnregDate"] else False,
            "note": r["Note"] or "",
        })

    c, u = _upsert(env["ssf.entry"], rows, dry_run=dry_run)
    print(f"    Entries:     {c} skapade, {u} uppdaterade  (totalt {len(rows)})")


def sync_one_competition(env, ssfta_id: int, odoo_id: int, dry_run: bool):
    print(f"  Competition SSFTA-ID={ssfta_id}")
    ccd_records = env["ssf.comp.ccd"].search_read(
        [("competition_id", "=", odoo_id)], ["ssfta_id", "id"]
    )
    ccd_map = {r["ssfta_id"]: r["id"] for r in ccd_records}
    if not ccd_map:
        print(f"    Inga CCDs hittade -- kör sync_competition_meta.py först")
        return
    rl_map = sync_result_lists(env, ssfta_id, ccd_map, dry_run)
    sync_results(env, ssfta_id, rl_map, dry_run)
    sync_entries(env, ssfta_id, ccd_map, dry_run)


def main():
    parser = argparse.ArgumentParser(description="Synkar resultat/anmalningar per tavling")
    parser.add_argument("--competition-id", type=int, help="SSFTA Competition.ID")
    parser.add_argument("--event-id", type=int, help="SSFTA Event.ID (synkar alla tavlingar)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    if not args.competition_id and not args.event_id:
        print("Ange --competition-id eller --event-id")
        sys.exit(1)

    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    dr = args.dry_run
    mode = "[DRY-RUN] " if dr else ""

    competition_ids = [args.competition_id] if args.competition_id else None
    event_ids = [args.event_id] if args.event_id else None
    pairs = _get_competition_ssfta_ids(env, competition_ids, event_ids)

    if not pairs:
        print("Inga matching tavlingar i Odoo. Kör sync_competition_meta.py först.")
        sys.exit(1)

    print(f"{mode}Synkar resultat för {len(pairs)} tavling(ar) → Odoo ({env.db})")
    for ssfta_id, odoo_id in pairs:
        sync_one_competition(env, ssfta_id, odoo_id, dr)
    print("Klar.")


if __name__ == "__main__":
    main()