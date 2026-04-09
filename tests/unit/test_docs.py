"""
test_docs.py
Unit tests for clio-docs-batch.py

Tests:
    - find_pdfs() discovers correct files
    - extract_md() builds valid MD from sidecar text
    - Temp file workaround triggers for non-ASCII paths
"""

import sys
import unittest
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "config"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "clio-docs"))

FIXTURES = Path(__file__).parent.parent / "fixtures"

import importlib.util
spec = importlib.util.spec_from_file_location(
    "clio_docs",
    Path(__file__).parent.parent.parent / "clio-docs" / "clio-docs-batch.py"
)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    _MOD_LOADED = True
except Exception as e:
    _MOD_LOADED = False
    _MOD_ERROR = str(e)


@unittest.skipUnless(_MOD_LOADED, "clio-docs module could not be loaded")
class TestFindPdfs(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "book.pdf").write_bytes(b"%PDF-1.4 test")
        (self.tmp / "book_OCR.pdf").write_bytes(b"%PDF-1.4 ocr")
        (self.tmp / "notes.txt").write_text("not a pdf")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_finds_pdfs(self):
        result = mod.find_pdfs(self.tmp)
        names = [f.name for f in result]
        self.assertIn("book.pdf", names)

    def test_excludes_ocr_files(self):
        result = mod.find_pdfs(self.tmp)
        names = [f.name for f in result]
        self.assertNotIn("book_OCR.pdf", names)

    def test_excludes_non_pdfs(self):
        result = mod.find_pdfs(self.tmp)
        names = [f.name for f in result]
        self.assertNotIn("notes.txt", names)

    def test_recursive(self):
        sub = self.tmp / "subdir"
        sub.mkdir()
        (sub / "nested.pdf").write_bytes(b"%PDF-1.4")
        flat = mod.find_pdfs(self.tmp, recursive=False)
        deep = mod.find_pdfs(self.tmp, recursive=True)
        self.assertGreater(len(deep), len(flat))


@unittest.skipUnless(_MOD_LOADED, "clio-docs module could not be loaded")
class TestHasNonAscii(unittest.TestCase):

    def test_swedish_path_triggers_temp(self):
        from clio_utils import has_non_ascii
        self.assertTrue(has_non_ascii("/Users/fredr/Göteborg/file.pdf"))

    def test_ascii_path_no_temp(self):
        from clio_utils import has_non_ascii
        self.assertFalse(has_non_ascii("/Users/fredr/Documents/file.pdf"))


@unittest.skipUnless(_MOD_LOADED, "clio-docs module could not be loaded")
class TestExtractMd(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_sidecar_creates_md(self):
        fake_pdf = self.tmp / "book_OCR.pdf"
        try:
            import fitz
            doc = fitz.open()
            doc.new_page()
            doc.save(str(fake_pdf))
            doc.close()
        except ImportError:
            self.skipTest("pymupdf not available")

        sidecar = self.tmp / "book_OCR.txt"
        sidecar.write_text("First page text.\x0cSecond page text.", encoding="utf-8")

        ok, msg = mod.extract_md(fake_pdf, "book", "2026-03-29", sidecar)
        self.assertTrue(ok, msg)

        md_file = self.tmp / "book_OCR.md"
        self.assertTrue(md_file.exists())
        content = md_file.read_text(encoding="utf-8")
        self.assertIn("book", content)
        self.assertIn("First page text", content)

    def test_skips_existing_md(self):
        fake_pdf = self.tmp / "book_OCR.pdf"
        fake_pdf.write_bytes(b"")
        existing_md = self.tmp / "book_OCR.md"
        existing_md.write_text("already exists")

        ok, msg = mod.extract_md(fake_pdf, "book", "2026-03-29")
        self.assertFalse(ok)
        self.assertIn("Skipping", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
