"""
test_utils.py
Unit tests for clio_utils.py

Tests:
    - sanitize_filename()
    - has_non_ascii()
    - propose_rename()
    - t() translation function
    - _format_time() from clio-transcribe
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "config"))
from clio_utils import sanitize_filename, has_non_ascii, propose_rename, t, set_language


class TestSanitizeFilename(unittest.TestCase):

    def test_removes_parentheses(self):
        self.assertEqual(
            sanitize_filename("Enuma Elish (Svensk översättning).pdf"),
            "Enuma Elish Svensk översättning.pdf"
        )

    def test_preserves_spaces(self):
        result = sanitize_filename("My Book Title.pdf")
        self.assertEqual(result, "My Book Title.pdf")

    def test_preserves_swedish_chars(self):
        result = sanitize_filename("Jättarnas Bok.pdf")
        self.assertEqual(result, "Jättarnas Bok.pdf")

    def test_preserves_date_prefix(self):
        result = sanitize_filename("2024-08-03 Enuma Elish.pdf")
        self.assertEqual(result, "2024-08-03 Enuma Elish.pdf")

    def test_removes_comma(self):
        result = sanitize_filename("Tesla, UFOs.pdf")
        self.assertEqual(result, "Tesla UFOs.pdf")

    def test_removes_brackets(self):
        result = sanitize_filename("file[draft].pdf")
        self.assertEqual(result, "filedraft.pdf")

    def test_collapses_multiple_spaces(self):
        result = sanitize_filename("file  name.pdf")
        self.assertEqual(result, "file name.pdf")

    def test_already_clean(self):
        name = "already_ok_name.pdf"
        self.assertEqual(sanitize_filename(name), name)

    def test_preserves_extension(self):
        result = sanitize_filename("test (file).docx")
        self.assertTrue(result.endswith(".docx"))


class TestHasNonAscii(unittest.TestCase):

    def test_swedish_chars(self):
        self.assertTrue(has_non_ascii("Jättarnas Bok.pdf"))
        self.assertTrue(has_non_ascii("C:/Users/fredr/Göteborg/file.pdf"))

    def test_ascii_only(self):
        self.assertFalse(has_non_ascii("simple_file.pdf"))
        self.assertFalse(has_non_ascii("C:/Users/fredr/Documents/file.pdf"))

    def test_empty_string(self):
        self.assertFalse(has_non_ascii(""))

    def test_mixed(self):
        self.assertTrue(has_non_ascii("file_åäö_test.pdf"))


class TestProposeRename(unittest.TestCase):

    def test_needs_rename(self):
        needs, new_name = propose_rename("file (test).pdf")
        self.assertTrue(needs)
        self.assertEqual(new_name, "file test.pdf")

    def test_no_rename_needed(self):
        needs, new_name = propose_rename("clean_file.pdf")
        self.assertFalse(needs)
        self.assertEqual(new_name, "clean_file.pdf")


class TestTranslation(unittest.TestCase):

    def test_swedish_key_exists(self):
        set_language("sv")
        result = t("search_subfolders")
        self.assertNotEqual(result, "search_subfolders")
        self.assertIn("n/J", result)

    def test_english_key_exists(self):
        set_language("en")
        result = t("search_subfolders")
        self.assertNotEqual(result, "search_subfolders")
        self.assertIn("n/Y", result)

    def test_unknown_key_returns_key(self):
        result = t("this_key_does_not_exist")
        self.assertEqual(result, "this_key_does_not_exist")

    def test_format_placeholder(self):
        set_language("en")
        result = t("starting_batch", n=5)
        self.assertIn("5", result)

    def tearDown(self):
        set_language("sv")


class TestFormatTime(unittest.TestCase):
    """Tests _format_time from clio-transcribe-batch."""

    def setUp(self):
        import logging
        logging.disable(logging.CRITICAL)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "transcribe",
            Path(__file__).parent.parent.parent / "clio-transcribe" / "clio-transcribe-batch.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self._format_time = mod._format_time
        logging.disable(logging.NOTSET)

    def test_seconds_only(self):
        self.assertEqual(self._format_time(65), "01:05")

    def test_zero(self):
        self.assertEqual(self._format_time(0), "00:00")

    def test_hours(self):
        self.assertEqual(self._format_time(3661), "01:01:01")

    def test_under_minute(self):
        self.assertEqual(self._format_time(45), "00:45")


if __name__ == "__main__":
    unittest.main(verbosity=2)
