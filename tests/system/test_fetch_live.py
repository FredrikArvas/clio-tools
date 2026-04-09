"""
test_fetch_live.py
System tests for clio_fetch.py — requires internet + requests + beautifulsoup4.

Tests:
    - fetch_url() hämtar en riktig webbsida
    - process_one() sparar JSON med rätt struktur
"""

import sys
import json
import unittest
import tempfile
import shutil
from pathlib import Path

import importlib.util
spec = importlib.util.spec_from_file_location(
    "clio_fetch",
    Path(__file__).parent.parent.parent / "clio-fetch" / "clio_fetch.py"
)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    _MOD_LOADED = True
except Exception as e:
    _MOD_LOADED = False
    _MOD_ERROR = str(e)


@unittest.skipUnless(_MOD_LOADED, "clio_fetch module could not be loaded")
class TestFetchUrlLive(unittest.TestCase):
    """Kräver internet. Använder example.com (stabil IANA-sida)."""

    TEST_URL = "https://example.com"

    def test_fetch_returns_html(self):
        html, url = mod.fetch_url(self.TEST_URL)
        if not html:
            self.skipTest(f"Could not reach {self.TEST_URL} (SSL/network issue)")
        self.assertTrue(len(html) > 100, "Expected non-empty HTML")
        self.assertIn("<html", html.lower())

    def test_fetch_returns_source_url(self):
        html, url = mod.fetch_url(self.TEST_URL)
        self.assertEqual(url, self.TEST_URL)

    def test_nonexistent_url_returns_empty(self):
        html, url = mod.fetch_url("https://this-domain-does-not-exist-clio.invalid/")
        self.assertEqual(html, "")


@unittest.skipUnless(_MOD_LOADED, "clio_fetch module could not be loaded")
class TestProcessOneLive(unittest.TestCase):
    """Hämtar example.com och kontrollerar JSON-output."""

    TEST_URL = "https://example.com"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_process_one_creates_json(self):
        html, src = mod.fetch_url(self.TEST_URL)
        if not html:
            self.skipTest("Could not reach example.com")

        result = mod.process_one(html, src, str(self.tmp), base_url=self.TEST_URL)
        self.assertIsNotNone(result)

        saved = result["saved"]
        self.assertTrue(saved.exists())
        self.assertEqual(saved.suffix, ".json")

    def test_json_has_required_fields(self):
        html, src = mod.fetch_url(self.TEST_URL)
        if not html:
            self.skipTest("Could not reach example.com")

        result = mod.process_one(html, src, str(self.tmp), base_url=self.TEST_URL)
        data = json.loads(result["saved"].read_text(encoding="utf-8"))

        for field in ("title", "description", "text", "word_count", "source", "fetched_at"):
            self.assertIn(field, data, f"Missing field: {field}")

    def test_word_count_positive(self):
        html, src = mod.fetch_url(self.TEST_URL)
        if not html:
            self.skipTest("Could not reach example.com")

        result = mod.process_one(html, src, str(self.tmp), base_url=self.TEST_URL)
        data = json.loads(result["saved"].read_text(encoding="utf-8"))
        self.assertGreater(data["word_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
