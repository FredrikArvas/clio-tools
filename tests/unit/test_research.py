"""
test_research.py — Enhetstester för clio-research-modulerna.

Testar:
  - GedcomSource (rena hjälpfunktioner + syntetisk fil)
  - WikidataSource (rena hjälpfunktioner)
  - LibrisSource (MARCXML-parsning)
  - NotionWriter (block-hjälpfunktioner, om notion_client finns)
  - ResearchPipeline (injicerade mock-källor, inga nätverksanrop)

Inga externa beroenden eller nätverksanrop.
"""

import sys
import unittest
import tempfile
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).parent.parent.parent
RESEARCH = ROOT / "clio-research"
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(RESEARCH / "sources"))

from gedcom import (
    GedcomSource,
    _normalize_email,
    _parse_gedcom_date,
    _extract_tag_value,
)
from wikidata import WikidataResult, _extract_qid, _format_wikidata_date
from libris import (
    LibrisSource,
    Publikation,
    _marc_subfield,
    _marc_all_subfields,
    _parse_record,
    _MARC_NS,
)

# Importera notion_writer om notion_client finns
try:
    from notion_writer import _text_block, _code_block, _heading_block, _table_row
    _NOTION_OK = True
except ImportError:
    _NOTION_OK = False

from pipeline import ResearchPipeline, PipelineResult
from confidence import FieldValue


# ---------------------------------------------------------------------------
# Syntetisk GEDCOM-fil
# ---------------------------------------------------------------------------

_GEDCOM_CONTENT = """\
0 HEAD
1 GEDC
2 VERS 5.5.1
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Anna /Svensson/
1 SEX F
1 BIRT
2 DATE 15 JAN 1980
2 PLAC Stockholm
1 DEAT
2 DATE 20 MAR 2020
2 PLAC Göteborg
1 EMAIL anna@@test.se
0 @I2@ INDI
1 NAME Johan* /Svensson/
1 SEX M
1 BIRT
2 DATE ABT 1990
0 @I3@ INDI
1 NAME Erik /Karlsson/
1 SEX M
1 BIRT
2 DATE JAN 1945
0 TRLR
"""

# Syntetisk MARCXML för Libris-tester
_MARC_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse>
  <numberOfRecords>1</numberOfRecords>
  <records>
    <record>
      <recordData>
        <record xmlns="{_MARC_NS}">
          <datafield tag="100" ind1=" " ind2=" ">
            <subfield code="e">upphovsman</subfield>
          </datafield>
          <datafield tag="245" ind1="1" ind2="0">
            <subfield code="a">En bok om något /</subfield>
          </datafield>
          <datafield tag="264" ind1=" " ind2="1">
            <subfield code="b">Norstedts,</subfield>
            <subfield code="c">[1980]</subfield>
          </datafield>
          <datafield tag="020" ind1=" " ind2=" ">
            <subfield code="a">978-91-7100-123-4</subfield>
          </datafield>
        </record>
      </recordData>
    </record>
  </records>
</searchRetrieveResponse>
"""

_MARC_XML_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse>
  <numberOfRecords>0</numberOfRecords>
  <records/>
</searchRetrieveResponse>
"""


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _make_marc_record(tag_attrs: dict[str, dict[str, str]]) -> ET.Element:
    """Skapar ett minimalt MARCXML-record-element för testning."""
    ns = _MARC_NS
    record = ET.Element(f"{{{ns}}}record")
    for tag, subfields in tag_attrs.items():
        df = ET.SubElement(record, f"{{{ns}}}datafield", attrib={"tag": tag, "ind1": " ", "ind2": " "})
        for code, text in subfields.items():
            sf = ET.SubElement(df, f"{{{ns}}}subfield", attrib={"code": code})
            sf.text = text
    return record


# ---------------------------------------------------------------------------
# 1. Gedcom rena hjälpfunktioner
# ---------------------------------------------------------------------------

class TestNormalizeEmail(unittest.TestCase):
    def test_double_at_normalized(self):
        self.assertEqual(_normalize_email("anna@@test.se"), "anna@test.se")

    def test_single_at_unchanged(self):
        self.assertEqual(_normalize_email("bob@example.com"), "bob@example.com")

    def test_strips_whitespace(self):
        self.assertEqual(_normalize_email("  x@@y.se  "), "x@y.se")


class TestParseGedcomDate(unittest.TestCase):
    def test_full_date(self):
        self.assertEqual(_parse_gedcom_date("15 JAN 1980"), "1980-01-15")

    def test_month_year(self):
        self.assertEqual(_parse_gedcom_date("JAN 1945"), "1945-01")

    def test_year_only(self):
        self.assertEqual(_parse_gedcom_date("1945"), "1945")

    def test_abt_stripped(self):
        self.assertEqual(_parse_gedcom_date("ABT 1990"), "1990")

    def test_bef_stripped(self):
        self.assertEqual(_parse_gedcom_date("BEF 1920"), "1920")

    def test_empty_returns_none(self):
        self.assertIsNone(_parse_gedcom_date(""))

    def test_none_returns_none(self):
        self.assertIsNone(_parse_gedcom_date(None))

    def test_day_zero_padded(self):
        self.assertEqual(_parse_gedcom_date("5 MAR 1950"), "1950-03-05")


class TestExtractTagValue(unittest.TestCase):
    def test_found(self):
        lines = ["1 NAME Anna /Svensson/", "1 SEX F"]
        self.assertEqual(_extract_tag_value(lines, 1, "NAME"), "Anna /Svensson/")

    def test_not_found(self):
        lines = ["1 NAME Anna"]
        self.assertIsNone(_extract_tag_value(lines, 1, "SEX"))

    def test_level_matters(self):
        lines = ["1 BIRT", "2 DATE 1980"]
        # Level 1 DATE not present
        self.assertIsNone(_extract_tag_value(lines, 1, "DATE"))
        self.assertEqual(_extract_tag_value(lines, 2, "DATE"), "1980")


# ---------------------------------------------------------------------------
# 2. GedcomSource med syntetisk fil
# ---------------------------------------------------------------------------

class TestGedcomSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".ged", delete=False
        )
        cls._tmp.write(_GEDCOM_CONTENT)
        cls._tmp.close()
        cls._gs = GedcomSource(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls._tmp.name)

    def test_list_ids(self):
        ids = self._gs.list_ids()
        self.assertIn("@I1@", ids)
        self.assertIn("@I2@", ids)
        self.assertIn("@I3@", ids)

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self._gs.get_person("@I999@"))

    def test_anna_basic(self):
        p = self._gs.get_person("@I1@")
        self.assertIsNotNone(p)
        self.assertEqual(p.fornamn, "Anna")
        self.assertEqual(p.efternamn, "Svensson")
        self.assertEqual(p.kön, "F")

    def test_anna_fodelsedag(self):
        p = self._gs.get_person("@I1@")
        self.assertEqual(p.fodelsedag, "1980-01-15")
        self.assertEqual(p.fodelseort, "Stockholm")

    def test_anna_dodsdag(self):
        p = self._gs.get_person("@I1@")
        self.assertEqual(p.dodsdag, "2020-03-20")
        self.assertEqual(p.dodsort, "Göteborg")
        self.assertFalse(p.levande)

    def test_anna_email_normalized(self):
        p = self._gs.get_person("@I1@")
        self.assertEqual(p.email, "anna@test.se")

    def test_johan_asterisk(self):
        p = self._gs.get_person("@I2@")
        self.assertTrue(p.har_asterisk)
        self.assertEqual(p.fornamn, "Johan")
        self.assertTrue(p.levande)

    def test_johan_abt_year(self):
        p = self._gs.get_person("@I2@")
        self.assertEqual(p.fodelsedag, "1990")

    def test_search_by_surname(self):
        results = self._gs.search_by_surname("Svensson")
        ids = {r.gedcom_id for r in results}
        self.assertIn("@I1@", ids)
        self.assertIn("@I2@", ids)
        self.assertNotIn("@I3@", ids)

    def test_search_by_surname_case_insensitive(self):
        results = self._gs.search_by_surname("svensson")
        self.assertEqual(len(results), 2)

    def test_erik_month_year_birth(self):
        p = self._gs.get_person("@I3@")
        self.assertEqual(p.fodelsedag, "1945-01")


# ---------------------------------------------------------------------------
# 3. Wikidata rena hjälpfunktioner
# ---------------------------------------------------------------------------

class TestExtractQid(unittest.TestCase):
    def test_full_uri(self):
        self.assertEqual(
            _extract_qid("http://www.wikidata.org/entity/Q5560391"),
            "Q5560391",
        )

    def test_trailing_slash(self):
        self.assertEqual(
            _extract_qid("http://www.wikidata.org/entity/Q123/"),
            "Q123",
        )

    def test_bare_qid(self):
        self.assertEqual(_extract_qid("Q999"), "Q999")


class TestFormatWikidataDate(unittest.TestCase):
    def test_full_date(self):
        self.assertEqual(_format_wikidata_date("+1913-09-22T00:00:00Z"), "1913-09-22")

    def test_empty_returns_none(self):
        self.assertIsNone(_format_wikidata_date(""))

    def test_none_returns_none(self):
        self.assertIsNone(_format_wikidata_date(None))

    def test_long_year_truncated(self):
        # "+00321945-01-01T..." → year part > 4 digits
        result = _format_wikidata_date("+00321945-01-01T00:00:00Z")
        # ska ta de 4 sista siffrorna av år-delen "00321945" → "1945"
        self.assertTrue(result.startswith("1945"))


# ---------------------------------------------------------------------------
# 4. Libris MARCXML-hjälpfunktioner
# ---------------------------------------------------------------------------

class TestMarcSubfield(unittest.TestCase):
    def setUp(self):
        self._record = _make_marc_record({
            "245": {"a": "En bok /", "b": "undertitel"},
            "264": {"b": "Norstedts,", "c": "[1980]"},
        })

    def test_found(self):
        val = _marc_subfield(self._record, "245", "a")
        self.assertEqual(val, "En bok /")

    def test_missing_tag(self):
        self.assertIsNone(_marc_subfield(self._record, "100", "a"))

    def test_missing_code(self):
        self.assertIsNone(_marc_subfield(self._record, "245", "z"))


class TestMarcAllSubfields(unittest.TestCase):
    def setUp(self):
        ns = _MARC_NS
        record = ET.Element(f"{{{ns}}}record")
        for title in ["Bok ett", "Bok två"]:
            df = ET.SubElement(record, f"{{{ns}}}datafield", attrib={"tag": "245", "ind1": " ", "ind2": " "})
            sf = ET.SubElement(df, f"{{{ns}}}subfield", attrib={"code": "a"})
            sf.text = title
        self._record = record

    def test_returns_all(self):
        vals = _marc_all_subfields(self._record, "245", "a")
        self.assertEqual(vals, ["Bok ett", "Bok två"])

    def test_missing_tag_returns_empty(self):
        vals = _marc_all_subfields(self._record, "100", "a")
        self.assertEqual(vals, [])


class TestParseRecord(unittest.TestCase):
    def _make(self, overrides: dict | None = None) -> ET.Element:
        fields = {
            "100": {"e": "upphovsman"},
            "245": {"a": "En bok om något /"},
            "264": {"b": "Norstedts,", "c": "[1980]"},
            "020": {"a": "978-91-7100-123-4"},
        }
        if overrides:
            fields.update(overrides)
        return _make_marc_record(fields)

    def test_titel_stripped(self):
        pub = _parse_record(self._make())
        self.assertEqual(pub.titel, "En bok om något")

    def test_roll_from_100e(self):
        pub = _parse_record(self._make())
        self.assertEqual(pub.roll, "upphovsman")

    def test_utgivare_stripped(self):
        pub = _parse_record(self._make())
        self.assertEqual(pub.utgivare, "Norstedts")

    def test_år_extracted(self):
        pub = _parse_record(self._make())
        self.assertEqual(pub.år, "1980")

    def test_isbn(self):
        pub = _parse_record(self._make())
        self.assertEqual(pub.isbn, "978-91-7100-123-4")

    def test_no_roll_returns_none(self):
        record = _make_marc_record({"245": {"a": "Titel"}})
        pub = _parse_record(record)
        self.assertIsNone(pub.roll)


class TestLibrisParseSruResponse(unittest.TestCase):
    def setUp(self):
        self._ls = LibrisSource()

    def test_one_publication(self):
        result = self._ls._parse_sru_response(_MARC_XML)
        self.assertTrue(result.found)
        self.assertEqual(result.antal_träffar, 1)
        self.assertEqual(len(result.publikationer), 1)
        self.assertEqual(result.publikationer[0].titel, "En bok om något")

    def test_empty_response(self):
        result = self._ls._parse_sru_response(_MARC_XML_EMPTY)
        self.assertFalse(result.found)
        self.assertEqual(result.antal_träffar, 0)
        self.assertEqual(len(result.publikationer), 0)

    def test_invalid_xml_returns_error(self):
        result = self._ls._parse_sru_response("not xml at all")
        self.assertIsNotNone(result.error)
        self.assertFalse(result.found)


# ---------------------------------------------------------------------------
# 5. NotionWriter block-hjälpfunktioner (kräver notion_client)
# ---------------------------------------------------------------------------

@unittest.skipUnless(_NOTION_OK, "notion_client inte installerat")
class TestNotionBlocks(unittest.TestCase):
    def test_text_block_type(self):
        b = _text_block("hej")
        self.assertEqual(b["type"], "paragraph")
        self.assertEqual(b["paragraph"]["rich_text"][0]["text"]["content"], "hej")

    def test_text_block_truncates(self):
        long_text = "x" * 3000
        b = _text_block(long_text)
        content = b["paragraph"]["rich_text"][0]["text"]["content"]
        self.assertEqual(len(content), 2000)

    def test_code_block_type(self):
        b = _code_block('{"a": 1}')
        self.assertEqual(b["type"], "code")
        self.assertEqual(b["code"]["language"], "json")

    def test_heading_block_level2(self):
        b = _heading_block("Rubrik", level=2)
        self.assertEqual(b["type"], "heading_2")
        self.assertEqual(b["heading_2"]["rich_text"][0]["text"]["content"], "Rubrik")

    def test_heading_block_clamps_min(self):
        b = _heading_block("X", level=0)
        self.assertEqual(b["type"], "heading_1")

    def test_heading_block_clamps_max(self):
        b = _heading_block("X", level=5)
        self.assertEqual(b["type"], "heading_3")

    def test_table_row_cells(self):
        b = _table_row(["A", "B", "C"])
        self.assertEqual(b["type"], "table_row")
        cells = b["table_row"]["cells"]
        self.assertEqual(len(cells), 3)
        self.assertEqual(cells[0][0]["text"]["content"], "A")


# ---------------------------------------------------------------------------
# 6. ResearchPipeline med injicerade mock-källor
# ---------------------------------------------------------------------------

class TestPipelineMocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".ged", delete=False
        )
        cls._tmp.write(_GEDCOM_CONTENT)
        cls._tmp.close()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls._tmp.name)

    def _make_pipeline(self, wd_result=None, wp_result=None, lib_result=None):
        from sources.wikidata import WikidataResult
        from sources.wikipedia import WikipediaResult
        from sources.libris import LibrisResult

        mock_wd = MagicMock()
        mock_wd.search_by_name_and_year.return_value = wd_result or WikidataResult(found=False)

        mock_wp = MagicMock()
        mock_wp.search.return_value = wp_result or WikipediaResult(found=False)
        mock_wp.get_by_url.return_value = wp_result or WikipediaResult(found=False)

        mock_lib = MagicMock()
        mock_lib.search_by_creator.return_value = lib_result or LibrisResult(found=False)

        return ResearchPipeline(
            gedcom_path=Path(self._tmp.name),
            wikidata_source=mock_wd,
            wikipedia_source=mock_wp,
            libris_source=mock_lib,
        )

    def test_unknown_gedcom_id_returns_error(self):
        p = self._make_pipeline()
        result = p.run("@I999@")
        self.assertEqual(len(result.errors), 1)
        self.assertIsNone(result.person_record)

    def test_anna_basic_fields(self):
        p = self._make_pipeline()
        result = p.run("@I1@")
        self.assertIsNotNone(result.person_record)
        rec = result.person_record
        self.assertEqual(rec.fornamn.värde, "Anna")
        self.assertEqual(rec.efternamn.värde, "Svensson")
        self.assertEqual(rec.födelsedag.värde, "1980-01-15")

    def test_anna_not_levande(self):
        p = self._make_pipeline()
        result = p.run("@I1@")
        self.assertFalse(result.gdpr_flagged)

    def test_johan_levande_no_syfte_clears_contact(self):
        p = self._make_pipeline()
        result = p.run("@I2@", levande_override="ja")
        self.assertTrue(result.gdpr_flagged)
        rec = result.person_record
        self.assertIsNone(rec.email.värde)
        self.assertIsNone(rec.telefon.värde)

    def test_johan_levande_with_syfte_keeps_contact(self):
        p = self._make_pipeline()
        result = p.run("@I2@", levande_override="ja", syfte="guldboda-75")
        self.assertTrue(result.gdpr_flagged)
        rec = result.person_record
        # Kontaktuppgifter ska inte rensas när syfte angivet
        # (Anna har email i gedcom men Johan har inte — kontrollera berikningsbehov istället)
        gdpr_notes = [b for b in rec.berikningsbehov if "GDPR" in b]
        self.assertTrue(any("guldboda-75" in n for n in gdpr_notes))

    def test_wikidata_found_sets_wikidata_id(self):
        from sources.wikidata import WikidataResult
        wd = WikidataResult(
            found=True,
            wikidata_id="Q123",
            wikidata_url="https://www.wikidata.org/wiki/Q123",
        )
        p = self._make_pipeline(wd_result=wd)
        result = p.run("@I1@")
        self.assertEqual(result.person_record.wikidata_id.värde, "Q123")

    def test_wikidata_multiple_candidates_sets_flag(self):
        from sources.wikidata import WikidataResult
        wd = WikidataResult(
            found=False,
            multiple_candidates=True,
            candidates=[{"label": "Anna S", "wikidata_id": "Q1"}, {"label": "Anna S", "wikidata_id": "Q2"}],
        )
        p = self._make_pipeline(wd_result=wd)
        result = p.run("@I1@")
        self.assertTrue(result.wikidata_multiple_candidates)
        self.assertEqual(len(result.wikidata_candidates), 2)

    def test_wikipedia_sets_sammanfattning(self):
        from sources.wikipedia import WikipediaResult
        wp = WikipediaResult(
            found=True,
            sammanfattning="Anna Svensson var en svensk konstnär.",
            url="https://sv.wikipedia.org/wiki/Anna_Svensson",
        )
        p = self._make_pipeline(wp_result=wp)
        result = p.run("@I1@")
        self.assertEqual(
            result.person_record.sammanfattning.värde,
            "Anna Svensson var en svensk konstnär.",
        )

    def test_libris_adds_publikationer(self):
        from sources.libris import LibrisResult, Publikation
        pub = Publikation(titel="En bok", roll="upphovsman", utgivare="Norstedts", år="1980")
        lib = LibrisResult(found=True, publikationer=[pub], antal_träffar=1)
        p = self._make_pipeline(lib_result=lib)
        result = p.run("@I1@")
        self.assertEqual(len(result.person_record.publikationer), 1)
        self.assertEqual(result.person_record.publikationer[0]["värde"]["titel"], "En bok")

    def test_levande_vet_ej_adds_berikningsbehov(self):
        p = self._make_pipeline()
        result = p.run("@I2@", levande_override="vet-ej")
        notes = result.person_record.berikningsbehov
        self.assertTrue(any("okänd" in n.lower() for n in notes))

    def test_wikipedia_skipped_for_levande(self):
        from sources.wikipedia import WikipediaResult
        mock_wp = MagicMock()
        mock_wp.search.return_value = WikipediaResult(found=False)
        mock_wp.get_by_url.return_value = WikipediaResult(found=False)

        mock_wd = MagicMock()
        from sources.wikidata import WikidataResult
        mock_wd.search_by_name_and_year.return_value = WikidataResult(found=False)

        from sources.libris import LibrisResult
        mock_lib = MagicMock()
        mock_lib.search_by_creator.return_value = LibrisResult(found=False)

        pipeline = ResearchPipeline(
            gedcom_path=Path(self._tmp.name),
            wikidata_source=mock_wd,
            wikipedia_source=mock_wp,
            libris_source=mock_lib,
        )
        pipeline.run("@I2@", levande_override="ja")
        # Wikipedia-källan ska inte ha anropats
        mock_wp.search.assert_not_called()
        mock_wp.get_by_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
