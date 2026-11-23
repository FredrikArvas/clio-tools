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

    def test_article_linked_as_source_document(self):
        v = mod._build_encounter_vals("x.pdf", "x.pdf", "UFO-reports", {}, 42)
        self.assertEqual(v["article_ids"], [(4, 42)])

    def test_no_article_gives_no_link(self):
        v = mod._build_encounter_vals("x.pdf", "x.pdf", "UFO-reports", {}, None)
        self.assertEqual(v["article_ids"], [])

    def test_string_false_suppression(self):
        v = mod._build_encounter_vals(
            "x.pdf", "x.pdf", "UFO-reports", {"suppression_indicator": "false"}, None
        )
        self.assertFalse(v["suppression_indicator"])


class TestArticleClassificationVals(unittest.TestCase):
    def test_full_record(self):
        v = mod.article_classification_vals({
            "is_case_report": "true", "eth_origin": 2, "craft_class": "Tic-Tac",
            "case_date": "1946-07-24", "location": "Kamlunge", "summary_sv": "Spökraket.",
            "text_chars": 1818, "enriched_at": "2026-11-22T21:00:50.123+00:00",
        })
        self.assertTrue(v["is_afu_case_report"])
        self.assertEqual(v["afu_eth_origin"], "2")
        self.assertEqual(v["afu_craft_class"], "II")
        self.assertEqual(v["afu_case_year"], 1946)
        self.assertEqual(v["afu_classified_at"], "2026-11-22 21:00:50")

    def test_empty_record_gives_falsy_values(self):
        v = mod.article_classification_vals({"text_chars": 0})
        self.assertFalse(v["is_afu_case_report"])
        self.assertFalse(v["afu_eth_origin"])
        self.assertEqual(v["afu_case_year"], 0)
        self.assertFalse(v["afu_summary"])

    def test_bad_case_date_gives_no_year(self):
        self.assertEqual(mod._case_year("okänt"), 0)
        self.assertEqual(mod._case_year("9999-01"), 0)


class TestSyncArticle(unittest.TestCase):
    def _kw(self, article):
        calls = []

        def kw(model, method, args, kwargs=None):
            calls.append((method, args))
            return [article] if method == "search_read" and article else []
        return kw, calls

    def test_writes_fields_and_empty_body(self):
        kw, calls = self._kw({"id": 7, "body": False})
        rec = {"filepath": "UFO-reports/a.pdf", "text_chars": 3, "enriched_at": ""}
        self.assertEqual(mod.sync_article(kw, rec, "hej", "t"), 7)
        vals = calls[-1][1][1]
        self.assertEqual(vals["body"], "hej")
        self.assertIn("afu_text_chars", vals)

    def test_keeps_existing_body(self):
        kw, calls = self._kw({"id": 7, "body": "befintlig"})
        mod.sync_article(kw, {"filepath": "a.pdf"}, "ny", "t")
        self.assertNotIn("body", calls[-1][1][1])

    def test_missing_article_returns_none(self):
        kw, calls = self._kw(None)
        self.assertIsNone(mod.sync_article(kw, {"filepath": "a.pdf"}, "x", "t"))
        self.assertEqual([c[0] for c in calls], ["search_read"])

    def test_odoo_error_is_logged_not_raised(self):
        def kw(*a, **k):
            raise ConnectionError("nere")
        with self.assertLogs(mod.logger, level="WARNING"):
            self.assertIsNone(mod.sync_article(kw, {"filepath": "a.pdf"}, "x", "t"))


if __name__ == "__main__":
    unittest.main()
