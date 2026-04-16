"""
run.py — Main script for clio-agent-obit.

Daily monitoring workflow:
  1. Load watch lists from clio-partnerdb
  2. Fetch announcements from all sources
  3. Match against watch lists
  4. Apply first-run suppression (180 days grace per watch entry)
  5. Send notifications (immediate for 'important', digest for others)
  6. Log the run

Usage:
    python run.py
    python run.py --dry-run
    python run.py --backfill 2025-10-01..2026-01-01
    python run.py --show-all-matches
    python run.py --last-run

First-run suppression:
    Each watch entry has an added_at timestamp. Announcements published more
    than GRACE_DAYS before added_at are shown on screen / logged but do NOT
    trigger email notifications. This prevents inbox spam when a watch list
    is first imported with hundreds of entries.

    GRACE_DAYS = 180 (approx. 6 months)

Scheduling (Windows Task Scheduler):
    Program:   python
    Arguments: C:\\path\\to\\clio-agent-obit\\run.py
    Trigger:   Daily 08:15
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
_BASE_DIR = Path(os.path.dirname(__file__))
load_dotenv(_BASE_DIR.parent / ".env")          # root clio-tools/.env (prioritet)
load_dotenv(_BASE_DIR / ".env")                  # lokal fallback (standalone)

# ── partnerdb ─────────────────────────────────────────────────────────────────
_PARTNERDB_PATH = os.path.join(os.path.dirname(__file__), "..", "clio-partnerdb")
sys.path.insert(0, _PARTNERDB_PATH)
import db as _partnerdb

from matcher import (
    Announcement, WatchlistEntry, Match,
    match_announcement, filter_notifiable, load_entries_from_db,
)
from notifier import send_urgent, send_digest
from state import is_seen, mark_seen
from sources.registry import load_sources, RegistryError
from sources.source_base import SourceError

GRACE_DAYS = 180
LOG_FILE = os.path.join(os.path.dirname(__file__), "obit.log")


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


# ── Suppression ───────────────────────────────────────────────────────────────

def _is_suppressed(ann_date_str: str, watch_added_at: str) -> bool:
    """
    Return True if the announcement is older than GRACE_DAYS relative to
    when the watch entry was added. Suppressed matches are shown on screen
    but do NOT generate email notifications.
    """
    try:
        ann_dt  = datetime.fromisoformat(ann_date_str[:10])
        added_dt = datetime.fromisoformat(watch_added_at[:10])
        earliest_notifiable = added_dt - timedelta(days=GRACE_DAYS)
        return ann_dt < earliest_notifiable
    except Exception:
        return False


# ── Owners ────────────────────────────────────────────────────────────────────

def _load_all_watchlists(conn) -> dict[str, list[WatchlistEntry]]:
    """Return {owner_email: [WatchlistEntry, ...]} for all owners in DB."""
    rows = conn.execute(
        "SELECT DISTINCT owner_email FROM watch"
    ).fetchall()
    result: dict[str, list] = {}
    for row in rows:
        owner = row["owner_email"]
        entries = load_entries_from_db(conn, owner)
        if entries:
            result[owner] = entries
    return result


# ── Backfill ──────────────────────────────────────────────────────────────────

def _parse_date_range(s: str) -> tuple[str, str]:
    """Parse 'YYYY-MM-DD..YYYY-MM-DD' into (from_date, to_date)."""
    parts = s.split("..")
    if len(parts) != 2:
        raise ValueError(f"Invalid date range '{s}'. Expected format: 2025-10-01..2026-01-01")
    return parts[0].strip(), parts[1].strip()


def _fetch_backfill(date_from: str, date_to: str) -> list[Announcement]:
    """
    Fetch historical announcements from sources that support backfill.
    Currently: Familjesidan only. Fonus backfill TODO Sprint 3.
    """
    announcements: list[Announcement] = []
    try:
        sources = load_sources()
    except RegistryError:
        return announcements

    for source in sources:
        if not hasattr(source, "fetch_range"):
            print(f"[backfill] {source.name}: backfill not supported — skipping")
            continue
        try:
            fetched = source.fetch_range(date_from, date_to)
            announcements.extend(fetched)
            print(f"[backfill] {source.name}: {len(fetched)} announcements")
        except Exception as e:
            print(f"[backfill] {source.name}: error — {e}")

    return announcements


# ── Main run ──────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, show_all_matches: bool = False,
        backfill_range: str = None) -> int:
    """
    Main function. Returns exit code:
      0 = OK
      1 = Source error
      2 = Configuration error
    """
    start = datetime.now()
    date_str = start.strftime("%Y-%m-%d")
    timestamp = start.strftime("%Y-%m-%d %H:%M:%S")

    # ── Load watchlists from DB ───────────────────────────────────────────────
    conn = _partnerdb.connect()
    watchlists = _load_all_watchlists(conn)

    if not watchlists:
        _log(f"{timestamp} | No watch lists in partnerdb — add entries via import_gedcom.py")
        return 2

    total_entries = sum(len(v) for v in watchlists.values())
    _log(f"{timestamp} | Loaded {total_entries} watch entries for {len(watchlists)} owner(s)")

    # ── Fetch announcements ───────────────────────────────────────────────────
    if backfill_range:
        try:
            date_from, date_to = _parse_date_range(backfill_range)
        except ValueError as e:
            _log(f"{timestamp} | CONFIG ERROR: {e}")
            return 2
        _log(f"{timestamp} | Backfill mode: {date_from} → {date_to}")
        all_announcements = _fetch_backfill(date_from, date_to)
    else:
        try:
            sources = load_sources()
        except RegistryError as e:
            _log(f"{timestamp} | CONFIG ERROR: {e}")
            return 2

        if not sources:
            _log(f"{timestamp} | No active sources in sources.yaml — aborted")
            return 2

        all_announcements = []
        for source in sources:
            try:
                fetched = source.fetch()
                all_announcements.extend(fetched)
            except SourceError as e:
                _log(f"{timestamp} | SOURCE ERROR ({source.name}): {e}")
            except Exception as e:
                _log(f"{timestamp} | SOURCE ERROR ({source.name}, unexpected): {e}")

    # ── Filter already-seen (skip for backfill, it's a one-off scan) ─────────
    if backfill_range:
        new_announcements = all_announcements
    else:
        new_announcements = [a for a in all_announcements if not is_seen(a.id)]

    # ── Match and classify ────────────────────────────────────────────────────
    urgent_by_owner: dict[str, list[Match]] = {o: [] for o in watchlists}
    digest_by_owner: dict[str, list[Match]] = {o: [] for o in watchlists}
    suppressed: list[tuple[str, Match]] = []     # (owner, Match) — visible but no email
    all_matches_log: list[tuple[str, Match]] = []  # for --show-all-matches

    for announcement in new_announcements:
        any_match = False
        for owner, entries in watchlists.items():
            matches = match_announcement(announcement, entries)
            notifiable = filter_notifiable(matches)
            if notifiable:
                any_match = True
            for m in notifiable:
                all_matches_log.append((owner, m))
                if _is_suppressed(announcement.publiceringsdatum,
                                   m.entry.added_at or datetime.now(timezone.utc).isoformat()):
                    suppressed.append((owner, m))
                elif m.entry.prioritet == "viktig":
                    urgent_by_owner[owner].append(m)
                else:
                    digest_by_owner[owner].append(m)
        if not backfill_range:
            mark_seen(announcement.id, matched=any_match)

    # ── Display suppressed (screen only, no email) ────────────────────────────
    if suppressed:
        print(f"\n--- SUPPRESSED (>{GRACE_DAYS} days before watch added — no email) ---")
        for owner, m in suppressed:
            print(f"  [{owner}] {m.summary()}")
            print(f"           published: {m.announcement.publiceringsdatum}  "
                  f"watch added: {m.entry.added_at[:10] if m.entry.added_at else '?'}")

    # ── Show all matches if requested ─────────────────────────────────────────
    if show_all_matches and all_matches_log:
        print(f"\n--- ALL MATCHES ({len(all_matches_log)}) ---")
        for owner, m in all_matches_log:
            tag = "(suppressed)" if any(o == owner and mm.announcement.id == m.announcement.id
                                        for o, mm in suppressed) else ""
            print(f"  [{owner}] {m.summary()} {tag}")

    # ── Send notifications ────────────────────────────────────────────────────
    total_urgent = sum(len(v) for v in urgent_by_owner.values())
    total_digest = sum(len(v) for v in digest_by_owner.values())

    if not dry_run:
        for owner, matches in urgent_by_owner.items():
            for m in matches:
                try:
                    send_urgent(m, to_addr=owner)
                except Exception as e:
                    _log(f"{timestamp} | MAIL ERROR (urgent → {owner}): {e}")

        for owner, matches in digest_by_owner.items():
            if matches:
                try:
                    send_digest(matches, run_date=date_str, to_addr=owner)
                except Exception as e:
                    _log(f"{timestamp} | MAIL ERROR (digest → {owner}): {e}")
    elif total_urgent or total_digest:
        print(f"\n--- DRY RUN: would have sent ---")
        for owner, matches in urgent_by_owner.items():
            for m in matches:
                print(f"  [URGENT → {owner}] {m.summary()}")
        for owner, matches in digest_by_owner.items():
            for m in matches:
                print(f"  [DIGEST → {owner}] {m.summary()}")

    # ── Log ───────────────────────────────────────────────────────────────────
    total_matches = total_urgent + total_digest
    digest_sent = "yes" if total_digest and not dry_run else "no"
    all_urgent = [m for ms in urgent_by_owner.values() for m in ms]
    urgent_names = ", ".join(
        f"{m.entry.fornamn} {m.entry.efternamn}" for m in all_urgent
    )
    log_line = (
        f"{timestamp} | "
        f"announcements: {len(all_announcements)} | "
        f"new: {len(new_announcements)} | "
        f"matches: {total_matches} | "
        f"suppressed: {len(suppressed)} | "
        f"digest: {digest_sent}"
    )
    if urgent_names:
        log_line += f" | URGENT: {urgent_names}"
    _log(log_line)
    return 0


def last_run() -> str:
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        return lines[-1] if lines else "No run recorded"
    except FileNotFoundError:
        return "obit.log not found — clio-agent-obit has never run"


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="clio-agent-obit — daily death notice monitoring")
    p.add_argument("--dry-run",  action="store_true",
                   help="Match but do not send emails")
    p.add_argument("--last-run", action="store_true",
                   help="Print last run summary and exit")
    p.add_argument("--backfill", metavar="FROM..TO",
                   help="Scan historical archive, e.g. 2025-10-01..2026-01-01 (Familjesidan only)")
    p.add_argument("--show-all-matches", action="store_true",
                   help="Print all matches including suppressed ones")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.last_run:
        print(last_run())
        return
    exit_code = run(
        dry_run=args.dry_run,
        show_all_matches=args.show_all_matches,
        backfill_range=args.backfill,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
