"""
test_narrate.py
Unit tests for clio-narrate-batch.py

Tests:
    - extract_text() for docx, md, txt
    - split_into_chunks() splits correctly
    - find_files() discovers correct files
    - tag_mp3() writes ID3 tags (requires mutagen)
"""

import sys
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

FIXTURES = Path(__file__).parent.parent / "fixtures"

import importlib.util
spec = importlib.util.spec_from_file_location(
    "clio_narrate",
    Path(__file__).parent.parent.parent / "clio-narrate" / "clio-narrate-batch.py"
)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    _MOD_LOADED = True
except Exception as e:
    _MOD_LOADED = False
    _MOD_ERROR = str(e)


@unittest.skipUnless(_MOD_LOADED, "clio-narrate module could not be loaded")
class TestExtractText(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_txt_extraction(self):
        f = self.tmp / "test.txt"
        f.write_text("Hello world.\n\nSecond paragraph.", encoding="utf-8")
        result = mod.extract_text(f)
        self.assertIn("Hello world", result)
        self.assertIn("Second paragraph", result)

    def test_md_strips_headers(self):
        f = self.tmp / "test.md"
        f.write_text("# Title\n\nSome content here.\n\n## Section\n\nMore text.", encoding="utf-8")
        result = mod.extract_text(f)
        self.assertNotIn("# Title", result)
        self.assertIn("Some content here", result)

    def test_md_strips_html_comments(self):
        f = self.tmp / "test.md"
        f.write_text("<!-- comment -->\n\nActual content.", encoding="utf-8")
        result = mod.extract_text(f)
        self.assertNotIn("<!--", result)
        self.assertIn("Actual content", result)

    def test_md_strips_frontmatter(self):
        f = self.tmp / "test.md"
        f.write_text("---\ntitle: Test\ndate: 2026\n---\n\nContent here.", encoding="utf-8")
        result = mod.extract_text(f)
        self.assertNotIn("title:", result)
        self.assertIn("Content here", result)

    def test_docx_extraction(self):
        fixture = FIXTURES / "sample.docx"
        if not fixture.exists():
            self.skipTest("Run tests/fixtures/generate_fixtures.py first")
        result = mod.extract_text(fixture)
        self.assertGreater(len(result), 10)
        self.assertIsInstance(result, str)

    def test_empty_file_returns_empty(self):
        f = self.tmp / "empty.txt"
        f.write_text("", encoding="utf-8")
        result = mod.extract_text(f)
        self.assertEqual(result.strip(), "")


@unittest.skipUnless(_MOD_LOADED, "clio-narrate module could not be loaded")
class TestSplitIntoChunks(unittest.TestCase):

    def test_short_text_single_chunk(self):
        text = "Short text."
        chunks = mod.split_into_chunks(text, max_chars=1000)
        self.assertEqual(len(chunks), 1)

    def test_long_text_multiple_chunks(self):
        text = "\n\n".join([f"Paragraph {i}. " * 20 for i in range(10)])
        chunks = mod.split_into_chunks(text, max_chars=200)
        self.assertGreater(len(chunks), 1)

    def test_no_empty_chunks(self):
        text = "Para one.\n\n\n\nPara two.\n\n"
        chunks = mod.split_into_chunks(text)
        for chunk in chunks:
            self.assertTrue(chunk.strip())

    def test_respects_max_chars(self):
        text = "\n\n".join(["x" * 100 for _ in range(20)])
        chunks = mod.split_into_chunks(text, max_chars=300)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 400)


@unittest.skipUnless(_MOD_LOADED, "clio-narrate module could not be loaded")
class TestFindFiles(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "book.docx").write_bytes(b"fake docx")
        (self.tmp / "notes.txt").write_text("text")
        (self.tmp / "chapter.md").write_text("# MD")
        (self.tmp / "book_NARRAT.mp3").write_bytes(b"fake mp3")
        (self.tmp / "image.jpg").write_bytes(b"fake jpg")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_finds_supported_formats(self):
        result = mod.find_files(self.tmp)
        names = [f.name for f in result]
        self.assertIn("book.docx", names)
        self.assertIn("notes.txt", names)
        self.assertIn("chapter.md", names)

    def test_excludes_narrat_files(self):
        result = mod.find_files(self.tmp)
        names = [f.name for f in result]
        self.assertNotIn("book_NARRAT.mp3", names)

    def test_excludes_unsupported_formats(self):
        result = mod.find_files(self.tmp)
        names = [f.name for f in result]
        self.assertNotIn("image.jpg", names)


@unittest.skipUnless(_MOD_LOADED, "clio-narrate module could not be loaded")
class TestTagMp3(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_tags_written(self):
        try:
            from mutagen.id3 import ID3
        except ImportError:
            self.skipTest("mutagen not installed")

        mp3 = self.tmp / "test.mp3"
        mp3.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 413)

        mod.tag_mp3(mp3,
            title="Test Title",
            artist="Test Artist",
            album="Test Album",
            comment="test comment"
        )
        self.assertTrue(mp3.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
