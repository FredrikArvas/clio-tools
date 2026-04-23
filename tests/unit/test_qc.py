"""
test_qc.py
Unit-tester för clio_qc.py hjälpfunktioner.

Täcker:
    - _parse_requirements()  — extraherar paketnamn ur requirements.txt
"""

import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from clio_qc import _parse_requirements


class TestParseRequirements(unittest.TestCase):

    def _make_file(self, content: str, tmp_path: Path) -> Path:
        f = tmp_path / "requirements.txt"
        f.write_text(textwrap.dedent(content), encoding="utf-8")
        return f

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    # ── Basfall ────────────────────────────────────────────────────────────────

    def test_simple_package(self):
        f = self._make_file("requests\n", self.tmp)
        self.assertEqual(_parse_requirements(f), [("requests", False)])

    def test_version_constraint_stripped(self):
        f = self._make_file("anthropic>=0.25.0\n", self.tmp)
        self.assertEqual(_parse_requirements(f), [("anthropic", False)])

    def test_multiple_packages(self):
        f = self._make_file("flask\nrequests>=2.0\njinja2==3.1\n", self.tmp)
        names = [name for name, _ in _parse_requirements(f)]
        self.assertEqual(names, ["flask", "requests", "jinja2"])

    # ── Kommentarer och tomma rader ────────────────────────────────────────────

    def test_comment_lines_skipped(self):
        f = self._make_file("# detta är en kommentar\nrequests\n", self.tmp)
        names = [name for name, _ in _parse_requirements(f)]
        self.assertEqual(names, ["requests"])

    def test_empty_lines_skipped(self):
        f = self._make_file("\n\nrequests\n\n", self.tmp)
        names = [name for name, _ in _parse_requirements(f)]
        self.assertEqual(names, ["requests"])

    def test_inline_comment_stripped(self):
        f = self._make_file("requests  # HTTP-klient\n", self.tmp)
        names = [name for name, _ in _parse_requirements(f)]
        self.assertEqual(names, ["requests"])

    def test_commented_out_optional_skipped(self):
        f = self._make_file("# torch  # GPU-stöd\n", self.tmp)
        self.assertEqual(_parse_requirements(f), [])

    # ── Valfria paket: # optional ──────────────────────────────────────────────

    def test_optional_flag_detected(self):
        f = self._make_file("neo4j>=5.0  # optional\n", self.tmp)
        result = _parse_requirements(f)
        self.assertEqual(result, [("neo4j", True)])

    def test_non_optional_flag_not_set(self):
        f = self._make_file("requests\n", self.tmp)
        _, optional = _parse_requirements(f)[0]
        self.assertFalse(optional)

    def test_optional_case_insensitive(self):
        f = self._make_file("neo4j  # OPTIONAL\n", self.tmp)
        _, optional = _parse_requirements(f)[0]
        self.assertTrue(optional)

    # ── Versionsformat ─────────────────────────────────────────────────────────

    def test_double_equals(self):
        f = self._make_file("jinja2==3.1.4\n", self.tmp)
        self.assertEqual(_parse_requirements(f)[0][0], "jinja2")

    def test_tilde_equals(self):
        f = self._make_file("flask~=2.0\n", self.tmp)
        self.assertEqual(_parse_requirements(f)[0][0], "flask")

    def test_extras_stripped(self):
        f = self._make_file("requests[security]>=2.0\n", self.tmp)
        self.assertEqual(_parse_requirements(f)[0][0], "requests")

    # ── Tomfil ─────────────────────────────────────────────────────────────────

    def test_empty_file_returns_empty_list(self):
        f = self._make_file("", self.tmp)
        self.assertEqual(_parse_requirements(f), [])

    def test_only_comments_returns_empty_list(self):
        f = self._make_file("# kommentar 1\n# kommentar 2\n", self.tmp)
        self.assertEqual(_parse_requirements(f), [])
