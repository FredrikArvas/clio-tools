"""
watchlist/import_email.py — Import a returned watch-list (CSV or XLSX) into partnerdb.

Called by clio-agent-mail when a [clio-obit] reply arrives with a CSV or XLSX attachment.
clio-agent-obit owns this logic; clio-agent-mail only triggers it.

Security: sender must be in obit_import.whitelist (config.yaml).
          clio-agent-mail's own whitelist is a separate, independent layer.

Usage:
    python import_email.py --csv /tmp/ulrika.xlsx --owner ulrika@arvas.se
    python import_email.py --csv /tmp/ulrika.csv  --owner ulrika@arvas.se --dry-run

Returns (stdout):
    A receipt text suitable for sending back to the owner.
    Exit 0 = OK, exit 1 = rejected (not whitelisted or bad file).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

# Paths
_OBIT_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARTNERDB    = os.path.join(_OBIT_DIR, "..", "clio-partnerdb")
sys.path.insert(0, _OBIT_DIR)
sys.path.insert(0, _PARTNERDB)

import yaml
import db as _partnerdb
from watchlist.loader import load_watchlist, load_watchlist_from_db


# ── Config helpers ────────────────────────────────────────────────────────────

def _load_config() -> dict:
    path = os.path.join(_OBIT_DIR, "config.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_whitelist(cfg: dict) -> set[str]:
    raw = cfg.get("obit_import", {}).get("whitelist", [])
    return {addr.strip().lower() for addr in raw}


# ── Import logic ──────────────────────────────────────────────────────────────

def import_from_csv(csv_path: str, owner_email: str,
                    dry_run: bool = False) -> tuple[int, int, list[str]]:
    """
    Import entries from csv_path into partnerdb for owner_email.
    Returns (added, skipped, warnings).
    """
    from watchlist.loader import load_watchlist
    from models import priority_to_english
    import db as _db

    entries = load_watchlist(csv_path)
    if not entries:
        return 0, 0, ["CSV is empty or could not be parsed."]

    conn = _db.connect()
    source_id = _db.insert_source(conn, "csv_import",
                                   os.path.basename(csv_path),
                                   actor=owner_email)
    import uuid as _uuid, json as _json

    added = 0
    skipped = 0
    warnings = []

    for entry in entries:
        fornamn   = entry.fornamn
        efternamn = entry.efternamn

        if not fornamn or not efternamn:
            warnings.append(f"Skipped row with missing name")
            continue

        # Find or create partner (conservative: name match only, no auto-merge)
        existing = conn.execute(
            """SELECT c.partner_id FROM claim c
               WHERE c.predicate='name'
               AND json_extract(c.value, '$.fornamn') = ?
               AND json_extract(c.value, '$.efternamn') = ?
               LIMIT 1""",
            (fornamn, efternamn),
        ).fetchone()

        if existing:
            pid = existing["partner_id"]
        else:
            pid = str(_uuid.uuid4())
            ts  = _db.now_iso()
            partner_row = {
                "id": pid, "created_at": ts,
                "editors": _json.dumps([owner_email]),
                "is_person": 1, "is_org": 0,
            }
            with conn:
                conn.execute(
                    "INSERT INTO partner (id, created_at, editors, is_person, is_org) VALUES (?,?,?,?,?)",
                    (pid, ts, partner_row["editors"], 1, 0),
                )
                _db.audit(conn, "partner", {"id": pid}, "insert",
                          after=partner_row, actor=owner_email,
                          reason=f"import_email from {owner_email}")
            _db.upsert_claim(conn, pid, "name",
                             {"fornamn": fornamn, "efternamn": efternamn},
                             source_id=source_id, actor=owner_email, is_primary=True)
            if entry.fodelsear:
                _db.upsert_event(conn, pid, "birth", source_id, owner_email,
                                 date_from=str(entry.fodelsear), date_precision="year")
            if entry.hemort:
                _db.upsert_claim(conn, pid, "city", entry.hemort,
                                 source_id=source_id, actor=owner_email, is_primary=True)

        priority_en = priority_to_english(entry.prioritet)
        was_new = _db.upsert_watch(conn, owner_email, pid, priority_en,
                                    source="invitation", actor=owner_email)
        if was_new:
            added += 1
        else:
            skipped += 1

    return added, skipped, warnings


# ── Receipt text ──────────────────────────────────────────────────────────────

def _receipt(owner_email: str, added: int, skipped: int,
             warnings: list[str]) -> str:
    lines = [
        f"Bevakningslista importerad — {added} poster tillagda",
        "",
        f"  Tillagda:   {added}",
        f"  Redan fanns: {skipped}",
    ]
    if warnings:
        lines.append(f"  Varningar:  {len(warnings)}")
        for w in warnings[:5]:
            lines.append(f"    - {w}")
        if len(warnings) > 5:
            lines.append(f"    … och {len(warnings)-5} till")
    lines += [
        "",
        "Bevakningen är nu aktiv. Du får ett mail när en träff hittas.",
        "Dina poster bevakas vid nästa körning (morgon).",
        "",
        "— clio-agent-obit",
    ]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(csv_path: str, owner_email: str,
        dry_run: bool = False) -> tuple[bool, str]:
    """
    Validate, import, and return (success, receipt_text).
    receipt_text is suitable for sending back to owner_email.
    """
    cfg       = _load_config()
    whitelist = _get_whitelist(cfg)
    owner_lower = owner_email.strip().lower()

    if owner_lower not in whitelist:
        msg = (
            f"Import rejected: {owner_email} is not in obit_import.whitelist.\n"
            f"Ask Fredrik to add your address to config.yaml."
        )
        return False, msg

    if not os.path.exists(csv_path):
        return False, f"File not found: {csv_path}"

    if dry_run:
        entries = load_watchlist(csv_path)
        lines = [f"DRY RUN — {len(entries)} entries found in {os.path.basename(csv_path)}:"]
        for e in entries[:20]:
            lines.append(f"  {e.prioritet:12} {e.fornamn} {e.efternamn} ({e.fodelsear or '?'})")
        if len(entries) > 20:
            lines.append(f"  … and {len(entries)-20} more")
        return True, "\n".join(lines)

    added, skipped, warnings = import_from_csv(csv_path, owner_lower)
    receipt = _receipt(owner_lower, added, skipped, warnings)
    return True, receipt


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Import a returned [clio-obit] CSV or XLSX attachment into partnerdb"
    )
    p.add_argument("--csv",   required=True,
                   help="Path to attachment (.csv or .xlsx)")
    p.add_argument("--owner", required=True, help="Sender email (watch list owner)")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    success, text = run(args.csv, args.owner, dry_run=args.dry_run)
    print(text)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
