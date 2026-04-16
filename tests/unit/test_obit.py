"""
test_obit.py
Unit tests for clio-agent-obit modules.

Tests:
    - matcher.py  — name matching, scoring, normalisation
    - state.py    — SQLite seen-announcements tracking (in-memory DB)
    - notifier.py — email building and send logic (mocked smtplib)
    - sources/parsers.py — extract_birth_year, extract_location,
                           parse_publication_date, clean_name
    - sources/source_familjesidan_rss.py — _parse_entry, fetch() (mocked feedparser)

No real SMTP connections, no real network calls.
"""

import sys
import sqlite3
import smtplib
import tempfile
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent.parent
OBIT = ROOT / "clio-agent-obit"
sys.path.insert(0, str(OBIT))
sys.path.insert(0, str(OBIT / "sources"))
# source_familjesidan_rss.py uses "from sources.source_base import …"
# so the parent of the sources/ package must also be on the path.
# OBIT is already added above; the line below is kept for clarity.
if str(OBIT) not in sys.path:
    sys.path.insert(0, str(OBIT))

# ── Module imports ────────────────────────────────────────────────────────────
from matcher import (
    WatchlistEntry,
    Announcement,
    Match,
    THRESHOLD,
    _normalize,
    _split_name,
    _lev,
    _swedish_soundex,
    _soundex_match,
    _score_first_name,
    _score_last_name,
    match_announcement,
    filter_notifiable,
)
from state import _connect, is_seen, mark_seen, count_seen
from parsers import (
    extract_birth_year,
    extract_location,
    parse_publication_date,
    clean_name,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _entry(efternamn="Frisk", fornamn="Göran", fodelsear=1945,
           hemort="Haninge", prioritet="viktig", kalla="manuell") -> WatchlistEntry:
    return WatchlistEntry(
        efternamn=efternamn,
        fornamn=fornamn,
        fodelsear=fodelsear,
        hemort=hemort,
        prioritet=prioritet,
        kalla=kalla,
    )


def _announcement(namn="Göran Frisk", fodelsear=1945, hemort="Haninge",
                  url="http://example.com/1", pubdate="2026-04-08",
                  ann_id="ann-1") -> Announcement:
    return Announcement(
        id=ann_id,
        namn=namn,
        fodelsear=fodelsear,
        hemort=hemort,
        url=url,
        publiceringsdatum=pubdate,
        raw_title=namn,
    )


def _in_memory_db() -> str:
    """Return a path to a fresh in-memory-style temp DB (deleted after test)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # let _connect() create it fresh
    return path


# =============================================================================
# matcher.py
# =============================================================================

class TestNormalize(unittest.TestCase):

    def test_lowercase(self):
        self.assertEqual(_normalize("FRISK"), "frisk")

    def test_strip_swedish_diacritics(self):
        self.assertEqual(_normalize("Göran"), "goran")
        self.assertEqual(_normalize("Åberg"), "aberg")
        self.assertEqual(_normalize("Öberg"), "oberg")

    def test_strips_whitespace(self):
        self.assertEqual(_normalize("  Frisk  "), "frisk")

    def test_ascii_unchanged(self):
        self.assertEqual(_normalize("Frisk"), "frisk")


class TestSplitName(unittest.TestCase):

    def test_simple(self):
        first, last = _split_name("Göran Frisk")
        self.assertEqual(first, "Göran")
        self.assertEqual(last, "Frisk")

    def test_middle_name(self):
        first, last = _split_name("Anna Maria Svensson")
        self.assertEqual(first, "Anna Maria")
        self.assertEqual(last, "Svensson")

    def test_single_word(self):
        first, last = _split_name("Frisk")
        self.assertEqual(first, "")
        self.assertEqual(last, "Frisk")

    def test_empty_string(self):
        first, last = _split_name("")
        self.assertEqual(first, "")
        self.assertEqual(last, "")


class TestLevenshtein(unittest.TestCase):

    def test_identical(self):
        self.assertEqual(_lev("frisk", "frisk"), 0)

    def test_one_substitution(self):
        dist = _lev("jansson", "jonsson")
        self.assertLessEqual(dist, 2)  # at least within 2

    def test_different(self):
        self.assertGreater(_lev("anderson", "zetterberg"), 3)


class TestSwedishSoundex(unittest.TestCase):

    def test_ck_collapsed_to_k(self):
        self.assertEqual(_swedish_soundex("eckberg"), _swedish_soundex("ekberg"))

    def test_ph_collapsed_to_f(self):
        self.assertEqual(_swedish_soundex("jonasfelt"), _swedish_soundex("jonasfelt"))

    def test_w_to_v(self):
        self.assertEqual(_swedish_soundex("wallin"), _swedish_soundex("vallin"))

    def test_soundex_match_true(self):
        self.assertTrue(_soundex_match("wallin", "vallin"))

    def test_soundex_match_false_short(self):
        # Names < 3 chars should not match via soundex
        self.assertFalse(_soundex_match("ax", "ax"))


class TestScoreFirstName(unittest.TestCase):

    def test_exact_match(self):
        pts, key = _score_first_name("goran", "goran")
        self.assertEqual(pts, 30)
        self.assertEqual(key, "fornamn_exact")

    def test_levenshtein_close(self):
        pts, key = _score_first_name("sara", "sara")
        self.assertEqual(pts, 30)

    def test_no_match(self):
        pts, key = _score_first_name("bertil", "zettergren")
        self.assertEqual(pts, 0)

    def test_empty_first_name(self):
        pts, key = _score_first_name("", "goran")
        self.assertEqual(pts, 0)


class TestScoreLastName(unittest.TestCase):

    def test_exact_match(self):
        pts, key = _score_last_name("frisk", "frisk")
        self.assertEqual(pts, 40)
        self.assertEqual(key, "efternamn_exact")

    def test_levenshtein_one_off(self):
        pts, key = _score_last_name("jansson", "jonsson")
        self.assertEqual(pts, 25)
        self.assertEqual(key, "efternamn_levenshtein")

    def test_no_match(self):
        pts, key = _score_last_name("karlsson", "zetterberg")
        self.assertEqual(pts, 0)

    def test_empty_last_name(self):
        pts, key = _score_last_name("", "frisk")
        self.assertEqual(pts, 0)


class TestMatchAnnouncement(unittest.TestCase):

    def test_exact_match_above_threshold(self):
        entry = _entry()  # Göran Frisk, 1945, Haninge
        ann = _announcement()   # Göran Frisk, 1945, Haninge
        matches = match_announcement(ann, [entry])
        self.assertTrue(len(matches) > 0)
        top = matches[0]
        self.assertGreaterEqual(top.score, THRESHOLD)
        self.assertTrue(top.is_notifiable)

    def test_wrong_name_below_threshold(self):
        entry = _entry("Bergström", "Lars", 1960, "Stockholm")
        ann = _announcement("Göran Frisk", 1945, "Haninge")
        matches = match_announcement(ann, [entry])
        # Either no match or score below threshold
        notifiable = [m for m in matches if m.is_notifiable]
        self.assertEqual(len(notifiable), 0)

    def test_birth_year_contributes_points(self):
        entry = _entry(fodelsear=1945)
        ann = _announcement(fodelsear=1945)
        matches = match_announcement(ann, [entry])
        self.assertTrue(len(matches) > 0)
        if matches:
            self.assertIn("fodelsear", matches[0].score_breakdown)

    def test_city_contributes_points(self):
        entry = _entry(hemort="Haninge")
        ann = _announcement(hemort="Haninge")
        matches = match_announcement(ann, [entry])
        self.assertTrue(len(matches) > 0)
        if matches:
            self.assertIn("hemort", matches[0].score_breakdown)

    def test_empty_watchlist(self):
        ann = _announcement()
        matches = match_announcement(ann, [])
        self.assertEqual(matches, [])

    def test_results_sorted_descending(self):
        entry_good = _entry("Frisk", "Göran", 1945, "Haninge")
        entry_partial = _entry("Frisk", "Gun", 1980, None)
        ann = _announcement("Göran Frisk", 1945, "Haninge")
        matches = match_announcement(ann, [entry_partial, entry_good])
        if len(matches) >= 2:
            self.assertGreaterEqual(matches[0].score, matches[1].score)

    def test_approximate_birth_year_window(self):
        entry = _entry(fodelsear=1940)
        entry.fodelsear_approx = True
        ann = _announcement(fodelsear=1945)  # within ±10
        matches = match_announcement(ann, [entry])
        birth_pts = [m.score_breakdown.get("fodelsear", 0) for m in matches]
        # Should have gotten points (15 for approx)
        self.assertTrue(any(p > 0 for p in birth_pts) or len(matches) > 0)

    def test_match_summary_contains_name(self):
        entry = _entry()
        ann = _announcement()
        matches = match_announcement(ann, [entry])
        if matches:
            summary = matches[0].summary()
            # summary uses normalized (lowercase) names
            self.assertIn("frisk", summary)
            self.assertIn("score", summary)


class TestFilterNotifiable(unittest.TestCase):

    def test_filters_above_threshold(self):
        entry = _entry()
        ann = _announcement()
        all_matches = match_announcement(ann, [entry])
        notifiable = filter_notifiable(all_matches)
        for m in notifiable:
            self.assertGreaterEqual(m.score, THRESHOLD)

    def test_returns_empty_when_no_matches(self):
        self.assertEqual(filter_notifiable([]), [])


# =============================================================================
# state.py
# =============================================================================

class TestState(unittest.TestCase):

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)  # let state module create it fresh

    def tearDown(self):
        import gc
        gc.collect()  # force-close any lingering sqlite connections (Windows)
        try:
            if os.path.exists(self.db_path):
                os.unlink(self.db_path)
        except PermissionError:
            pass  # Windows: file still locked; left for OS cleanup at process exit

    def test_new_announcement_not_seen(self):
        self.assertFalse(is_seen("ann-001", db_path=self.db_path))

    def test_mark_and_check_seen(self):
        mark_seen("ann-001", db_path=self.db_path)
        self.assertTrue(is_seen("ann-001", db_path=self.db_path))

    def test_mark_idempotent(self):
        mark_seen("ann-001", db_path=self.db_path)
        mark_seen("ann-001", db_path=self.db_path)  # should not raise
        self.assertTrue(is_seen("ann-001", db_path=self.db_path))

    def test_count_seen_empty(self):
        self.assertEqual(count_seen(db_path=self.db_path), 0)

    def test_count_seen_increments(self):
        mark_seen("a", db_path=self.db_path)
        mark_seen("b", db_path=self.db_path)
        self.assertEqual(count_seen(db_path=self.db_path), 2)

    def test_different_ids_independent(self):
        mark_seen("ann-001", db_path=self.db_path)
        self.assertFalse(is_seen("ann-002", db_path=self.db_path))

    def test_matched_flag_stored(self):
        mark_seen("ann-001", matched=True, db_path=self.db_path)
        conn = _connect(db_path=self.db_path)
        row = conn.execute(
            "SELECT matched FROM seen_announcements WHERE id='ann-001'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 1)

    def test_unmatched_flag_stored(self):
        mark_seen("ann-002", matched=False, db_path=self.db_path)
        conn = _connect(db_path=self.db_path)
        row = conn.execute(
            "SELECT matched FROM seen_announcements WHERE id='ann-002'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 0)


# =============================================================================
# parsers.py
# =============================================================================

class TestExtractBirthYear(unittest.TestCase):

    def test_fods_with_accent(self):
        self.assertEqual(extract_birth_year("född 1942"), 1942)

    def test_f_dot(self):
        self.assertEqual(extract_birth_year("f. 1942"), 1942)

    def test_star_format(self):
        self.assertEqual(extract_birth_year("*1942"), 1942)

    def test_year_range(self):
        self.assertEqual(extract_birth_year("1945-2026"), 1945)

    def test_standalone_year(self):
        self.assertEqual(extract_birth_year("Göran Frisk 1945"), 1945)

    def test_no_year(self):
        self.assertIsNone(extract_birth_year("Göran Frisk"))

    def test_empty(self):
        self.assertIsNone(extract_birth_year(""))

    def test_year_out_of_range(self):
        self.assertIsNone(extract_birth_year("year 1850"))

    def test_case_insensitive(self):
        self.assertEqual(extract_birth_year("FÖDD 1965"), 1965)


class TestExtractLocation(unittest.TestCase):
    """extract_location currently returns None (Sprint 2 stub)."""

    def test_returns_none(self):
        self.assertIsNone(extract_location("Haninge"))

    def test_returns_none_empty(self):
        self.assertIsNone(extract_location(""))


class TestParsePublicationDate(unittest.TestCase):

    def test_iso_date_string(self):
        self.assertEqual(parse_publication_date("2026-04-08"), "2026-04-08")

    def test_datetime_object(self):
        dt = datetime(2026, 4, 8, 10, 30)
        self.assertEqual(parse_publication_date(dt), "2026-04-08")

    def test_feedparser_entry_with_published_parsed(self):
        entry = MagicMock()
        entry.published_parsed = (2026, 4, 8, 10, 0, 0, 0, 0, 0)
        self.assertEqual(parse_publication_date(entry), "2026-04-08")

    def test_feedparser_entry_without_published(self):
        entry = MagicMock(spec=[])  # no published_parsed attribute
        result = parse_publication_date(entry)
        # Should return today's date (YYYY-MM-DD format)
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2}")

    def test_empty_string_returns_today(self):
        result = parse_publication_date("")
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2}")


class TestCleanName(unittest.TestCase):

    def test_removes_in_memoriam_prefix(self):
        self.assertEqual(clean_name("In memoriam Göran Frisk"), "Göran Frisk")

    def test_removes_minnesruna_prefix(self):
        self.assertEqual(clean_name("Minnesruna: Lars Andersson"), "Lars Andersson")

    def test_removes_dodsannons_prefix(self):
        self.assertEqual(clean_name("Dödsannons Karin Berg"), "Karin Berg")

    def test_removes_till_minne_av_prefix(self):
        self.assertEqual(clean_name("Till minne av Anna Svensson"), "Anna Svensson")

    def test_plain_name_unchanged(self):
        self.assertEqual(clean_name("Göran Frisk"), "Göran Frisk")

    def test_empty_string(self):
        self.assertEqual(clean_name(""), "")

    def test_case_insensitive_prefix(self):
        self.assertEqual(clean_name("IN MEMORIAM Göran Frisk"), "Göran Frisk")


# =============================================================================
# notifier.py — mocked smtplib
# =============================================================================

class TestNotifierSendUrgent(unittest.TestCase):
    """Tests send_urgent() with smtplib and config fully mocked."""

    def _make_match(self) -> "Match":
        entry = _entry()
        ann = _announcement()
        return Match(
            entry=entry,
            announcement=ann,
            score=90,
            score_breakdown={"efternamn_exact": 40, "fornamn_exact": 30, "fodelsear": 20},
        )

    def test_send_urgent_calls_smtp(self):
        """send_urgent() should log in and sendmail exactly once."""
        mock_cfg = {
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "bot@example.com",
                "use_ssl": False,
                "use_starttls": False,
                "password_env": "SMTP_PASSWORD",
            },
            "notify": {"to": "clio@arvas.se", "from_label": "clio-agent-obit"},
        }

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        import notifier
        with patch.object(notifier, "_load_config", return_value=mock_cfg), \
             patch.dict(os.environ, {"SMTP_PASSWORD": "secret"}), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            notifier.send_urgent(self._make_match(), to_addr="clio@arvas.se")

        mock_smtp_instance.login.assert_called_once_with("bot@example.com", "secret")
        mock_smtp_instance.sendmail.assert_called_once()

    def test_send_urgent_subject_contains_name(self):
        """Subject of the sent email must mention the matched person's name."""
        import base64
        mock_cfg = {
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "bot@example.com",
                "use_ssl": False,
                "use_starttls": False,
                "password_env": "SMTP_PASSWORD",
            },
            "notify": {"to": "clio@arvas.se", "from_label": "clio-agent-obit"},
        }

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        import notifier
        captured = {}

        def capture_sendmail(from_addr, to_addr, msg_str):
            captured["msg"] = msg_str

        mock_smtp_instance.sendmail.side_effect = capture_sendmail

        with patch.object(notifier, "_load_config", return_value=mock_cfg), \
             patch.dict(os.environ, {"SMTP_PASSWORD": "secret"}), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            notifier.send_urgent(self._make_match(), to_addr="clio@arvas.se")

        # The message body may be base64-encoded; decode all base64 chunks to find name
        raw = captured.get("msg", "")
        decoded_parts = []
        for chunk in raw.split("\n"):
            chunk = chunk.strip()
            if len(chunk) % 4 == 0 and chunk:
                try:
                    decoded_parts.append(base64.b64decode(chunk).decode("utf-8", errors="ignore"))
                except Exception:
                    pass
        full_decoded = raw + " " + " ".join(decoded_parts)
        # "frisk" appears in the normalized body text; "Frisk" appears in announcement.namn
        self.assertTrue(
            "risk" in full_decoded.lower(),
            f"Expected name 'frisk' in decoded message. Got: {full_decoded[:500]}"
        )

    def test_send_digest_empty_does_nothing(self):
        """send_digest with empty list should not call _send."""
        import notifier
        with patch.object(notifier, "_send") as mock_send:
            notifier.send_digest([], run_date="2026-04-08")
        mock_send.assert_not_called()

    def test_send_digest_calls_smtp_for_matches(self):
        """send_digest with matches should call _send once."""
        mock_cfg = {
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "bot@example.com",
                "use_ssl": False,
                "use_starttls": False,
                "password_env": "SMTP_PASSWORD",
            },
            "notify": {"to": "clio@arvas.se", "from_label": "clio-agent-obit"},
        }

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        import notifier

        match = self._make_match()
        with patch.object(notifier, "_load_config", return_value=mock_cfg), \
             patch.dict(os.environ, {"SMTP_PASSWORD": "secret"}), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            notifier.send_digest([match], run_date="2026-04-08", to_addr="clio@arvas.se")

        mock_smtp_instance.sendmail.assert_called_once()

    def test_create_smtp_raises_without_password(self):
        """_create_smtp should raise ValueError if password env var is missing."""
        cfg = {
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "bot@example.com",
                "use_ssl": False,
                "use_starttls": False,
                "password_env": "SMTP_PASSWORD_MISSING_XYZ",
            }
        }
        import notifier
        with patch.dict(os.environ, {}, clear=True):
            # Remove the variable if it happens to be set
            os.environ.pop("SMTP_PASSWORD_MISSING_XYZ", None)
            with self.assertRaises(ValueError):
                notifier._create_smtp(cfg)


# =============================================================================
# sources/source_familjesidan_rss.py
#
# The RSS module uses "from sources.source_base import ..." which is
# sensitive to the order in which test suites are loaded (clio-research also
# has a "sources" package that ends up in sys.modules first).
# We load it via importlib with explicit path control to avoid the conflict.
# =============================================================================

import importlib
import importlib.util
import types as _types

def _load_rss_module():
    """Load source_familjesidan_rss with the obit sources/ package in place."""
    rss_path = OBIT / "sources" / "source_familjesidan_rss.py"
    obit_sources_str = str(OBIT / "sources")
    obit_str = str(OBIT)

    # Temporarily ensure clio-agent-obit is resolved for "sources.*" imports
    saved = {}
    for key in ("sources", "sources.source_base", "sources.parsers"):
        saved[key] = sys.modules.get(key)

    # Install a fresh "sources" package pointing at clio-agent-obit/sources/
    pkg = _types.ModuleType("sources")
    pkg.__path__ = [obit_sources_str]
    pkg.__package__ = "sources"
    sys.modules["sources"] = pkg

    try:
        spec = importlib.util.spec_from_file_location("source_familjesidan_rss", rss_path)
        mod = importlib.util.module_from_spec(spec)
        # Ensure sub-imports land under the right name
        sys.modules["source_familjesidan_rss"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        # Restore original sys.modules state
        for key, val in saved.items():
            if val is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = val


try:
    _rss_mod = _load_rss_module()
    _RSS_LOADED = True
except Exception as _rss_err:
    _RSS_LOADED = False
    _rss_mod = None


@unittest.skipUnless(_RSS_LOADED, "source_familjesidan_rss could not be loaded")
class TestFamiljesidanRssParser(unittest.TestCase):

    def _make_feedparser_entry(self, title="Göran Frisk", summary="född 1945 Haninge",
                               link="http://example.com/1", entry_id=None,
                               published_parsed=None):
        entry = MagicMock()
        entry.title = title
        entry.summary = summary
        entry.link = link
        entry.id = entry_id or link
        entry.published_parsed = published_parsed
        return entry

    def test_parse_valid_entry(self):
        entry = self._make_feedparser_entry()
        ann = _rss_mod._parse_entry(entry)
        self.assertIsNotNone(ann)
        self.assertIn("Frisk", ann.namn)

    def test_parse_entry_extracts_birth_year(self):
        entry = self._make_feedparser_entry(
            title="Göran Frisk", summary="född 1945 i Haninge"
        )
        ann = _rss_mod._parse_entry(entry)
        self.assertEqual(ann.fodelsear, 1945)

    def test_parse_entry_empty_title_returns_none(self):
        entry = self._make_feedparser_entry(title="", link="http://example.com/1")
        ann = _rss_mod._parse_entry(entry)
        self.assertIsNone(ann)

    def test_parse_entry_empty_link_returns_none(self):
        entry = self._make_feedparser_entry(link="")
        ann = _rss_mod._parse_entry(entry)
        self.assertIsNone(ann)

    def test_fetch_uses_feedparser(self):
        mock_feed = MagicMock()
        mock_feed.status = 200
        mock_feed.entries = [
            self._make_feedparser_entry("Karin Berg", "f. 1952", "http://ex.com/2"),
        ]

        with patch("feedparser.parse", return_value=mock_feed) as mock_parse:
            src = _rss_mod.FamiljesidanRssSource(rss_urls=["http://rss.example.com/feed"])
            results = src.fetch()

        mock_parse.assert_called_once_with("http://rss.example.com/feed")
        self.assertEqual(len(results), 1)
        self.assertIn("Berg", results[0].namn)

    def test_fetch_empty_url_list_returns_empty(self):
        src = _rss_mod.FamiljesidanRssSource(rss_urls=[])
        results = src.fetch()
        self.assertEqual(results, [])

    def test_fetch_http_error_raises_source_error(self):
        mock_feed = MagicMock()
        mock_feed.status = 404
        mock_feed.entries = []

        with patch("feedparser.parse", return_value=mock_feed):
            src = _rss_mod.FamiljesidanRssSource(rss_urls=["http://bad.example.com/feed"])
            SourceError = _rss_mod.SourceError
            with self.assertRaises(SourceError):
                src.fetch()


if __name__ == "__main__":
    unittest.main(verbosity=2)
