"""
cli.py — Command-line interface for clio-partnerdb.

Commands:
    list   [--owner EMAIL]              List partners (optionally filtered by watch owner)
    show   <id-or-name>                 Show all data for a partner
    history <id-or-name>               Show audit log for a partner
    add    --fornamn F --efternamn E    Add a partner manually
    merge  <winner-id> <loser-id>      Merge two partners (conservative, manual only)
    export-csv --owner EMAIL            Export watchlist to CSV
    import-csv --file FILE --owner E   Import CSV into watchlist
    stats                               Show DB statistics

Usage:
    python cli.py list --owner fredrik@arvas.se
    python cli.py show "Helena Arvas"
    python cli.py history <uuid>
    python cli.py merge <winner-uuid> <loser-uuid>
    python cli.py export-csv --owner fredrik@arvas.se --out watchlist.csv
    python cli.py import-csv --file watchlist.csv --owner fredrik@arvas.se
    python cli.py stats
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
import db as _db
from models import priority_to_english, priority_to_swedish


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = s.strip().lower()
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _find_partners_by_name(conn, query: str) -> list[str]:
    """Return partner_ids matching name query."""
    parts = [_norm(p) for p in query.strip().split()]
    rows = conn.execute(
        "SELECT partner_id, value FROM claim WHERE predicate='name'"
    ).fetchall()
    matches = []
    for row in rows:
        try:
            v = json.loads(row["value"])
            full = _norm(f"{v.get('fornamn','')} {v.get('efternamn','')}")
            if all(p in full for p in parts):
                matches.append(row["partner_id"])
        except Exception:
            pass
    return list(dict.fromkeys(matches))


def _display_name(conn, partner_id: str) -> str:
    names = _db.get_partner_names(conn, partner_id)
    if not names:
        return f"(no name) [{partner_id[:8]}]"
    n = names[0]
    return f"{n.get('fornamn','')} {n.get('efternamn','')}".strip()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list(args, conn) -> None:
    if args.owner:
        entries = _db.list_watch_entries(conn, args.owner)
        if not entries:
            print(f"No watch entries for {args.owner}")
            return
        print(f"{'Priority':<12} {'Name':<28} {'Born':<6} {'City':<16} {'Source'}")
        print("-" * 72)
        for e in sorted(entries, key=lambda x: (x["priority"], x["efternamn"])):
            prio = priority_to_swedish(e["priority"])
            name = f"{e['fornamn']} {e['efternamn']}".strip()
            print(f"{prio:<12} {name:<28} {e['birth_year'] or '':<6} "
                  f"{(e['city'] or ''):<16} {e['source'] or ''}")
    else:
        rows = conn.execute("SELECT COUNT(*) as n FROM partner").fetchone()
        watch_rows = conn.execute("SELECT COUNT(*) as n FROM watch").fetchone()
        print(f"Partners: {rows['n']}  Watch entries: {watch_rows['n']}")
        print("Use --owner EMAIL to list a specific watchlist.")


def cmd_show(args, conn) -> None:
    query = " ".join(args.query)
    partner_ids = _find_partners_by_name(conn, query)
    if not partner_ids:
        # Try as direct UUID
        row = conn.execute("SELECT id FROM partner WHERE id=?", (query,)).fetchone()
        if row:
            partner_ids = [row["id"]]
        else:
            print(f"No partner found matching '{query}'")
            return

    for pid in partner_ids:
        info = _db.partner_full_info(conn, pid)
        if not info:
            continue
        print(f"\n{'='*60}")
        print(f"ID         : {pid}")
        print(f"Created    : {info['partner']['created_at']}")
        print(f"Editors    : {info['partner']['editors']}")
        types = []
        if info["partner"]["is_person"]:
            types.append("person")
        if info["partner"]["is_org"]:
            types.append("organisation")
        print(f"Type       : {', '.join(types) or 'unknown'}")

        print(f"\nClaims ({len(info['claims'])}):")
        for c in sorted(info["claims"], key=lambda x: (x["predicate"], -x["is_primary"])):
            primary = " ★" if c["is_primary"] else "  "
            vf = f"  [{c['valid_from']}→{c['valid_to']}]" if c["valid_from"] else ""
            print(f"  {primary} {c['predicate']:15} {c['value']}{vf}")

        print(f"\nEvents ({len(info['events'])}):")
        for e in sorted(info["events"], key=lambda x: x["type"]):
            place = f" @ {e['place']}" if e["place"] else ""
            prec = f" ({e['date_precision']})" if e["date_precision"] else ""
            print(f"  {e['type']:12} {e['date_from'] or '?'}{prec}{place}")

        rels = info["relationships_from"]
        if rels:
            print(f"\nRelationships ({len(rels)}):")
            for r in sorted(rels, key=lambda x: (x["type"], x["to_id"])):
                other_name = _display_name(conn, r["to_id"])
                print(f"  {r['type']:15} {other_name}")

        if info["external_refs"]:
            print(f"\nExternal refs:")
            for r in info["external_refs"]:
                print(f"  {r['system']:35} {r['external_id']}")

        # Watch entries
        watches = conn.execute(
            "SELECT * FROM watch WHERE partner_id=?", (pid,)
        ).fetchall()
        if watches:
            print(f"\nWatched by:")
            for w in watches:
                prio = priority_to_swedish(w["priority"])
                print(f"  {w['owner_email']:30} {prio:12} added: {w['added_at'][:10]}")


def cmd_history(args, conn) -> None:
    query = " ".join(args.query)
    partner_ids = _find_partners_by_name(conn, query)
    if not partner_ids:
        row = conn.execute("SELECT id FROM partner WHERE id LIKE ?", (f"{query}%",)).fetchone()
        if row:
            partner_ids = [row["id"]]
        else:
            print(f"No partner found matching '{query}'")
            return

    pid = partner_ids[0]
    name = _display_name(conn, pid)
    print(f"\nAudit history for: {name} [{pid}]\n")

    rows = conn.execute(
        """SELECT * FROM audit_log
           WHERE row_key LIKE ?
           ORDER BY changed_at""",
        (f"%{pid}%",),
    ).fetchall()

    if not rows:
        print("  (no audit records found)")
        return

    for r in rows:
        ts = r["changed_at"][:19].replace("T", " ")
        before = f" ← {r['before_json'][:60]}" if r["before_json"] else ""
        after = f" → {r['after_json'][:80]}" if r["after_json"] else ""
        reason = f"  [{r['reason']}]" if r["reason"] else ""
        print(f"  {ts}  {r['operation']:8} {r['table_name']:15} by {r['changed_by']}{reason}")
        if args.verbose:
            if before:
                print(f"    before: {r['before_json']}")
            if after:
                print(f"    after:  {r['after_json']}")


def cmd_add(args, conn) -> None:
    import uuid
    pid = str(uuid.uuid4())
    actor = args.actor or "system:cli"
    ts = datetime.now(timezone.utc).isoformat()
    partner_row = {
        "id": pid, "created_at": ts,
        "editors": json.dumps([actor]), "is_person": 1, "is_org": 0,
    }
    with conn:
        conn.execute(
            "INSERT INTO partner (id, created_at, editors, is_person, is_org) VALUES (?,?,?,?,?)",
            (pid, ts, partner_row["editors"], 1, 0),
        )
        _db.audit(conn, "partner", {"id": pid}, "insert", after=partner_row, actor=actor,
                  reason="manual add via cli")

    src_id = _db.insert_source(conn, "manual", "cli", actor=actor)
    _db.upsert_claim(conn, pid, "name",
                     {"fornamn": args.fornamn, "efternamn": args.efternamn},
                     source_id=src_id, actor=actor, is_primary=True)

    if args.birth_year:
        _db.upsert_event(conn, pid, "birth", src_id, actor,
                         date_from=str(args.birth_year), date_precision="year")
    if args.city:
        _db.upsert_claim(conn, pid, "city", args.city, source_id=src_id,
                         actor=actor, is_primary=True)

    if args.owner:
        priority = priority_to_english(args.priority or "normal")
        _db.upsert_watch(conn, args.owner, pid, priority, source="manual", actor=actor)
        print(f"Added: {args.fornamn} {args.efternamn} [{pid[:8]}] — watch added for {args.owner}")
    else:
        print(f"Added: {args.fornamn} {args.efternamn} [{pid[:8]}]")


def cmd_merge(args, conn) -> None:
    """
    Merge loser into winner (conservative — manual only, no auto-merge).
    Rewrites: watch, relationship, external_ref rows.
    Keeps loser UUID in external_ref as 'merged:<loser_id>' for traceability.
    """
    winner_id = args.winner
    loser_id = args.loser

    winner = conn.execute("SELECT * FROM partner WHERE id=?", (winner_id,)).fetchone()
    loser  = conn.execute("SELECT * FROM partner WHERE id=?", (loser_id,)).fetchone()
    if not winner:
        print(f"Winner not found: {winner_id}")
        return
    if not loser:
        print(f"Loser not found: {loser_id}")
        return

    winner_name = _display_name(conn, winner_id)
    loser_name  = _display_name(conn, loser_id)
    print(f"Merging: {loser_name} [{loser_id[:8]}] → {winner_name} [{winner_id[:8]}]")
    if not args.yes:
        confirm = input("Confirm merge? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    actor = args.actor or "system:cli"
    reason = f"merge {loser_id} into {winner_id}"

    with conn:
        # Migrate claims
        conn.execute("UPDATE claim SET partner_id=? WHERE partner_id=?", (winner_id, loser_id))
        # Migrate events
        conn.execute("UPDATE event SET partner_id=? WHERE partner_id=?", (winner_id, loser_id))
        # Migrate relationships (avoid duplicates)
        conn.execute("""UPDATE relationship SET from_id=?
                        WHERE from_id=? AND NOT EXISTS (
                            SELECT 1 FROM relationship r2
                            WHERE r2.from_id=? AND r2.to_id=relationship.to_id AND r2.type=relationship.type
                        )""", (winner_id, loser_id, winner_id))
        conn.execute("""UPDATE relationship SET to_id=?
                        WHERE to_id=? AND NOT EXISTS (
                            SELECT 1 FROM relationship r2
                            WHERE r2.to_id=? AND r2.from_id=relationship.from_id AND r2.type=relationship.type
                        )""", (winner_id, loser_id, winner_id))
        conn.execute("DELETE FROM relationship WHERE from_id=? OR to_id=?", (loser_id, loser_id))
        # Migrate watch (avoid duplicates — winner takes precedence)
        conn.execute("""UPDATE watch SET partner_id=?
                        WHERE partner_id=? AND NOT EXISTS (
                            SELECT 1 FROM watch w2 WHERE w2.partner_id=? AND w2.owner_email=watch.owner_email
                        )""", (winner_id, loser_id, winner_id))
        conn.execute("DELETE FROM watch WHERE partner_id=?", (loser_id,))
        # Keep external_refs, pointing to winner
        conn.execute("UPDATE external_ref SET partner_id=? WHERE partner_id=?", (winner_id, loser_id))
        # Add a tombstone external_ref so we can trace the merge
        existing = conn.execute(
            "SELECT 1 FROM external_ref WHERE system=? AND external_id=?",
            ("merged", loser_id),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO external_ref (system, external_id, partner_id) VALUES (?,?,?)",
                ("merged", loser_id, winner_id),
            )
        # Delete loser partner
        conn.execute("DELETE FROM partner WHERE id=?", (loser_id,))
        _db.audit(conn, "partner", {"id": loser_id}, "delete",
                  before=dict(loser), actor=actor, reason=reason)
        _db.audit(conn, "partner", {"id": winner_id}, "update",
                  actor=actor, reason=reason)

    print(f"Merged. Loser UUID {loser_id} traced via external_ref (system='merged').")


def cmd_export_csv(args, conn) -> None:
    entries = _db.list_watch_entries(conn, args.owner)
    if not entries:
        print(f"No watch entries for {args.owner}")
        return

    out_path = args.out or f"{args.owner}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["efternamn", "fornamn", "fodelsear", "hemort", "prioritet", "kalla"]
        )
        writer.writeheader()
        for e in entries:
            writer.writerow({
                "efternamn": e["efternamn"],
                "fornamn":   e["fornamn"],
                "fodelsear": e["birth_year"] or "",
                "hemort":    e["city"] or "",
                "prioritet": priority_to_swedish(e["priority"]),
                "kalla":     e["source"] or "manual",
            })
    print(f"Exported {len(entries)} entries to {out_path}")


def cmd_import_csv(args, conn) -> None:
    actor = args.actor or "system:cli"
    src_id = _db.insert_source(conn, "csv_import", os.path.basename(args.file),
                                actor=actor)
    import uuid as _uuid

    added = skipped = 0
    with open(args.file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(line for line in f if not line.lstrip().startswith("#"))
        for row in reader:
            fornamn   = row.get("fornamn", "").strip()
            efternamn = row.get("efternamn", "").strip()
            if not fornamn or not efternamn:
                continue

            # Check for existing partner with same name (conservative — no auto-merge)
            existing = _find_partners_by_name(conn, f"{fornamn} {efternamn}")
            if existing:
                pid = existing[0]
            else:
                pid = str(_uuid.uuid4())
                ts = _db.now_iso()
                partner_row = {"id": pid, "created_at": ts,
                               "editors": json.dumps([actor]), "is_person": 1, "is_org": 0}
                with conn:
                    conn.execute(
                        "INSERT INTO partner (id, created_at, editors, is_person, is_org) VALUES (?,?,?,?,?)",
                        (pid, ts, partner_row["editors"], 1, 0),
                    )
                    _db.audit(conn, "partner", {"id": pid}, "insert",
                              after=partner_row, actor=actor, reason="csv_import")
                _db.upsert_claim(conn, pid, "name",
                                 {"fornamn": fornamn, "efternamn": efternamn},
                                 source_id=src_id, actor=actor, is_primary=True)
                birth_year_str = row.get("fodelsear", "").strip()
                if birth_year_str and birth_year_str.isdigit():
                    _db.upsert_event(conn, pid, "birth", src_id, actor,
                                     date_from=birth_year_str, date_precision="year")
                city = row.get("hemort", "").strip()
                if city:
                    _db.upsert_claim(conn, pid, "city", city,
                                     source_id=src_id, actor=actor, is_primary=True)

            priority_sw = row.get("prioritet", "normal").strip()
            priority_en = priority_to_english(priority_sw)
            source = row.get("kalla", "csv_import").strip()
            was_new = _db.upsert_watch(conn, args.owner, pid, priority_en, source, actor=actor)
            if was_new:
                added += 1
            else:
                skipped += 1

    print(f"import-csv: {added} added, {skipped} already existed")


def cmd_stats(args, conn) -> None:
    tables = ["partner", "event", "claim", "relationship", "source",
              "external_ref", "watch", "audit_log"]
    print("clio-partnerdb statistics")
    print(f"  DB: {_db.get_db_path()}")
    print(f"  Schema version: {_db.schema_version(conn)}")
    print()
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<20} {n:>8}")


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="clio-partnerdb CLI")
    p.add_argument("--db", default=None, metavar="PATH",
                   help="Override DB path (default: ~/.clio/partnerdb.sqlite)")
    sub = p.add_subparsers(dest="command", required=True)

    # list
    lp = sub.add_parser("list", help="List partners or watchlist")
    lp.add_argument("--owner", default=None)

    # show
    sp = sub.add_parser("show", help="Show all data for a partner")
    sp.add_argument("query", nargs="+")

    # history
    hp = sub.add_parser("history", help="Show audit log for a partner")
    hp.add_argument("query", nargs="+")
    hp.add_argument("--verbose", "-v", action="store_true")

    # add
    ap = sub.add_parser("add", help="Add a partner manually")
    ap.add_argument("--fornamn", required=True)
    ap.add_argument("--efternamn", required=True)
    ap.add_argument("--birth-year", type=int, default=None)
    ap.add_argument("--city", default=None)
    ap.add_argument("--owner", default=None, help="Also add a watch row for this owner")
    ap.add_argument("--priority", default="normal")
    ap.add_argument("--actor", default=None)

    # merge
    mp = sub.add_parser("merge", help="Merge loser partner into winner (manual only)")
    mp.add_argument("winner")
    mp.add_argument("loser")
    mp.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    mp.add_argument("--actor", default=None)

    # export-csv
    ep = sub.add_parser("export-csv", help="Export watchlist to CSV")
    ep.add_argument("--owner", required=True)
    ep.add_argument("--out", default=None, help="Output file (default: <owner>.csv)")

    # import-csv
    ip = sub.add_parser("import-csv", help="Import CSV into watchlist")
    ip.add_argument("--file", required=True)
    ip.add_argument("--owner", required=True)
    ip.add_argument("--actor", default=None)

    # stats
    sub.add_parser("stats", help="Show DB statistics")

    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    conn = _db.connect(args.db)
    {
        "list":       cmd_list,
        "show":       cmd_show,
        "history":    cmd_history,
        "add":        cmd_add,
        "merge":      cmd_merge,
        "export-csv": cmd_export_csv,
        "import-csv": cmd_import_csv,
        "stats":      cmd_stats,
    }[args.command](args, conn)


if __name__ == "__main__":
    main()
