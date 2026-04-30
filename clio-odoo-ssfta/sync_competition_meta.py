"""
sync_competition_meta.py -- Synkar tävlingsmetadata från SSFTA till Odoo ssf-db.

Ordning: Sectors -> Seasons -> Disciplines -> Classes -> Events -> Competitions -> CCDs
Filtren begränsar Events (och därigenom Competitions + CCDs via SQL-subquery).

Körning:
    python3 sync_competition_meta.py                                     # hela SSFTA
    python3 sync_competition_meta.py --season 18,19 --district Dalarna   # Dalarna 2025/26+
    python3 sync_competition_meta.py --season 19 --sector AL             # Alpine innevar. säs.
    python3 sync_competition_meta.py --clear --season 18,19 --district Dalarna --db ssf_t2
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


# ─── Helpers ──────────────────────────────────────────────────────────────────

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


def _upsert(Model, rows: list[dict], key: str = "ssfta_id", dry_run: bool = False, skip_updates: bool = False) -> tuple[int, int]:
    """Batch-upsert: creates i batchar om BATCH, writes per rad (ovanliga). skip_updates hoppar write()."""
    created = updated = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        ids = [r[key] for r in batch]
        existing = {
            r[key]: r["id"]
            for r in Model.search_read([[key, "in", ids]], [key, "id"])
        }
        to_create = [r for r in batch if r[key] not in existing]
        to_update = [(existing[r[key]], r) for r in batch if r[key] in existing]

        if to_create and not dry_run:
            Model.create(to_create)  # batch-create: ett RPC-anrop per BATCH rader
        created += len(to_create)

        for odoo_id, row in to_update:
            if not dry_run and not skip_updates:
                Model.browse(odoo_id).write(row)
        updated += len(to_update)

    return created, updated


def _resolve_sector_ids(sector_codes: list[str] | None) -> list[int] | None:
    if not sector_codes:
        return None
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    placeholders = ",".join(f"'{c.strip()}'" for c in sector_codes)
    cur.execute(f"SELECT ID FROM Sectors WHERE SectorCode IN ({placeholders})")
    ids = [r["ID"] for r in cur.fetchall()]
    conn.close()
    if not ids:
        print(f"  VARNING: Inga Sectors hittades för koder {sector_codes}")
    return ids or None


def _resolve_district_ids(district_names: list[str] | None) -> list[int] | None:
    """Slår upp distriktorganisations-ID baserat på namn (partiell matchning)."""
    if not district_names:
        return None
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    conditions = " OR ".join(
        f"FullName LIKE '%{n}%' OR ShortName LIKE '%{n}%'"
        for n in district_names
    )
    cur.execute(f"SELECT ID, FullName FROM Organizations WHERE OrganizationType IN (4,11) AND ({conditions})")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print(f"  VARNING: Inga distrikt hittades för namn {district_names}")
        return None
    for r in rows:
        print(f"  Distrikt: {r['FullName']} (ID={r['ID']})")
    return [r["ID"] for r in rows]


def _build_event_where(
    seasons: list[int] | None,
    sector_ids: list[int] | None,
    district_ids: list[int] | None,
) -> str:
    clauses = []
    if seasons:
        clauses.append(f"Season IN ({','.join(str(s) for s in seasons)})")
    if sector_ids:
        clauses.append(f"Sector IN ({','.join(str(s) for s in sector_ids)})")
    if district_ids:
        parent_list = ",".join(str(d) for d in district_ids)
        clauses.append(
            f"Organizer IN ("
            f"SELECT ChildId FROM OrganizationRelations WHERE ParentId IN ({parent_list})"
            f" UNION SELECT ID FROM Organizations WHERE ID IN ({parent_list})"
            f")"
        )
    return ("WHERE " + " AND ".join(clauses)) if clauses else ""


# ─── Clear ────────────────────────────────────────────────────────────────────

def clear_events(env, dry_run: bool):
    """Raderar alla ssf.event (cascade tar med competitions + CCDs)."""
    records = env["ssf.event"].search_read([], ["id"])
    if not records:
        print("  Clear: inga events att radera")
        return
    ids = [r["id"] for r in records]
    print(f"  Clear: raderar {len(ids)} events (+ tävlingar + CCDs via cascade)...")
    if not dry_run:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            env["ssf.event"].browse(chunk).unlink()
    print("  Clear: klar")


# ─── Referensdata (synkas alltid komplett) ────────────────────────────────────

def sync_sectors(env, dry_run: bool):
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("SELECT ID, SectorCode, Name, Hidden, SortOrder, FisSectorCode FROM Sectors")
    rows = [
        {
            "ssfta_id": r["ID"],
            "name": r["Name"] or f"Sektor {r['ID']}",
            "sector_code": r["SectorCode"] or "",
            "hidden": bool(r["Hidden"]),
            "sort_order": r["SortOrder"] or 0,
            "fis_sector_code": r["FisSectorCode"] or "",
        }
        for r in cur.fetchall()
    ]
    conn.close()
    c, u = _upsert(env["ssf.sector"], rows, dry_run=dry_run)
    print(f"  Sectors:     {c} skapade, {u} uppdaterade")


def sync_seasons(env, dry_run: bool):
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("SELECT ID, Name FROM Seasons")
    rows = [{"ssfta_id": r["ID"], "name": r["Name"] or str(r["ID"])} for r in cur.fetchall()]
    conn.close()
    c, u = _upsert(env["ssf.season"], rows, dry_run=dry_run)
    print(f"  Seasons:     {c} skapade, {u} uppdaterade")


def sync_disciplines(env, dry_run: bool):
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("SELECT ID, Name, ShortName, Sector, Hidden, SortOrder, TeamEntry FROM Disciplines")
    rows_raw = cur.fetchall()
    conn.close()
    sector_map = {r["ssfta_id"]: r["id"] for r in env["ssf.sector"].search_read([], ["ssfta_id", "id"])}
    rows = [
        {
            "ssfta_id": r["ID"],
            "name": r["Name"] or f"Disciplin {r['ID']}",
            "short_name": r["ShortName"] or "",
            "sector_id": sector_map.get(r["Sector"]) or False,
            "hidden": bool(r["Hidden"]),
            "sort_order": r["SortOrder"] or 0,
            "team_entry": bool(r["TeamEntry"]),
        }
        for r in rows_raw
    ]
    c, u = _upsert(env["ssf.discipline"], rows, dry_run=dry_run)
    print(f"  Disciplines: {c} skapade, {u} uppdaterade")


def sync_classes(env, dry_run: bool):
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute("SELECT ID, Name, LocalName, Sector, FromAge, ToAge, Gender, Hidden, SortOrder FROM Classes")
    rows_raw = cur.fetchall()
    conn.close()
    sector_map = {r["ssfta_id"]: r["id"] for r in env["ssf.sector"].search_read([], ["ssfta_id", "id"])}
    rows = [
        {
            "ssfta_id": r["ID"],
            "name": r["Name"] or f"Klass {r['ID']}",
            "local_name": r["LocalName"] or "",
            "sector_id": sector_map.get(r["Sector"]) or False,
            "from_age": r["FromAge"] or 0,
            "to_age": r["ToAge"] or 0,
            "gender": r["Gender"] or "",
            "hidden": bool(r["Hidden"]),
            "sort_order": r["SortOrder"] or 0,
        }
        for r in rows_raw
    ]
    c, u = _upsert(env["ssf.comp.class"], rows, dry_run=dry_run)
    print(f"  Classes:     {c} skapade, {u} uppdaterade")


# ─── Events / Competitions / CCDs (filtreras av event_where) ─────────────────

def sync_events(
    env, dry_run: bool,
    seasons: list[int] | None,
    sector_ids: list[int] | None,
    district_ids: list[int] | None,
    skip_updates: bool = False,
) -> str:
    """Returnerar event_where för att återanvända i competitions + CCDs."""
    event_where = _build_event_where(seasons, sector_ids, district_ids)
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute(f"""
        SELECT e.ID, e.Name, e.Sector, e.Season, e.StartDate, e.EndDate,
               e.Place, e.City, e.Organizer, e.EventStatus, e.Note, e.Email, e.Website,
               e.GeographicalScope,
               et.LocalName AS EventTypeName
        FROM Events e
        LEFT JOIN EventTypes et ON e.EventType = et.ID
        {event_where}
    """)
    rows_raw = cur.fetchall()
    conn.close()

    sector_map = {r["ssfta_id"]: r["id"] for r in env["ssf.sector"].search_read([], ["ssfta_id", "id"])}
    season_map = {r["ssfta_id"]: r["id"] for r in env["ssf.season"].search_read([], ["ssfta_id", "id"])}

    # Slå upp organizer -> res.partner via rfid (batcad)
    org_ssfta_ids = list({r["Organizer"] for r in rows_raw if r["Organizer"]})
    org_odoo_map = {}
    if org_ssfta_ids:
        org_conn = _get_conn()
        org_cur = org_conn.cursor(as_dict=True)
        placeholders = ",".join(str(i) for i in org_ssfta_ids)
        org_cur.execute(f"SELECT ID, rfid FROM Organizations WHERE ID IN ({placeholders})")
        rfid_to_ssfta = {row["ID"]: row["rfid"] for row in org_cur.fetchall() if row["rfid"]}
        org_conn.close()
        for ssfta_id, rfid in rfid_to_ssfta.items():
            partners = env["res.partner"].search_read([("ref", "=", f"ssfta-{rfid}")], ["id"])
            if partners:
                org_odoo_map[ssfta_id] = partners[0]["id"]

    rows = []
    for r in rows_raw:
        start = r["StartDate"].date() if r["StartDate"] else False
        end = r["EndDate"].date() if r["EndDate"] else False
        rows.append({
            "ssfta_id": r["ID"],
            "name": r["Name"] or f"Evenemang {r['ID']}",
            "sector_id": sector_map.get(r["Sector"]) or False,
            "season_id": season_map.get(r["Season"]) or False,
            "start_date": str(start) if start else False,
            "end_date": str(end) if end else False,
            "place": r["Place"] or "",
            "city": r["City"] or "",
            "organizer_id": org_odoo_map.get(r["Organizer"]) or False,
            "event_status": str(r["EventStatus"]) if r["EventStatus"] else False,
            "note": r["Note"] or "",
            "email": r["Email"] or "",
            "website": r["Website"] or "",
            "geographical_scope": str(r["GeographicalScope"]) if r["GeographicalScope"] else False,
            "event_type_label":   r["EventTypeName"] or "",
        })

    c, u = _upsert(env["ssf.event"], rows, dry_run=dry_run, skip_updates=skip_updates)
    print(f"  Events:      {c} skapade, {u} uppdaterade  (totalt {len(rows)})")
    return event_where


def sync_competitions(env, dry_run: bool, event_where: str, skip_updates: bool = False):
    """Laddar bara tävlingar vars event matchar event_where."""
    comp_filter = (
        f"WHERE Event IN (SELECT ID FROM Events {event_where})"
        if event_where else ""
    )
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute(f"""
        SELECT ID, Name, Event, Date, CompetitionStatus,
               LastEntryDate, EntryOpen, LiveResultsLink
        FROM Competitions {comp_filter}
    """)
    rows_raw = cur.fetchall()
    conn.close()

    event_map = {r["ssfta_id"]: r["id"] for r in env["ssf.event"].search_read([], ["ssfta_id", "id"])}
    rows = []
    skipped = 0
    for r in rows_raw:
        event_id = event_map.get(r["Event"])
        if not event_id:
            skipped += 1
            continue
        date = r["Date"].date() if r["Date"] else False
        rows.append({
            "ssfta_id": r["ID"],
            "name": r["Name"] or f"Tavling {r['ID']}",
            "event_id": event_id,
            "date": str(date) if date else False,
            "competition_status": str(r["CompetitionStatus"]) if r["CompetitionStatus"] else False,
            "last_entry_date": str(r["LastEntryDate"]) if r["LastEntryDate"] else False,
            "entry_open": bool(r["EntryOpen"]),
            "live_results_link": r["LiveResultsLink"] or "",
        })

    c, u = _upsert(env["ssf.competition"], rows, dry_run=dry_run, skip_updates=skip_updates)
    print(f"  Competitions:{c} skapade, {u} uppdaterade  (hoppade: {skipped})")


def sync_ccds(env, dry_run: bool, event_where: str, skip_updates: bool = False):
    """Laddar bara CCDs vars tävling matchar event_where."""
    ccd_filter = (
        f"WHERE Competition IN ("
        f"  SELECT ID FROM Competitions WHERE Event IN (SELECT ID FROM Events {event_where})"
        f")"
        if event_where else ""
    )
    conn = _get_conn()
    cur = conn.cursor(as_dict=True)
    cur.execute(f"""
        SELECT ID, Competition, Class, Discipline,
               Distance, FisCodex, NonMemberEntry, ForeignEntry
        FROM CompetitionClassDiscipline {ccd_filter}
    """)
    rows_raw = cur.fetchall()
    conn.close()

    comp_map = {r["ssfta_id"]: r["id"] for r in env["ssf.competition"].search_read([], ["ssfta_id", "id"])}
    class_map = {r["ssfta_id"]: r["id"] for r in env["ssf.comp.class"].search_read([], ["ssfta_id", "id"])}
    disc_map = {r["ssfta_id"]: r["id"] for r in env["ssf.discipline"].search_read([], ["ssfta_id", "id"])}

    rows = []
    skipped = 0
    for r in rows_raw:
        comp_id = comp_map.get(r["Competition"])
        if not comp_id:
            skipped += 1
            continue
        rows.append({
            "ssfta_id": r["ID"],
            "competition_id": comp_id,
            "class_id": class_map.get(r["Class"]) or False,
            "discipline_id": disc_map.get(r["Discipline"]) or False,
            "distance": r["Distance"] or "",
            "fis_codex": r["FisCodex"] or 0,
            "non_member_entry": bool(r["NonMemberEntry"]),
            "foreign_entry": bool(r["ForeignEntry"]),
        })

    c, u = _upsert(env["ssf.comp.ccd"], rows, dry_run=dry_run, skip_updates=skip_updates)
    print(f"  CCDs:        {c} skapade, {u} uppdaterade  (hoppade: {skipped})")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Synkar tavlingsmetadata SSFTA -> Odoo")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None)
    parser.add_argument("--clear", action="store_true",
                        help="Radera befintliga events/tavlingar/CCDs innan sync")
    parser.add_argument("--skip-updates", action="store_true",
                        help="Hoppa over write() pa befintliga poster (snabb inkrementell sync)")
    parser.add_argument("--season", default=None,
                        help="Kommasep. Season.ID, t.ex. 18,19")
    parser.add_argument("--sector", default=None,
                        help="Kommasep. sektorkoder, t.ex. AL eller AL,CC,SB")
    parser.add_argument("--district", default=None,
                        help="Kommasep. distriktnamn, t.ex. Dalarna")
    args = parser.parse_args()

    seasons = [int(s.strip()) for s in args.season.split(",")] if args.season else None
    sector_codes = [s.strip().upper() for s in args.sector.split(",")] if args.sector else None
    district_names = [d.strip() for d in args.district.split(",")] if args.district else None

    sector_ids = _resolve_sector_ids(sector_codes)
    district_ids = _resolve_district_ids(district_names)

    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    dr = args.dry_run
    mode = "[DRY-RUN] " if dr else ""

    filter_parts = []
    if seasons:
        filter_parts.append(f"säsong={seasons}")
    if sector_codes:
        filter_parts.append(f"sektor={sector_codes}")
    if district_names:
        filter_parts.append(f"distrikt={district_names}")
    filter_str = "  filter: " + ", ".join(filter_parts) if filter_parts else "  (ingen filtrering)"

    print(f"{mode}Synkar tavlingsmetadata SSFTA -> Odoo ({env.db})")
    print(filter_str)

    if args.clear:
        clear_events(env, dr)

    sync_sectors(env, dr)
    sync_seasons(env, dr)
    sync_disciplines(env, dr)
    sync_classes(env, dr)
    su = args.skip_updates
    event_where = sync_events(env, dr, seasons=seasons, sector_ids=sector_ids, district_ids=district_ids, skip_updates=su)
    sync_competitions(env, dr, event_where, skip_updates=su)
    sync_ccds(env, dr, event_where, skip_updates=su)
    print("Klar.")


if __name__ == "__main__":
    main()
