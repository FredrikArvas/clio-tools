"""
test_afu_classify_docs.py
Unit tests för clio-afu/afu_classify_docs.py

Täcker:
  - Prompten innehåller inga ifyllda standardvärden som modellen kan kopiera
  - is_excluded() — EmptyPages m.fl. och F9_n_rtf-dubbletter sorteras bort
  - .doc som egentligen är RTF extraheras via striprtf
  - clean_text() tar bort kontrolltecken som bryter XML-RPC
  - to_bool() tolkar LLM-strängar rätt
  - _extract_json() klarar markdown-block och skräp
  - encounter_id är deterministiskt per sökväg
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).parent.parent.parent / "clio-afu" / "afu_classify_docs.py"
spec = importlib.util.spec_from_file_location("afu_classify_docs", _MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

_RTF_SAMPLE = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0 Times;}}"
    b"\\f0 Sp\\'f6kraket \\'f6ver Kamlunge tr\\'e4sk\\par}"
)


class TestPrompt(unittest.TestCase):
    def test_template_has_placeholders_not_defaults(self):
        self.assertIn("<true|false>", mod.CLASSIFY_PROMPT)
        self.assertNotIn('"is_case_report": false', mod.CLASSIFY_PROMPT)
        self.assertNotIn('"summary_sv": ""', mod.CLASSIFY_PROMPT)

    def test_template_formats(self):
        out = mod.CLASSIFY_PROMPT.format(
            filename="a.pdf", source_dir="UFO-reports", max_chars=10, text="hej"
        )
        self.assertIn("hej", out)


class TestIsExcluded(unittest.TestCase):
    def test_empty_pages_excluded(self):
        self.assertTrue(mod.is_excluded(Path("UFO-reports/x/EmptyPages/000010.pdf")))

    def test_f9_rtf_excluded(self):
        self.assertTrue(mod.is_excluded(Path("UFO-reports/RTF/F9_3_rtf/000010.rtf")))

    def test_f9_pdf_kept(self):
        self.assertFalse(mod.is_excluded(Path("UFO-reports/PDF/F9_3_pdf/000010.pdf")))

    def test_filename_matching_dir_name_kept(self):
        self.assertFalse(mod.is_excluded(Path("UFO-reports/EmptyPages")))


class TestExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    @unittest.skipUnless(importlib.util.find_spec("striprtf"), "striprtf saknas")
    def test_doc_that_is_rtf_extracted(self):
        p = self.tmp / "aviser.doc"
        p.write_bytes(_RTF_SAMPLE)
        text = mod.extract_text_full(p)
        self.assertIn("Spökraket över Kamlunge träsk", text)

    def test_binary_doc_without_antiword_output_gives_none(self):
        p = self.tmp / "trasig.doc"
        p.write_bytes(b"\xd0\xcf\x11\xe0garbage")
        self.assertFalse(mod._is_rtf(p))

    def test_unknown_extension_gives_none(self):
        p = self.tmp / "bild.jpg"
        p.write_bytes(b"\xff\xd8")
        self.assertIsNone(mod.extract_text_full(p))


class TestCleanText(unittest.TestCase):
    def test_control_chars_removed(self):
        self.assertEqual(mod.clean_text("a\x0cb\x01c"), "abc")

    def test_newlines_kept(self):
        self.assertEqual(mod.clean_text("rad1\nrad2"), "rad1\nrad2")


class TestToBool(unittest.TestCase):
    def test_string_false_is_false(self):
        self.assertFalse(mod.to_bool("false"))

    def test_string_true_is_true(self):
        self.assertTrue(mod.to_bool("True"))

    def test_none_is_false(self):
        self.assertFalse(mod.to_bool(None))


class TestExtractJson(unittest.TestCase):
    def test_markdown_block(self):
        raw = 'Här:\n```json\n{"is_case_report": true}\n```'
        self.assertEqual(mod._extract_json(raw), {"is_case_report": True})

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            mod._extract_json("inget json här")


class TestEncounterVals(unittest.TestCase):
    def test_encounter_id_deterministic(self):
        a = mod._build_encounter_vals("UFO-reports/a.pdf", "a.pdf", "UFO-reports", {}, None)
        b = mod._build_encounter_vals("UFO-reports/a.pdf", "a.pdf", "UFO-reports", {}, None)
        c = mod._build_encounter_vals("UFO-reports/b.pdf", "b.pdf", "UFO-reports", {}, None)
        self.assertEqual(a["encounter_id"], b["encounter_id"])
        self.assertNotEqual(a["encounter_id"], c["encounter_id"])

    def test_string_false_suppression(self):
        v = mod._build_encounter_vals(
            "x.pdf", "x.pdf", "UFO-reports", {"suppression_indicator": "false"}, None
        )
        self.assertFalse(v["suppression_indicator"])


if __name__ == "__main__":
    unittest.main()
