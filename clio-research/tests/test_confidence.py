"""
test_confidence.py — Enhetstester för ConfidenceModel (confidence.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from confidence import (
    ConfidenceModel,
    FieldValue,
    FieldSource,
    BASE_CONFIDENCE,
    CONFIDENCE_THRESHOLD,
    CONVERGENCE_CONFIDENCE,
)


@pytest.fixture
def cm():
    return ConfidenceModel()


class TestBaseConfidence:
    def test_gedcom_confidence(self, cm):
        assert cm.base_confidence("gedcom") == 0.95

    def test_wikidata_confidence(self, cm):
        assert cm.base_confidence("wikidata") == 0.60

    def test_wikipedia_confidence(self, cm):
        assert cm.base_confidence("wikipedia") == 0.60

    def test_libris_confidence(self, cm):
        assert cm.base_confidence("libris") == 0.65

    def test_manuell_confidence(self, cm):
        assert cm.base_confidence("manuell") == 0.80

    def test_inferens_confidence(self, cm):
        assert cm.base_confidence("inferens") == 0.30

    def test_unknown_source_returns_zero(self, cm):
        assert cm.base_confidence("okänd_källa") == 0.0


class TestMakeField:
    def test_creates_field_with_correct_value(self, cm):
        fv = cm.make_field("Dag Arvas", "wikidata")
        assert fv.värde == "Dag Arvas"

    def test_creates_field_with_correct_confidence(self, cm):
        fv = cm.make_field("Dag Arvas", "wikidata")
        assert fv.konfidens == 0.60

    def test_creates_field_with_url(self, cm):
        fv = cm.make_field("Q5560391", "wikidata", url="https://www.wikidata.org/wiki/Q5560391")
        assert fv.källa.url == "https://www.wikidata.org/wiki/Q5560391"

    def test_creates_field_with_source_type(self, cm):
        fv = cm.make_field("1945-03-12", "gedcom")
        assert fv.källa.typ == "gedcom"
        assert fv.konfidens == 0.95

    def test_gedcom_field_above_threshold(self, cm):
        fv = cm.make_field("Birgitta", "gedcom")
        assert fv.konfidens >= CONFIDENCE_THRESHOLD

    def test_wikidata_field_below_threshold(self, cm):
        fv = cm.make_field("Stockholm", "wikidata")
        assert fv.konfidens < CONFIDENCE_THRESHOLD


class TestNeedsReview:
    def test_wikidata_field_needs_review(self, cm):
        fv = cm.make_field("Stockholm", "wikidata")
        assert cm.needs_review(fv) is True

    def test_gedcom_field_no_review(self, cm):
        fv = cm.make_field("Birgitta", "gedcom")
        assert cm.needs_review(fv) is False

    def test_empty_field_no_review(self, cm):
        fv = cm.empty_field()
        assert cm.needs_review(fv) is False

    def test_none_value_no_review_even_with_low_confidence(self, cm):
        fv = FieldValue(värde=None, källa=FieldSource(typ="inferens", konfidens=0.30))
        assert fv.needs_review is False


class TestConvergence:
    def test_two_sources_raises_to_convergence(self, cm):
        fv = cm.make_field("Stockholm", "wikidata")
        assert fv.konfidens < CONFIDENCE_THRESHOLD
        fv = cm.apply_convergence(fv, ["wikidata", "wikipedia"])
        assert fv.konfidens == CONVERGENCE_CONFIDENCE

    def test_convergence_above_threshold(self, cm):
        fv = cm.make_field("1932-06-15", "wikidata")
        fv = cm.apply_convergence(fv, ["wikidata", "wikipedia"])
        assert fv.konfidens >= CONFIDENCE_THRESHOLD

    def test_one_source_no_convergence(self, cm):
        fv = cm.make_field("Stockholm", "wikidata")
        original_confidence = fv.konfidens
        fv = cm.apply_convergence(fv, ["wikidata"])
        assert fv.konfidens == original_confidence

    def test_three_sources_still_convergence(self, cm):
        fv = cm.make_field("Sweden", "wikidata")
        fv = cm.apply_convergence(fv, ["wikidata", "wikipedia", "libris"])
        assert fv.konfidens == CONVERGENCE_CONFIDENCE

    def test_convergence_adds_notat(self, cm):
        fv = cm.make_field("Stockholm", "wikidata")
        fv = cm.apply_convergence(fv, ["wikidata", "wikipedia"])
        assert "konvergens" in fv.källa.notat

    def test_convergence_with_no_source_is_safe(self, cm):
        fv = FieldValue(värde="test", källa=None)
        result = cm.apply_convergence(fv, ["wikidata", "wikipedia"])
        assert result.källa is None


class TestEmptyField:
    def test_empty_field_has_none_value(self, cm):
        fv = cm.empty_field()
        assert fv.värde is None

    def test_empty_field_has_none_source(self, cm):
        fv = cm.empty_field()
        assert fv.källa is None

    def test_empty_field_serializes_correctly(self, cm):
        fv = cm.empty_field()
        d = fv.to_dict()
        assert d == {"värde": None, "källa": None}


class TestSerialization:
    def test_field_with_source_serializes(self, cm):
        fv = cm.make_field("Dag", "gedcom", url=None, hämtad="2026-04-05")
        d = fv.to_dict()
        assert d["värde"] == "Dag"
        assert d["källa"]["typ"] == "gedcom"
        assert d["källa"]["konfidens"] == 0.95
        assert d["källa"]["hämtad"] == "2026-04-05"

    def test_field_source_serializes_url(self, cm):
        fv = cm.make_field("Q5560391", "wikidata", url="https://www.wikidata.org/wiki/Q5560391")
        d = fv.to_dict()
        assert d["källa"]["url"] == "https://www.wikidata.org/wiki/Q5560391"
