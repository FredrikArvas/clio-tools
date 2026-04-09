"""
test_docs_ocr.py
System tests for clio-docs-batch.py — requires Tesseract + ocrmypdf.

Tests:
    - Full OCR pipeline on sample.pdf produces output files
"""

import sys
import unittest
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "config"))

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


@unittest.skipIf(
    not shutil.which("tesseract"),
    "Tesseract not installed – skipping OCR system test"
)
@unittest.skipUnless(_MOD_LOADED, "clio-docs module could not be loaded")
class TestOcrIntegration(unittest.TestCase):
    """Requires tesseract and a real PDF fixture."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_ocr_creates_output_files(self):
        fixture = FIXTURES / "sample.pdf"
        if not fixture.exists():
            self.skipTest("Run tests/fixtures/generate_fixtures.py first")

        dest = self.tmp / "sample.pdf"
        shutil.copy(fixture, dest)

        ok, ocr_file, sidecar_file, msg = mod.ocr_pdf(dest)
        self.assertTrue(ok, f"OCR failed: {msg}")
        self.assertTrue(ocr_file.exists())

    def test_ocr_then_extract_md(self):
        fixture = FIXTURES / "sample.pdf"
        if not fixture.exists():
            self.skipTest("Run tests/fixtures/generate_fixtures.py first")

        dest = self.tmp / "sample.pdf"
        shutil.copy(fixture, dest)

        ok, ocr_file, sidecar_file, msg = mod.ocr_pdf(dest)
        if not ok:
            self.skipTest(f"OCR failed: {msg}")

        md_ok, md_msg = mod.extract_md(ocr_file, dest.stem, "2026-04-02", sidecar_file)
        self.assertTrue(md_ok, f"extract_md failed: {md_msg}")

        md_file = ocr_file.parent / f"{ocr_file.stem}.md"
        self.assertTrue(md_file.exists())
        content = md_file.read_text(encoding="utf-8")
        self.assertIn("## Page 1", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
