"""
import_gedcom.py — Import a GEDCOM file into clio-partnerdb.

Writes partners, name claims, birth/death events, relationships, and
external_ref mappings (for idempotent re-imports). Optionally adds
watch rows for an owner.

Usage:
    python import_gedcom.py --gedcom FILE.ged --owner EMAIL [--ego "Name"] [--depth 1-3]
    python import_gedcom.py --gedcom FILE.ged --owner EMAIL --full [--limit N]
    python import_gedcom.py --gedcom FILE.ged --owner EMAIL --dry-run
    python import_gedcom.py --gedcom FILE.ged --verify "Helena Arvas"

Idempotency:
    External references are stored as (system='gedcom:FILENAME', external_id=XREF).
    Re-running the same file skips existing partners and only adds missing ones.
    Use --force to re-import all (clears previous watch rows for the owner).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from typing import Optional

try:
    from gedcom.parser import Parser
    from gedcom.element.individual import IndividualElement
    from gedcom.element.family import FamilyElement
except ImportError:
    print("Error: python-gedcom is not installed.")
    print("Install with: pip install python-gedcom")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(__file__))
import db as _db
from models import priority_to_english

MIN_BIRTH_YEAR = 1920
MAX_BIRTH_YEAR = 2010


# ── Encoding fix ──────────────────────────────────────────────────────────────

def _to_utf8_tempfile(gedcom_path: str) -> tuple[str, bool]:
    """Return (path, is_temp). If file is already UTF-8, returns original path."""
    try:
        with open(gedcom_path, encoding="utf-8-sig") as f:
            f.read()
        return gedcom_path, False
    except UnicodeDecodeError:
        pass
    for enc in ("cp1252", "latin-1"):
        try:
            with open(gedcom_path, encoding=enc) as f:
                content = f.read()
            tmp = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".ged",
                delete=False, prefix="clio_gedcom_",
            )
            tmp.write(content)
            tmp.close()
            print(f"[import_gedcom] Converted {enc} → utf-8")
            return tmp.name, True
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot read {gedcom_path} — unknown encoding")


# ── GEDCOM helpers ────────────────────────────────────────────────────────────

def _extract_birth_year(ind: IndividualElement) -> Optional[int]:
    try:
        birth_data = ind.get_birth_data()
        if birth_data and birth_data[0]:
            for part in reversed(birth_data[0].strip().split()):
                if part.isdigit() and len(part) == 4:
                    return int(part)
    except Exception:
        pass
    return None


def _extract_birth_place(ind: IndividualElement) -> Optional[str]:
    try:
        birth_data = ind.get_birth_data()
        if birth_data and len(birth_data) > 1 and birth_data[1]:
            return birth_data[1].strip() or None
    except Exception:
        pass
    return None


def _extract_death_year(ind: IndividualElement) -> Optional[int]:
    try:
        death_data = ind.get_death_data()
        if death_data and death_data[0]:
            for part in reversed(death_data[0].strip().split()):
                if part.isdigit() and len(part) == 4:
                    return int(part)
    except Exception:
        pass
    return None


def _extract_death_place(ind: IndividualElement) -> Optional[str]:
    try:
        death_data = ind.get_death_data()
        if death_data and len(death_data) > 1 and death_data[1]:
            return death_data[1].strip() or None
    except Exception:
        pass
    return None


def _is_deceased(ind: IndividualElement) -> bool:
    try:
        death_data = ind.get_death_data()
        if death_data and any(death_data):
            return True
    except Exception:
        pass
    return False


def _is_likely_alive(ind: IndividualElement) -> bool:
    if _is_deceased(ind):
        return False
    birth_year = _extract_birth_year(ind)
    if birth_year is not None:
        if birth_year < MIN_BIRTH_YEAR or birth_year > MAX_BIRTH_YEAR:
            return False
    return True


def _get_name(ind: IndividualElement) -> Optional[tuple[str, str]]:
    """Return (fornamn, efternamn) with tilltalsnamn handling, or None."""
    try:
        fornamn_raw, efternamn = ind.get_name()
        if "*" in fornamn_raw:
            fornamn = fornamn_raw.split("*")[0].strip()
        else:
            fornamn = fornamn_raw.strip().split()[0] if fornamn_raw.strip() else ""
        efternamn = efternamn.strip()
        if not fornamn or not efternamn:
            return None
        if fornamn.strip("? ") == "" or efternamn.strip("? ") == "":
            return None
        return fornamn, efternamn
    except Exception:
        return None


def _get_email_tags(ind: IndividualElement) -> list[str]:
    emails = []
    for child in ind.get_child_elements():
        if child.get_tag() in ("EMAIL", "EMAI", "_EMAIL"):
            emails.append(child.get_value().strip().lower())
    return emails


def _get_fams(ind: IndividualElement) -> list[str]:
    return [c.get_value() for c in ind.get_child_elements() if c.get_tag() == "FAMS"]


def _get_famc(ind: IndividualElement) -> list[str]:
    return [c.get_value() for c in ind.get_child_elements() if c.get_tag() == "FAMC"]


def _family_members(fam: FamilyElement, ptr_map: dict, exclude_ptr: str = "") -> dict:
    result = {"husb": None, "wife": None, "children": []}
    for child in fam.get_child_elements():
        tag = child.get_tag()
        ptr = child.get_value()
        if ptr == exclude_ptr:
            continue
        ind = ptr_map.get(ptr)
        if not isinstance(ind, IndividualElement):
            continue
        if tag == "HUSB":
            result["husb"] = ind
        elif tag == "WIFE":
            result["wife"] = ind
        elif tag == "CHIL":
            result["children"].append(ind)
    return result


# ── Ego search ────────────────────────────────────────────────────────────────

def find_ego(parser: Parser, owner_email: str,
             ego_name: Optional[str] = None) -> Optional[IndividualElement]:
    individuals = [e for e in parser.get_element_list() if isinstance(e, IndividualElement)]

    if ego_name:
        parts = ego_name.strip().lower().split()
        candidates = [
            ind for ind in individuals
            if (n := _get_name(ind)) and all(p in f"{n[0]} {n[1]}".lower() for p in parts)
        ]
        if len(candidates) == 1:
            n = _get_name(candidates[0])
            print(f"[import_gedcom] Ego: {n[0]} {n[1]} ({_extract_birth_year(candidates[0]) or '?'})")
            return candidates[0]
        elif candidates:
            return _pick_candidate(candidates, ego_name)
        print(f"[import_gedcom] No match for '{ego_name}' — falling back to full import.")
        return None

    owner_lower = owner_email.lower()
    for ind in individuals:
        if owner_lower in _get_email_tags(ind):
            n = _get_name(ind)
            print(f"[import_gedcom] Ego via email: {n[0]} {n[1] if n else '?'}")
            return ind

    local = owner_email.split("@")[0].replace(".", " ").replace("_", " ").split()[0].lower()
    candidates = [
        ind for ind in individuals
        if (n := _get_name(ind)) and n[0].lower().startswith(local)
    ]
    if not candidates:
        print(f"[import_gedcom] No match for '{local}' — falling back to full import.")
        return None
    if len(candidates) == 1:
        n = _get_name(candidates[0])
        print(f"[import_gedcom] Ego: {n[0]} {n[1]}")
        return candidates[0]
    return _pick_candidate(candidates, local)


def _pick_candidate(candidates: list, search_term: str) -> Optional[IndividualElement]:
    print(f"\n  Multiple matches for '{search_term}':\n")
    for i, ind in enumerate(candidates, 1):
        n = _get_name(ind)
        y = _extract_birth_year(ind)
        print(f"  {i:2}. {n[0]} {n[1]} ({y or '?'})")
    print("   0. Full import instead\n")
    raw = input("  Choice (number or name fragment): ").strip()
    if raw == "0":
        return None
    try:
        pick = int(raw)
        return candidates[pick - 1]
    except (ValueError, IndexError):
        pass
    raw_lower = raw.lower()
    matches = [c for c in candidates
               if raw_lower in f"{_get_name(c)[0]} {_get_name(c)[1]}".lower()]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        return _pick_candidate(matches, raw)
    return None


# ── DB write ──────────────────────────────────────────────────────────────────

def _write_individual(conn, ind: IndividualElement, source_id: str,
                      gedcom_file: str, actor: str) -> Optional[str]:
    """
    Write one GEDCOM individual to partnerdb. Returns partner_id or None.
    Idempotent via external_ref (system='gedcom:<filename>').
    """
    xref = ind.get_pointer()
    ext_system = f"gedcom:{os.path.basename(gedcom_file)}"

    partner_id, created = _db.get_or_create_partner(conn, ext_system, xref, actor)

    if not created:
        return partner_id  # Already exists — skip claims/events

    name = _get_name(ind)
    if not name:
        return partner_id

    fornamn, efternamn = name

    # Name claim
    _db.upsert_claim(
        conn, partner_id, "name",
        {"fornamn": fornamn, "efternamn": efternamn},
        source_id=source_id, actor=actor, is_primary=True,
    )

    # Birth event
    birth_year = _extract_birth_year(ind)
    birth_place = _extract_birth_place(ind)
    if birth_year or birth_place:
        _db.upsert_event(
            conn, partner_id, "birth", source_id, actor,
            date_from=str(birth_year) if birth_year else None,
            date_precision="year" if birth_year else None,
            place=birth_place,
        )

    # Death event (if deceased)
    if _is_deceased(ind):
        death_year = _extract_death_year(ind)
        death_place = _extract_death_place(ind)
        _db.upsert_event(
            conn, partner_id, "death", source_id, actor,
            date_from=str(death_year) if death_year else None,
            date_precision="year" if death_year else None,
            place=death_place,
        )

    return partner_id


def _write_relationships(conn, parser: Parser, source_id: str,
                          gedcom_file: str, actor: str, written_xrefs: set[str]) -> int:
    """Write family relationships for all already-imported individuals."""
    ext_system = f"gedcom:{os.path.basename(gedcom_file)}"
    ptr_map = parser.get_element_dictionary()
    count = 0

    def pid_for(xref: str) -> Optional[str]:
        if xref not in written_xrefs:
            return None
        row = conn.execute(
            "SELECT partner_id FROM external_ref WHERE system=? AND external_id=?",
            (ext_system, xref),
        ).fetchone()
        return row["partner_id"] if row else None

    for element in parser.get_element_list():
        if not isinstance(element, FamilyElement):
            continue
        husb_ptr = wife_ptr = None
        child_ptrs = []
        for child in element.get_child_elements():
            tag = child.get_tag()
            val = child.get_value()
            if tag == "HUSB":
                husb_ptr = val
            elif tag == "WIFE":
                wife_ptr = val
            elif tag == "CHIL":
                child_ptrs.append(val)

        husb_id = pid_for(husb_ptr) if husb_ptr else None
        wife_id = pid_for(wife_ptr) if wife_ptr else None

        if husb_id and wife_id:
            _db.upsert_relationship(conn, husb_id, wife_id, "spouse", source_id, actor)
            _db.upsert_relationship(conn, wife_id, husb_id, "spouse", source_id, actor)
            count += 2

        for child_ptr in child_ptrs:
            child_id = pid_for(child_ptr)
            if not child_id:
                continue
            if husb_id:
                _db.upsert_relationship(conn, husb_id, child_id, "parent", source_id, actor)
                _db.upsert_relationship(conn, child_id, husb_id, "child", source_id, actor)
                count += 2
            if wife_id:
                _db.upsert_relationship(conn, wife_id, child_id, "parent", source_id, actor)
                _db.upsert_relationship(conn, child_id, wife_id, "child", source_id, actor)
                count += 2

    return count


# ── Extraction strategies ─────────────────────────────────────────────────────

def _collect_ego_network(ego: IndividualElement, parser: Parser, depth: int) -> list[tuple]:
    """
    Returns list of (IndividualElement, priority_english) for ego's network.
    Priority: 'important' for depth-1 relations, 'normal' otherwise.
    """
    ptr_map = parser.get_element_dictionary()
    ego_ptr = ego.get_pointer()
    seen: set[str] = {ego_ptr}
    result: list[tuple] = []

    def add(ind: Optional[IndividualElement], priority: str):
        if ind is None:
            return
        ptr = ind.get_pointer()
        if ptr in seen:
            return
        if not _is_likely_alive(ind):
            return
        seen.add(ptr)
        result.append((ind, priority))

    partners, parents = [], []

    for fam_ptr in _get_fams(ego):
        fam = ptr_map.get(fam_ptr)
        if not isinstance(fam, FamilyElement):
            continue
        members = _family_members(fam, ptr_map, exclude_ptr=ego_ptr)
        for spouse in [members["husb"], members["wife"]]:
            if spouse:
                add(spouse, "important")
                partners.append(spouse)
        for child in members["children"]:
            add(child, "important")

    for fam_ptr in _get_famc(ego):
        fam = ptr_map.get(fam_ptr)
        if not isinstance(fam, FamilyElement):
            continue
        members = _family_members(fam, ptr_map)
        for parent in [members["husb"], members["wife"]]:
            if parent:
                add(parent, "important")
                parents.append(parent)
        siblings = [s for s in members["children"] if s.get_pointer() != ego_ptr]
        if depth >= 2:
            for sib in siblings:
                add(sib, "normal")

    if depth >= 2:
        for parent in parents:
            for fam_ptr in _get_famc(parent):
                fam = ptr_map.get(fam_ptr)
                if not isinstance(fam, FamilyElement):
                    continue
                members = _family_members(fam, ptr_map)
                for gp in [members["husb"], members["wife"]]:
                    add(gp, "normal")

    if depth >= 3:
        for fam_ptr in _get_famc(ego):
            fam = ptr_map.get(fam_ptr)
            if not isinstance(fam, FamilyElement):
                continue
            siblings = [s for s in _family_members(fam, ptr_map)["children"]
                        if s.get_pointer() != ego_ptr]
            for sib in siblings:
                for sib_fam_ptr in _get_fams(sib):
                    sib_fam = ptr_map.get(sib_fam_ptr)
                    if isinstance(sib_fam, FamilyElement):
                        for child in _family_members(sib_fam, ptr_map)["children"]:
                            add(child, "normal")
        for parent in parents:
            for fam_ptr in _get_famc(parent):
                fam = ptr_map.get(fam_ptr)
                if not isinstance(fam, FamilyElement):
                    continue
                for aunt_uncle in _family_members(fam, ptr_map)["children"]:
                    if aunt_uncle.get_pointer() != parent.get_pointer():
                        add(aunt_uncle, "normal")

    return result


def _collect_full(parser: Parser) -> list[tuple]:
    """All likely-alive individuals, all priority 'normal'."""
    return [
        (ind, "normal")
        for ind in parser.get_element_list()
        if isinstance(ind, IndividualElement) and _is_likely_alive(ind)
    ]


def _collect_family_context(watch_individuals: list[tuple], parser: Parser) -> set:
    """
    Return a set of all GEDCOM xrefs for individuals that appear in any family
    where a watch-list member also appears. Includes deceased members.

    Purpose: ensure relationship endpoints exist in partnerdb even when one end
    is deceased (e.g. Helena Thustrup as Fredrik's mother). Without this,
    parent/child relationships cannot be written.
    """
    ptr_map = parser.get_element_dictionary()
    watch_ptrs = {ind.get_pointer() for ind, _ in watch_individuals}
    context_ptrs: set[str] = set()

    for element in parser.get_element_list():
        if not isinstance(element, FamilyElement):
            continue
        # Collect all member pointers in this family
        husb_ptr = wife_ptr = None
        child_ptrs = []
        for child in element.get_child_elements():
            tag, val = child.get_tag(), child.get_value()
            if tag == "HUSB":
                husb_ptr = val
            elif tag == "WIFE":
                wife_ptr = val
            elif tag == "CHIL":
                child_ptrs.append(val)

        all_in_family = [p for p in [husb_ptr, wife_ptr] + child_ptrs if p]
        # If any watch member is in this family, add ALL family members as context
        if any(p in watch_ptrs for p in all_in_family):
            for p in all_in_family:
                if p not in watch_ptrs:
                    context_ptrs.add(p)

    return context_ptrs


# ── Main import ───────────────────────────────────────────────────────────────

def run_import(gedcom_path: str, owner_email: str, depth: int = 1,
               ego_name: Optional[str] = None, full: bool = False,
               limit: Optional[int] = None, dry_run: bool = False,
               db_path: Optional[str] = None) -> int:
    """
    Import GEDCOM into partnerdb. Returns number of watch entries added.

    Two-pass strategy:
      Pass 1: Write ALL individuals to partnerdb (watch members + family context,
              including deceased). This ensures relationship endpoints exist in DB.
      Pass 2: Add watch rows only for living watch-list members.

    Deceased family members (e.g. a parent) are stored in partnerdb with their
    death event but are never added to the watch list.
    """
    actual_path, is_temp = _to_utf8_tempfile(gedcom_path)
    parser = Parser()
    parser.parse_file(actual_path, strict=False)
    if is_temp:
        os.unlink(actual_path)

    if full:
        watch_individuals = _collect_full(parser)
        default_limit = 10
    else:
        ego = find_ego(parser, owner_email, ego_name=ego_name)
        if ego is None:
            print("[import_gedcom] No ego found — falling back to full import.")
            watch_individuals = _collect_full(parser)
            default_limit = 10
        else:
            watch_individuals = _collect_ego_network(ego, parser, depth)
            default_limit = None

    actual_limit = limit if limit is not None else default_limit
    if actual_limit and actual_limit > 0 and len(watch_individuals) > actual_limit:
        print(f"[import_gedcom] Limiting to {actual_limit} of {len(watch_individuals)} (--limit {actual_limit})")
        watch_individuals = watch_individuals[:actual_limit]

    if dry_run:
        print(f"\n--- DRY RUN: {len(watch_individuals)} watch individuals ---")
        for ind, priority in watch_individuals:
            n = _get_name(ind)
            y = _extract_birth_year(ind)
            name_str = f"{n[0]} {n[1]}" if n else "(no name)"
            print(f"  {priority:12}  {name_str} ({y or '?'})")
        return len(watch_individuals)

    conn = _db.connect(db_path)
    source_id = _db.insert_source(
        conn, "gedcom", os.path.basename(gedcom_path), actor=owner_email,
    )

    ptr_map = parser.get_element_dictionary()

    # ── Pass 1: Write all individuals to DB (watch + context, including deceased) ──
    written_xrefs: set[str] = set()

    # Watch members first
    watch_ptr_to_priority: dict[str, str] = {}
    for ind, priority in watch_individuals:
        partner_id = _write_individual(conn, ind, source_id, gedcom_path, actor=owner_email)
        if partner_id:
            written_xrefs.add(ind.get_pointer())
            watch_ptr_to_priority[ind.get_pointer()] = priority

    # Context individuals (family members not in watch list, including deceased)
    context_ptrs = _collect_family_context(watch_individuals, parser)
    context_written = 0
    for xref in context_ptrs:
        ind = ptr_map.get(xref)
        if not isinstance(ind, IndividualElement):
            continue
        partner_id = _write_individual(conn, ind, source_id, gedcom_path, actor=owner_email)
        if partner_id:
            written_xrefs.add(xref)
            context_written += 1

    if context_written:
        print(f"[import_gedcom] Also wrote {context_written} context individuals (family members, may include deceased)")

    # ── Pass 2: Add watch rows only for living watch members ──
    added = 0
    skipped = 0
    ext_system = f"gedcom:{os.path.basename(gedcom_path)}"

    for xref, priority in watch_ptr_to_priority.items():
        row = conn.execute(
            "SELECT partner_id FROM external_ref WHERE system=? AND external_id=?",
            (ext_system, xref),
        ).fetchone()
        if not row:
            continue
        partner_id = row["partner_id"]
        was_new = _db.upsert_watch(
            conn, owner_email, partner_id, priority,
            source="gedcom", actor=owner_email,
        )
        if was_new:
            added += 1
        else:
            skipped += 1

    # ── Relationships ──
    rel_count = _write_relationships(conn, parser, source_id, gedcom_path,
                                      actor=owner_email, written_xrefs=written_xrefs)

    print(f"[import_gedcom] Done. {added} new watch entries, {skipped} already existed, "
          f"{rel_count} relationships written.")
    return added


# ── Verify (--verify) ─────────────────────────────────────────────────────────

def verify_partner(query: str, db_path: Optional[str] = None) -> None:
    """Print everything known about partners matching the query."""
    import unicodedata

    def norm(s: str) -> str:
        s = s.strip().lower()
        nfd = unicodedata.normalize("NFD", s)
        return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

    conn = _db.connect(db_path)
    parts = query.strip().lower().split()

    # Find matching partners via name claims
    all_claims = conn.execute(
        "SELECT partner_id, value FROM claim WHERE predicate='name'"
    ).fetchall()

    matches = []
    for row in all_claims:
        try:
            v = json.loads(row["value"])
            full = norm(f"{v.get('fornamn','')} {v.get('efternamn','')}")
            if all(p in full for p in [norm(p) for p in parts]):
                matches.append(row["partner_id"])
        except Exception:
            pass

    if not matches:
        print(f"No partners found matching '{query}'")
        return

    for pid in dict.fromkeys(matches):  # deduplicate preserving order
        info = _db.partner_full_info(conn, pid)
        if not info:
            continue
        print(f"\n{'='*60}")
        print(f"Partner ID : {pid}")
        print(f"Created    : {info['partner']['created_at']}")
        print(f"Editors    : {info['partner']['editors']}")

        print(f"\nClaims ({len(info['claims'])}):")
        for c in sorted(info["claims"], key=lambda x: (x["predicate"], -x["is_primary"])):
            primary = " [primary]" if c["is_primary"] else ""
            vf = f"  {c['valid_from']}→{c['valid_to']}" if c["valid_from"] else ""
            print(f"  {c['predicate']:15} {c['value']}{primary}{vf}")

        print(f"\nEvents ({len(info['events'])}):")
        for e in info["events"]:
            place = f" @ {e['place']}" if e["place"] else ""
            print(f"  {e['type']:12} {e['date_from'] or '?'}{place}")

        rels = info["relationships_from"]
        if rels:
            print(f"\nRelationships ({len(rels)}):")
            for r in sorted(rels, key=lambda x: (x["type"], x["to_id"])):
                other_names = _db.get_partner_names(conn, r["to_id"])
                other_name = (f"{other_names[0].get('fornamn','')} {other_names[0].get('efternamn','')}"
                              if other_names else r["to_id"][:8])
                print(f"  {r['type']:15} {other_name}")

        if info["external_refs"]:
            print(f"\nExternal refs:")
            for r in info["external_refs"]:
                print(f"  {r['system']:30} {r['external_id']}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Import a GEDCOM file into clio-partnerdb",
    )
    p.add_argument("--gedcom",   help="Path to .ged file")
    p.add_argument("--owner",    help="Owner email (e.g. fredrik@arvas.se)")
    p.add_argument("--depth",    type=int, default=1, choices=[1, 2, 3],
                   help="Relationship depth 1-3 (default: 1)")
    p.add_argument("--ego",      default=None,
                   help="Ego person name, e.g. 'Fredrik Arvas'")
    p.add_argument("--limit",    type=int, default=None,
                   help="Max entries to import (0 = unlimited)")
    p.add_argument("--full",     action="store_true",
                   help="Import all likely-alive individuals (default limit 10)")
    p.add_argument("--dry-run",  action="store_true",
                   help="Preview without writing to DB")
    p.add_argument("--verify",   default=None, metavar="NAME",
                   help="Print everything known about matching partners and exit")
    p.add_argument("--db",       default=None, metavar="PATH",
                   help="Override DB path (default: ~/.clio/partnerdb.sqlite)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.verify:
        verify_partner(args.verify, db_path=args.db)
        return

    if not args.gedcom:
        print("Error: --gedcom is required (or use --verify NAME)")
        sys.exit(1)
    if not args.owner:
        print("Error: --owner is required")
        sys.exit(1)

    run_import(
        gedcom_path=args.gedcom,
        owner_email=args.owner,
        depth=args.depth,
        ego_name=args.ego,
        full=args.full,
        limit=args.limit if args.limit != 0 else None,
        dry_run=args.dry_run,
        db_path=args.db,
    )


if __name__ == "__main__":
    main()
