"""
run.py — Main script for clio-agent-obit.

Daily monitoring workflow:
  1. Load watch lists (Odoo if available, else clio-partnerdb)
  2. Fetch announcements from all sources
  3. Deduplicate (Odoo bulk-IDs if available, else state.db)
  4. Match against watch lists
  5. Apply first-run suppression (180 days grace per watch entry)
  6. For matched announcements: fetch detail page (body text + newspaper image)
  7. Send notifications (immediate for 'viktig', digest for others)
  8. Save all new announcements to Odoo + save matches
  9. Write heartbeat to Odoo cockpit
 10. Log the run

Usage:
    python run.py
    python run.py --dry-run
    python run.py --no-odoo
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

# ── partnerdb (fallback om Odoo ej tillgänglig) ───────────────────────────────
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
import odoo_writer
from odoo_reader import load_watchlist_from_odoo, get_partner_odoo_id

GRACE_DAYS = 180
LOG_FILE = os.path.join(os.path.dirname(__file__), "obit.log")


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


# ── Suppression ───────────────────────────────────────────────────────────────

def _is_suppressed(ann_date_str: str, watch_added_at: str) -> bool:
    try:
        ann_dt  = datetime.fromisoformat(ann_date_str[:10])
        added_dt = datetime.fromisoformat(watch_added_at[:10])
        earliest_notifiable = added_dt - timedelta(days=GRACE_DAYS)
        return ann_dt < earliest_notifiable
    except Exception:
        return False


# ── Owners ────────────────────────────────────────────────────────────────────

def _load_all_watchlists_from_partnerdb(conn) -> dict[str, list[WatchlistEntry]]:
    """Fallback: ladda bevakningslista från clio-partnerdb (SQLite)."""
    rows = conn.execute("SELECT DISTINCT owner_email FROM watch").fetchall()
    result: dict[str, list] = {}
    for row in rows:
        owner = row["owner_email"]
        entries = load_entries_from_db(conn, owner)
        if entries:
            result[owner] = entries
    return result


def _load_watchlists(use_odoo: bool, env, notify_to: str) -> dict[str, list[WatchlistEntry]]:
    """
    Laddar bevakningslistan. Prioritet: Odoo → partnerdb.
    Returnerar alltid ett dict (kan vara tomt om inget hittas).
    """
    if use_odoo and env is not None:
        odoo_lists = load_watchlist_from_odoo(env, default_notify_email=notify_to)
        if odoo_lists is not None:
            return odoo_lists
        _log("[odoo] Kunde inte ladda bevakningslista från Odoo — faller tillbaka på partnerdb")

    conn = _partnerdb.connect()
    return _load_all_watchlists_from_partnerdb(conn)


# ── Backfill ──────────────────────────────────────────────────────────────────

def _parse_date_range(s: str) -> tuple[str, str]:
    parts = s.split("..")
    if len(parts) != 2:
        raise ValueError(f"Ogiltigt datumintervall '{s}'. Förväntat format: 2025-10-01..2026-01-01")
    return parts[0].strip(), parts[1].strip()


def _fetch_backfill(date_from: str, date_to: str) -> list[Announcement]:
    announcements: list[Announcement] = []
    try:
        sources = load_sources()
    except RegistryError:
        return announcements
    for source in sources:
        if not hasattr(source, "fetch_range"):
            print(f"[backfill] {source.name}: backfill stöds ej — hoppar över")
            continue
        try:
            fetched = source.fetch_range(date_from, date_to)
            announcements.extend(fetched)
            print(f"[backfill] {source.name}: {len(fetched)} annonser")
        except Exception as e:
            print(f"[backfill] {source.name}: fel — {e}")
    return announcements


# ── Detail fetch ──────────────────────────────────────────────────────────────

def _fetch_detail_for_announcement(ann: Announcement, sources) -> None:
    """
    Hämtar detaljsidan (brödtext + bild) för en annons in-place.
    Hittar rätt källa via source_name och anropar fetch_detail().
    """
    if not ann.url:
        return
    source_obj = next((s for s in sources if s.name == ann.source_name), None)
    if source_obj is None:
        source_obj = sources[0] if sources else None
    if source_obj is None or not hasattr(source_obj, "fetch_detail"):
        return
    try:
        detail = source_obj.fetch_detail(ann.url)
        ann.body_html = detail.get("body_html", "")
        image_url = detail.get("image_url", "")
        if image_url:
            ann.image_data = _download_image(image_url, source_obj.user_agent)
    except Exception as e:
        print(f"[detail] {ann.url}: fel — {e}")


def _download_image(url: str, user_agent: str) -> bytes | None:
    try:
        import requests
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=20)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "image" in ct or len(resp.content) > 1024:
            return resp.content
    except Exception:
        pass
    return None


# ── Notify.to från config ─────────────────────────────────────────────────────

def _get_notify_to() -> str:
    """Läser notify.to från config.yaml — används som default owner-email för Odoo-poster."""
    try:
        import configparser, yaml
        cfg_path = _BASE_DIR / "config.yaml"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("notify", {}).get("to", "") or ""
    except Exception:
        return ""


# ── Main run ──────────────────────────────────────────────────────────────────

def run(
    dry_run: bool = False,
    show_all_matches: bool = False,
    backfill_range: str = None,
    use_odoo: bool = True,
) -> int:
    """
    Huvudfunktion. Returnerar exitkod:
      0 = OK
      1 = Källfel
      2 = Konfigurationsfel
    """
    start = datetime.now()
    date_str = start.strftime("%Y-%m-%d")
    timestamp = start.strftime("%Y-%m-%d %H:%M:%S")

    # ── Odoo-anslutning ───────────────────────────────────────────────────────
    env = odoo_writer.get_odoo_env() if use_odoo else None
    if use_odoo and env is None:
        _log(f"{timestamp} | [odoo] Ingen anslutning — kör utan Odoo (state.db används)")

    notify_to = _get_notify_to()

    # ── Bevakningslista ───────────────────────────────────────────────────────
    watchlists = _load_watchlists(use_odoo, env, notify_to)
    if not watchlists:
        _log(f"{timestamp} | Inga bevakningsposter — lägg till via Odoo eller import_gedcom.py")
        odoo_writer.write_heartbeat(env, "warning", 0, "Inga bevakningsposter")
        return 2

    total_entries = sum(len(v) for v in watchlists.values())
    _log(f"{timestamp} | {total_entries} bevakningsposter för {len(watchlists)} ägare")

    # ── Hämta annonser ────────────────────────────────────────────────────────
    if backfill_range:
        try:
            date_from, date_to = _parse_date_range(backfill_range)
        except ValueError as e:
            _log(f"{timestamp} | KONFIGFEL: {e}")
            return 2
        _log(f"{timestamp} | Backfill-läge: {date_from} → {date_to}")
        all_announcements = _fetch_backfill(date_from, date_to)
        active_sources = []
    else:
        try:
            active_sources = load_sources()
        except RegistryError as e:
            _log(f"{timestamp} | KONFIGFEL: {e}")
            return 2
        if not active_sources:
            _log(f"{timestamp} | Inga aktiva källor i sources.yaml — avbryter")
            return 2

        all_announcements = []
        for source in active_sources:
            try:
                fetched = source.fetch()
                all_announcements.extend(fetched)
            except SourceError as e:
                _log(f"{timestamp} | KÄLLFEL ({source.name}): {e}")
            except Exception as e:
                _log(f"{timestamp} | KÄLLFEL ({source.name}, oväntat): {e}")

    # ── Deduplicering ─────────────────────────────────────────────────────────
    if backfill_range:
        new_announcements = all_announcements
    else:
        # Odoo-bulk-dedup (primär), state.db (fallback/backup)
        odoo_seen_ids = odoo_writer.bulk_load_seen_ann_ids(env) if env else set()
        if odoo_seen_ids:
            new_announcements = [a for a in all_announcements if a.id not in odoo_seen_ids]
        else:
            new_announcements = [a for a in all_announcements if not is_seen(a.id)]

    # ── Matchning ─────────────────────────────────────────────────────────────
    urgent_by_owner:  dict[str, list[Match]] = {o: [] for o in watchlists}
    digest_by_owner:  dict[str, list[Match]] = {o: [] for o in watchlists}
    suppressed:       list[tuple[str, Match]] = []
    all_matches_log:  list[tuple[str, Match]] = []

    # Samla matchade annonser (dedup: en annons kan matcha via flera ägare)
    matched_ann_ids: set[str] = set()

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
        if any_match:
            matched_ann_ids.add(announcement.id)
        if not backfill_range:
            mark_seen(announcement.id, matched=any_match)  # state.db backup

    # ── Hämta detaljer för matchade annonser ──────────────────────────────────
    matched_announcements = [a for a in new_announcements if a.id in matched_ann_ids]
    if matched_announcements and active_sources:
        _log(f"{timestamp} | Hämtar detaljer för {len(matched_announcements)} matchad(e) annons(er)...")
        for ann in matched_announcements:
            _fetch_detail_for_announcement(ann, active_sources)

    # ── Spara till Odoo ───────────────────────────────────────────────────────
    # Bygg upp ann_id → odoo_id-map för matchningar
    ann_odoo_ids: dict[str, int] = {}

    if not backfill_range and env:
        for ann in new_announcements:
            odoo_id = odoo_writer.save_announcement(env, ann)
            if odoo_id:
                ann_odoo_ids[ann.id] = odoo_id

        # Uppdatera matchade annonser med detaljer
        for ann in matched_announcements:
            odoo_id = ann_odoo_ids.get(ann.id)
            if odoo_id:
                odoo_writer.update_announcement_detail(
                    env, odoo_id,
                    body_html=ann.body_html,
                    image_data=ann.image_data,
                    image_filename=f"obit_{ann.namn.replace(' ', '_')}.jpg" if ann.namn else "obit.jpg",
                    matched=True,
                )

        # Spara matchningar
        for owner, m in all_matches_log:
            ann_odoo_id = ann_odoo_ids.get(m.announcement.id)
            partner_odoo_id = get_partner_odoo_id(env, m.entry.partner_id or "")
            if ann_odoo_id and partner_odoo_id:
                is_supp = any(
                    o == owner and mm.announcement.id == m.announcement.id
                    for o, mm in suppressed
                )
                notified_at = None if is_supp or dry_run else _utcnow_str()
                odoo_writer.save_match(
                    env, ann_odoo_id, partner_odoo_id,
                    score=m.score,
                    priority=m.entry.prioritet,
                    notified_at=notified_at,
                    suppressed=is_supp,
                )

    # ── Visa supprimerade ─────────────────────────────────────────────────────
    if suppressed:
        print(f"\n--- SUPPRIMERADE (>{GRACE_DAYS} dagar innan bevakad lades till — ingen notis) ---")
        for owner, m in suppressed:
            print(f"  [{owner}] {m.summary()}")
            print(f"           publicerad: {m.announcement.publiceringsdatum}  "
                  f"bevakad tillagd: {m.entry.added_at[:10] if m.entry.added_at else '?'}")

    if show_all_matches and all_matches_log:
        print(f"\n--- ALLA TRÄFFAR ({len(all_matches_log)}) ---")
        for owner, m in all_matches_log:
            tag = "(supprimerad)" if any(o == owner and mm.announcement.id == m.announcement.id
                                         for o, mm in suppressed) else ""
            print(f"  [{owner}] {m.summary()} {tag}")

    # ── Skicka notiser ────────────────────────────────────────────────────────
    total_urgent = sum(len(v) for v in urgent_by_owner.values())
    total_digest = sum(len(v) for v in digest_by_owner.values())

    if not dry_run:
        for owner, matches in urgent_by_owner.items():
            for m in matches:
                try:
                    send_urgent(m, to_addr=owner)
                except Exception as e:
                    _log(f"{timestamp} | MAILFEL (direkt → {owner}): {e}")

        for owner, matches in digest_by_owner.items():
            if matches:
                try:
                    send_digest(matches, run_date=date_str, to_addr=owner)
                except Exception as e:
                    _log(f"{timestamp} | MAILFEL (digest → {owner}): {e}")
    elif total_urgent or total_digest:
        print(f"\n--- TORRKÖRNING: skulle ha skickat ---")
        for owner, matches in urgent_by_owner.items():
            for m in matches:
                print(f"  [DIREKT → {owner}] {m.summary()}")
        for owner, matches in digest_by_owner.items():
            for m in matches:
                print(f"  [DIGEST → {owner}] {m.summary()}")

    # ── Logg + heartbeat ──────────────────────────────────────────────────────
    total_matches = total_urgent + total_digest
    digest_sent = "ja" if total_digest and not dry_run else "nej"
    all_urgent = [m for ms in urgent_by_owner.values() for m in ms]
    urgent_names = ", ".join(
        f"{m.entry.fornamn} {m.entry.efternamn}" for m in all_urgent
    )
    log_line = (
        f"{timestamp} | "
        f"annonser: {len(all_announcements)} | "
        f"nya: {len(new_announcements)} | "
        f"träffar: {total_matches} | "
        f"supprimerade: {len(suppressed)} | "
        f"digest: {digest_sent}"
    )
    if urgent_names:
        log_line += f" | VIKTIG: {urgent_names}"
    _log(log_line)

    hb_status = "ok" if total_matches == 0 or urgent_names else "warning"
    odoo_writer.write_heartbeat(
        env, hb_status,
        items_processed=len(new_announcements),
        message=log_line[-200:],
    )

    return 0


def _utcnow_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def last_run() -> str:
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        return lines[-1] if lines else "Ingen körning registrerad"
    except FileNotFoundError:
        return "obit.log saknas — clio-agent-obit har aldrig körts"


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="clio-agent-obit — daglig dödsannonsbevakning")
    p.add_argument("--dry-run",  action="store_true",
                   help="Matcha men skicka ingen e-post")
    p.add_argument("--no-odoo", action="store_true",
                   help="Kör utan Odoo (state.db + partnerdb används)")
    p.add_argument("--last-run", action="store_true",
                   help="Visa senaste körningens loggpost och avsluta")
    p.add_argument("--backfill", metavar="FRÅN..TILL",
                   help="Skanna historiskt arkiv, t.ex. 2025-10-01..2026-01-01")
    p.add_argument("--show-all-matches", action="store_true",
                   help="Visa alla träffar inklusive supprimerade")
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
        use_odoo=not args.no_odoo,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
