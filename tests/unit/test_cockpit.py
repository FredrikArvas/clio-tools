"""
test_cockpit.py
Unit-tester för clio_cockpit och clio-agent-odoo.

Täcker:
    - _md_to_html()  — HTML-konvertering (ren funktion, ingen Odoo nödvändig)
    - _call()        — HTTP-anrop mot clio-service (mockat)
    - _reopen()      — rätt view_id per action
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import json

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-agent-odoo"))

from odoo_reply import _md_to_html  # ren funktion, inga Odoo-beroenden


# ── _md_to_html ────────────────────────────────────────────────────────────────

class TestMdToHtml(unittest.TestCase):

    def test_plain_text_wraps_in_p(self):
        result = _md_to_html("Hej världen")
        self.assertIn("<p>", result)
        self.assertIn("Hej världen", result)

    def test_html_chars_are_escaped(self):
        result = _md_to_html("a < b & c > d")
        self.assertIn("&lt;", result)
        self.assertIn("&amp;", result)
        self.assertIn("&gt;", result)
        self.assertNotIn("<b", result)   # inga lösa HTML-taggar

    def test_two_paragraphs(self):
        result = _md_to_html("Stycke ett\n\nStycke två")
        self.assertEqual(result.count("<p>"), 2)
        self.assertIn("Stycke ett", result)
        self.assertIn("Stycke två", result)

    def test_code_block_preserved(self):
        result = _md_to_html("Intro\n\n```python\nprint('hello')\n```\n\nAvslut")
        self.assertIn("<pre><code", result)   # class="language-python" kan finnas
        self.assertIn("print(", result)

    def test_code_block_html_escaped(self):
        result = _md_to_html("```\n<script>alert(1)</script>\n```")
        self.assertIn("&lt;script&gt;", result)
        self.assertNotIn("<script>", result)

    def test_single_newline_becomes_br(self):
        result = _md_to_html("Rad ett\nRad två")
        self.assertIn("<br", result)      # nl2br: enkel radbryt → <br/>
        self.assertIn("Rad ett", result)

    def test_empty_string(self):
        result = _md_to_html("")
        self.assertIsInstance(result, str)

    def test_only_whitespace(self):
        result = _md_to_html("   \n\n   ")
        self.assertIsInstance(result, str)


# ── _call (mockad HTTP) ────────────────────────────────────────────────────────

class TestCall(unittest.TestCase):

    def _make_env(self, param_value="http://test:7200"):
        env = MagicMock()
        env.__getitem__("ir.config_parameter") \
            .sudo().get_param.return_value = param_value
        return env

    def _mock_response(self, payload: dict):
        """Skapar en fake urllib-response som returnerar JSON."""
        import io
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_successful_call_returns_dict(self):
        try:
            from odoo.addons.clio_cockpit.models.clio_cockpit import _call
        except ImportError:
            self.skipTest("Odoo ej tillgängligt i denna miljö")
        with patch("urllib.request.urlopen", return_value=self._mock_response({"ok": True, "text": "svar"})):
            env = self._make_env()
            result = _call(env, "/health")
        self.assertEqual(result["text"], "svar")

    def test_urlerror_raises_usererror(self):
        import urllib.error
        try:
            from odoo.addons.clio_cockpit.models.clio_cockpit import _call
            from odoo.exceptions import UserError
        except ImportError:
            self.skipTest("Odoo ej tillgängligt i denna miljö")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            env = self._make_env()
            with self.assertRaises(UserError):
                _call(env, "/health")

    def test_ok_false_raises_usererror(self):
        try:
            from odoo.addons.clio_cockpit.models.clio_cockpit import _call
            from odoo.exceptions import UserError
        except ImportError:
            self.skipTest("Odoo ej tillgängligt i denna miljö")
        with patch("urllib.request.urlopen", return_value=self._mock_response({"ok": False, "error": "nope"})):
            env = self._make_env()
            with self.assertRaises(UserError):
                _call(env, "/broken")


# ── _reopen (view_id) ──────────────────────────────────────────────────────────

class TestReopen(unittest.TestCase):

    def _make_record(self, view_db_id=42):
        """Fake clio.cockpit-instans med mockat env.ref."""
        try:
            from odoo.addons.clio_cockpit.models.clio_cockpit import ClioCockpit
        except ImportError:
            return None

        rec = MagicMock(spec=ClioCockpit)
        rec._name = "clio.cockpit"
        rec.id    = 1
        fake_view = MagicMock()
        fake_view.id = view_db_id
        rec.env.ref.return_value = fake_view
        return rec

    def _call_reopen(self, rec, xml_id):
        from odoo.addons.clio_cockpit.models.clio_cockpit import ClioCockpit
        return ClioCockpit._reopen(rec, xml_id)

    def test_reopen_with_view_sets_view_id(self):
        try:
            from odoo.addons.clio_cockpit.models.clio_cockpit import ClioCockpit  # noqa
        except ImportError:
            self.skipTest("Odoo ej tillgängligt")
        rec = self._make_record(view_db_id=99)
        result = self._call_reopen(rec, "clio_cockpit.view_cockpit_rag")
        self.assertEqual(result["view_id"], 99)
        self.assertEqual(result["res_model"], "clio.cockpit")

    def test_reopen_without_view_omits_view_id(self):
        try:
            from odoo.addons.clio_cockpit.models.clio_cockpit import ClioCockpit  # noqa
        except ImportError:
            self.skipTest("Odoo ej tillgängligt")
        rec = self._make_record()
        rec.env.ref.return_value = None
        result = self._call_reopen(rec, None)
        self.assertNotIn("view_id", result)


if __name__ == "__main__":
    unittest.main()
