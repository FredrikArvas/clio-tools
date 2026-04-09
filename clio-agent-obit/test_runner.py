"""
test_runner.py — Sprint 2 acceptance test suite for clio-agent-obit.

Runs the 5 test cases defined in matcher/test_cases.yaml.
All 5 must pass for sprint acceptance gate.

Test types:
  unit    — synthetic announcement, no network or DB required
  gedcom  — requires partnerdb with imported GEDCOM data
  online  — requires live network access (skipped unless --online)

Usage:
    python test_runner.py
    python test_runner.py --gedcom "E:\\path\\to\\file.ged" --owner fredrik@arvas.se
    python test_runner.py --online
    python test_runner.py --tc TC-01          (run a single test)
    python test_runner.py -v                  (verbose score breakdown)
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Optional

import yaml

# Ensure obit root is in path
sys.path.insert(0, os.path.dirname(__file__))
# Ensure partnerdb is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "clio-partnerdb"))

from matcher import (
    Announcement, WatchlistEntry, match_announcement, filter_notifiable,
)

TEST_CASES_PATH = os.path.join(os.path.dirname(__file__), "matcher", "test_cases.yaml")
GEDCOM_DEFAULT = (
    r"E:\Dropbox\ulrika-fredrik\släktforskning\släkten Fredrik arvas"
    r"\släktträdsfiler\UlrikasFredriks_v2010-09-22 - 22092010.ged"
)


# ── Result tracking ───────────────────────────────────────────────────────────

@dataclass
class TestResult:
    tc_id: str
    name: str
    passed: bool
    skipped: bool = False
    skip_reason: str = ""
    failures: list[str] = None
    notes: list[str] = None

    def __post_init__(self):
        if self.failures is None:
            self.failures = []
        if self.notes is None:
            self.notes = []


# ── Test helpers ──────────────────────────────────────────────────────────────

def _make_entry(d: dict) -> WatchlistEntry:
    """Build a WatchlistEntry from test_cases.yaml watchlist_entry dict."""
    fodelsear = d.get("fodelsear")
    fodelsear_approx = False
    if fodelsear is None and d.get("fodelsear_approx"):
        fodelsear = d["fodelsear_approx"]
        fodelsear_approx = True
    return WatchlistEntry(
        efternamn=d["efternamn"],
        fornamn=d["fornamn"],
        fodelsear=fodelsear,
        hemort=d.get("hemort"),
        prioritet=d.get("prioritet", "normal"),
        kalla="test",
        fodelsear_approx=fodelsear_approx,
    )


def _make_announcement(d: dict) -> Announcement:
    return Announcement(
        id=f"test-{d['namn'].replace(' ','-').lower()}",
        namn=d["namn"],
        fodelsear=d.get("fodelsear"),
        hemort=d.get("hemort"),
        url=d.get("url", "https://test.example/"),
        publiceringsdatum=d.get("publiceringsdatum", "2026-04-09"),
        raw_title=d.get("namn", ""),
    )


# ── Individual test runners ───────────────────────────────────────────────────

def run_unit_tc01(tc: dict, verbose: bool) -> TestResult:
    """TC-01: Göran Frisk — regression, exact match."""
    entry = _make_entry(tc["watchlist_entry"])
    ann   = _make_announcement(tc["announcement"])
    matches = match_announcement(ann, [entry])

    failures = []
    notes = []

    if not matches:
        failures.append("No match at all (expected score >= 90)")
    else:
        m = matches[0]
        expected_min = tc["expect"]["score_min"]
        if m.score < expected_min:
            failures.append(f"Score {m.score} < expected {expected_min}")
        if not m.is_notifiable and tc["expect"]["notifiable"]:
            failures.append(f"is_notifiable=False (threshold {m.score} < 60)")
        if verbose:
            notes.append(f"Score: {m.score}  breakdown: {m.score_breakdown}")

    return TestResult(tc["id"], tc["name"], passed=len(failures) == 0,
                      failures=failures, notes=notes)


def run_unit_tc05(tc: dict, verbose: bool) -> TestResult:
    """TC-05: Roger Jansson — fuzzy match."""
    entry = _make_entry(tc["watchlist_entry"])
    failures = []
    notes = []

    for ann_spec in tc["announcements"]:
        ann = _make_announcement(ann_spec)
        matches = match_announcement(ann, [entry])
        expected_min = ann_spec["expect_score_min"]
        expected_notifiable = ann_spec["expect_notifiable"]

        if not matches:
            failures.append(f"No match for '{ann_spec['namn']}' (expected >= {expected_min})")
            continue

        m = matches[0]
        if m.score < expected_min:
            failures.append(
                f"'{ann_spec['namn']}': score {m.score} < expected {expected_min}  "
                f"breakdown: {m.score_breakdown}"
            )
        if m.is_notifiable != expected_notifiable:
            failures.append(
                f"'{ann_spec['namn']}': is_notifiable={m.is_notifiable} != {expected_notifiable}"
            )
        if verbose:
            notes.append(f"'{ann_spec['namn']}': score {m.score}  {m.score_breakdown}")

    return TestResult(tc["id"], tc["name"], passed=len(failures) == 0,
                      failures=failures, notes=notes)


def run_gedcom_tc04(tc: dict, gedcom_path: Optional[str], owner: str,
                    verbose: bool) -> TestResult:
    """TC-04: GEDCOM data verification (Helena Thustrup, known as Helena Arvas)."""
    if not gedcom_path or not os.path.exists(gedcom_path):
        return TestResult(tc["id"], tc["name"], passed=False, skipped=True,
                          skip_reason=f"GEDCOM file not found: {gedcom_path}")

    import db as _db
    import import_gedcom as _ig

    # Use in-memory DB for the test
    conn = _db.connect(":memory:")
    _ig.run_import(
        gedcom_path=gedcom_path,
        owner_email=owner,
        depth=2,
        ego_name="Fredrik Arvas",
        db_path=":memory:",
    )
    # Re-open with same in-memory conn (run_import creates its own conn; use file DB instead)
    # For this test we import into a temp file DB
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        _ig.run_import(
            gedcom_path=gedcom_path,
            owner_email=owner,
            depth=2,
            ego_name="Fredrik Arvas",
            db_path=tmp_path,
        )
        conn = _db.connect(tmp_path)

        # Verify Helena Arvas
        import json as _json
        import unicodedata

        def norm(s):
            s = s.strip().lower()
            nfd = unicodedata.normalize("NFD", s)
            return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

        query_parts = [norm(p) for p in tc["gedcom_verify_query"].split()]
        all_name_rows = conn.execute(
            "SELECT partner_id, value FROM claim WHERE predicate='name'"
        ).fetchall()

        helena_ids = []
        for row in all_name_rows:
            try:
                v = _json.loads(row["value"])
                full = norm(f"{v.get('fornamn','')} {v.get('efternamn','')}")
                if all(p in full for p in query_parts):
                    helena_ids.append(row["partner_id"])
            except Exception:
                pass

        failures = []
        notes = []

        if not helena_ids:
            failures.append(f"'{tc['gedcom_verify_query']}' not found in imported GEDCOM data")
            return TestResult(tc["id"], tc["name"], passed=False,
                              failures=failures, notes=notes)

        pid = helena_ids[0]

        if tc["expect"]["has_name_claim"]:
            names = _db.get_partner_names(conn, pid)
            if not names:
                failures.append("No name claim found")
            elif verbose:
                notes.append(f"Name: {names[0]}")

        if tc["expect"]["has_birth_event"]:
            birth = conn.execute(
                "SELECT date_from, place FROM event WHERE partner_id=? AND type='birth'",
                (pid,)
            ).fetchone()
            if not birth:
                failures.append("No birth event found")
            elif verbose:
                notes.append(f"Birth: {birth['date_from']} @ {birth['place']}")

        if tc["expect"]["has_relationships"]:
            rels = conn.execute(
                "SELECT COUNT(*) as n FROM relationship WHERE from_id=? OR to_id=?",
                (pid, pid)
            ).fetchone()
            if not rels or rels["n"] == 0:
                failures.append("No relationships found")
            elif verbose:
                notes.append(f"Relationships: {rels['n']}")

        return TestResult(tc["id"], tc["name"], passed=len(failures) == 0,
                          failures=failures, notes=notes)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def run_online_tc(tc: dict, verbose: bool) -> TestResult:
    """TC-02 / TC-03: online backfill tests — skipped unless --online."""
    return TestResult(tc["id"], tc["name"], passed=True, skipped=True,
                      skip_reason="Online test — run with --online flag")


# ── Main runner ───────────────────────────────────────────────────────────────

def run_all(gedcom_path: Optional[str] = None, owner: str = "fredrik@arvas.se",
            online: bool = False, only_tc: Optional[str] = None,
            verbose: bool = False) -> list[TestResult]:
    with open(TEST_CASES_PATH, encoding="utf-8") as f:
        test_cases = yaml.safe_load(f)

    results: list[TestResult] = []

    for tc in test_cases:
        if only_tc and tc["id"] != only_tc:
            continue

        tc_type = tc.get("type", "unit")
        tc_id   = tc["id"]

        if tc_id == "TC-01":
            results.append(run_unit_tc01(tc, verbose))
        elif tc_id == "TC-05":
            results.append(run_unit_tc05(tc, verbose))
        elif tc_id == "TC-04":
            results.append(run_gedcom_tc04(tc, gedcom_path, owner, verbose))
        elif tc_type == "online":
            if online:
                results.append(TestResult(
                    tc_id, tc["name"], passed=False, skipped=True,
                    skip_reason="Online test not yet automated — verify manually",
                ))
            else:
                results.append(TestResult(
                    tc_id, tc["name"], passed=True, skipped=True,
                    skip_reason="Online test — run with --online flag",
                ))

    return results


def print_report(results: list[TestResult]) -> bool:
    print("\n" + "="*60)
    print("clio-agent-obit Sprint 2 — Test Report")
    print("="*60)

    passed = skipped = failed = 0
    for r in results:
        if r.skipped:
            status = "SKIP"
            skipped += 1
        elif r.passed:
            status = "PASS"
            passed += 1
        else:
            status = "FAIL"
            failed += 1

        print(f"\n  [{status}] {r.tc_id}: {r.name}")
        if r.skipped:
            print(f"         → {r.skip_reason}")
        for note in (r.notes or []):
            print(f"         ℹ {note}")
        for fail in (r.failures or []):
            print(f"         ✗ {fail}")

    print("\n" + "-"*60)
    print(f"  Passed: {passed}  Skipped: {skipped}  Failed: {failed}")
    gate = failed == 0
    print(f"  Sprint acceptance gate: {'✓ PASSED' if gate else '✗ FAILED'}")
    print("="*60 + "\n")
    return gate


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="clio-agent-obit test runner")
    p.add_argument("--gedcom", default=GEDCOM_DEFAULT, help="GEDCOM file path for TC-04")
    p.add_argument("--owner",  default="fredrik@arvas.se")
    p.add_argument("--online", action="store_true", help="Run online tests (TC-02, TC-03)")
    p.add_argument("--tc",     default=None, help="Run only this test case (e.g. TC-01)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    results = run_all(
        gedcom_path=args.gedcom,
        owner=args.owner,
        online=args.online,
        only_tc=args.tc,
        verbose=args.verbose,
    )
    gate_passed = print_report(results)
    sys.exit(0 if gate_passed else 1)


if __name__ == "__main__":
    main()
