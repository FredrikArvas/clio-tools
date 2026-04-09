"""
test_fetch.py
Unit tests for clio_fetch.py

Tests:
    - make_slug()   – URL- och filsystemslogik
    - should_skip() – filtreringslogik
    - parse()       – HTML-extraktion
    - save()        – JSON-skrivning till disk
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
class TestShouldSkip(unittest.TestCase):

    def test_skip_feed(self):
        skip, reason = mod.should_skip("feed/index.html")
        self.assertTrue(skip)
        self.assertIn("feed", reason)

    def test_skip_wp_json(self):
        skip, reason = mod.should_skip("wp-json/v2/posts")
        self.assertTrue(skip)

    def test_skip_hex_redirect(self):
        skip, reason = mod.should_skip("index1a2b.html")
        self.assertTrue(skip)
        self.assertEqual(reason, "redirect-hex")

    def test_skip_email_in_path(self):
        skip, reason = mod.should_skip("user@example.com/index.html")
        self.assertTrue(skip)
        self.assertEqual(reason, "e-post")

    def test_skip_pagination(self):
        skip, reason = mod.should_skip("blog/page/3/index.html")
        self.assertTrue(skip)
        self.assertEqual(reason, "paginering")

    def test_keep_normal_page(self):
        skip, reason = mod.should_skip("om-gtff/stadgar/index.html")
        self.assertFalse(skip)
        self.assertEqual(reason, "")

    def test_keep_root_index(self):
        skip, reason = mod.should_skip("index.html")
        self.assertFalse(skip)

    def test_keep_nested_page(self):
        skip, reason = mod.should_skip("kalender/midsommar/index.html")
        self.assertFalse(skip)


@unittest.skipUnless(_MOD_LOADED, "clio_fetch module could not be loaded")
class TestMakeSlug(unittest.TestCase):

    def test_live_url_simple(self):
        slug = mod.make_slug("https://gtff.se/om-gtff/stadgar/")
        self.assertEqual(slug, "gtff.se_om-gtff_stadgar")

    def test_live_url_root(self):
        slug = mod.make_slug("https://gtff.se/")
        self.assertEqual(slug, "gtff.se")

    def test_live_url_strips_index_php(self):
        slug = mod.make_slug("https://gtff.se/index.php/om-gtff/stadgar/")
        self.assertEqual(slug, "gtff.se_om-gtff_stadgar")

    def test_live_url_date_merging(self):
        slug = mod.make_slug("https://gtff.se/index.php/2017/01/04/nya-hemsidan/")
        self.assertEqual(slug, "gtff.se_2017-01-04_nya-hemsidan")

    def test_local_file_uses_base_dir(self):
        base_dir = Path("/srv/httrack/gtff.se")
        source = str(base_dir / "index.php" / "om-gtff" / "stadgar" / "index.html")
        slug = mod.make_slug(source, base_dir=base_dir)
        self.assertEqual(slug, "gtff.se_om-gtff_stadgar")

    def test_local_file_root(self):
        base_dir = Path("/srv/httrack/gtff.se")
        source = str(base_dir / "index.html")
        slug = mod.make_slug(source, base_dir=base_dir)
        self.assertEqual(slug, "gtff.se")


@unittest.skipUnless(_MOD_LOADED, "clio_fetch module could not be loaded")
class TestParse(unittest.TestCase):

    MINIMAL_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Test Page</title>
  <meta name="description" content="A test description.">
</head>
<body>
  <nav>Navigation</nav>
  <main>
    <h1>Hello World</h1>
    <p>This is the main content.</p>
  </main>
  <script>alert('noise')</script>
  <footer>Footer</footer>
</body>
</html>"""

    def test_extracts_title(self):
        data = mod.parse(self.MINIMAL_HTML, "https://example.com/")
        self.assertEqual(data["title"], "Test Page")

    def test_extracts_description(self):
        data = mod.parse(self.MINIMAL_HTML, "https://example.com/")
        self.assertEqual(data["description"], "A test description.")

    def test_extracts_main_content(self):
        data = mod.parse(self.MINIMAL_HTML, "https://example.com/")
        self.assertIn("Hello World", data["text"])
        self.assertIn("main content", data["text"])

    def test_removes_script_noise(self):
        data = mod.parse(self.MINIMAL_HTML, "https://example.com/")
        self.assertNotIn("alert", data["text"])

    def test_removes_nav_noise(self):
        data = mod.parse(self.MINIMAL_HTML, "https://example.com/")
        self.assertNotIn("Navigation", data["text"])

    def test_word_count_positive(self):
        data = mod.parse(self.MINIMAL_HTML, "https://example.com/")
        self.assertGreater(data["word_count"], 0)

    def test_source_preserved(self):
        data = mod.parse(self.MINIMAL_HTML, "https://example.com/test")
        self.assertEqual(data["source"], "https://example.com/test")

    def test_fetched_at_present(self):
        data = mod.parse(self.MINIMAL_HTML, "https://example.com/")
        self.assertIn("fetched_at", data)
        self.assertTrue(data["fetched_at"].startswith("20"))

    def test_empty_html_no_crash(self):
        data = mod.parse("<html><body></body></html>", "https://example.com/")
        self.assertIsInstance(data, dict)
        self.assertEqual(data["word_count"], 0)


@unittest.skipUnless(_MOD_LOADED, "clio_fetch module could not be loaded")
class TestSave(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_creates_json_file(self):
        data = {"title": "Test", "text": "Content", "word_count": 1,
                "source": "https://example.com", "description": "", "fetched_at": "2026-01-01"}
        path = mod.save(data, str(self.tmp), "example.com_test")
        self.assertTrue(path.exists())
        self.assertEqual(path.suffix, ".json")

    def test_json_is_valid(self):
        data = {"title": "Test", "text": "Content", "word_count": 1,
                "source": "https://example.com", "description": "", "fetched_at": "2026-01-01"}
        path = mod.save(data, str(self.tmp), "example.com_test")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["title"], "Test")

    def test_filename_includes_slug(self):
        data = {"title": "T", "text": "", "word_count": 0,
                "source": "x", "description": "", "fetched_at": "2026-01-01"}
        path = mod.save(data, str(self.tmp), "gtff.se_om-gtff")
        self.assertIn("gtff.se_om-gtff", path.name)

    def test_creates_output_dir_if_missing(self):
        subdir = self.tmp / "new_output"
        data = {"title": "T", "text": "", "word_count": 0,
                "source": "x", "description": "", "fetched_at": "2026-01-01"}
        mod.save(data, str(subdir), "test")
        self.assertTrue(subdir.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
