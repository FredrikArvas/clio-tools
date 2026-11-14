"""
test_research_sources.py — Enhetstester för källformatet (source_model.py), spår 1.

Inga nätverksanrop. Körs en fil i taget: `python -m pytest tests/unit/test_research_sources.py`.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import source_model as sm  # noqa: E402


def make_source(n=3, **overrides) -> dict:
    """En giltig, fullständig källa enligt kontraktet."""
    source = {
        "n": n,
        "source_id": f"openalex:W{n}",
        "title": "Statistical analysis of unidentified aerial phenomena",
        "authors": ["J.-P. Rospars"],
        "year": 2014,
        "doi": "10.1000/xyz",
        "url": "https://example.org/a",
        "database": "openalex",
        "source_type": "konferens",
        "country_codes": ["FR"],
        "institutions": ["CNES"],
        "read_level": "sammanfattning",
        "read_note": "Fulltext inte hämtad än.",
        "text_path": None,
        "abstract": "En sammanfattning.",
        "quotes": [{"text": "ordagrant", "where": "s. 4"}],
        "relevance": {"role": "direkt", "why": "Prövar klassificeringen empiriskt.", "similarity": 0.43},
        "quality": {"citations": 12, "age_years": 12, "assessment": None},
    }
    source.update(overrides)
    return source


RAW_HIT = {
    "source_id": "abc123def4567890",
    "external_id": "W4391389886",
    "title": "  A study  ",
    "authors": ["M. Teodorani", ""],
    "year": 2024,
    "doi": "https://doi.org/10.59661/001C.92684",
    "fulltext_url": "https://doi.org/10.59661/001c.92684",
    "database": "openalex",
    "source_type": "peer-reviewed",
    "country_codes": ["US"],
    "institutions": ["Society for UAP Studies"],
    "abstract": "Text.",
    "citation_count": 5,
    "language": "en",
    "journal": "Limina",
    "region": "US",
    "phase_found": 2,
    "raw_score": None,
}


# ── Råträff → källa ───────────────────────────────────────────────────────────

def test_from_raw_hit_builds_contract_source():
    source = sm.from_raw_hit(RAW_HIT)
    assert source["source_id"] == "openalex:W4391389886"
    assert source["title"] == "A study"
    assert source["authors"] == ["M. Teodorani"]
    assert source["doi"] == "10.59661/001c.92684"
    assert source["url"] == "https://doi.org/10.59661/001c.92684"
    assert source["country_codes"] == ["US"]
    assert source["read_level"] == "sammanfattning"
    assert source["quality"] == {"citations": 5, "age_years": None, "assessment": None}
    assert source["relevance"] == {"role": None, "why": None, "similarity": None}
    assert source["n"] is None
    assert "region" not in source and "raw_score" not in source
    sm.validate_source(source, complete=False)


def test_from_raw_hit_without_metadata_gives_empty_lists_not_guesses():
    raw = {"title": "T", "database": "jstage", "source_id": "hash1", "year": "2001"}
    source = sm.from_raw_hit(raw)
    assert source["country_codes"] == []
    assert source["institutions"] == []
    assert source["source_type"] is None
    assert source["year"] is None
    assert source["read_level"] == "bara titel"
    assert source["source_id"] == "jstage:hash1"
    sm.validate_source(source, complete=False)


@pytest.mark.parametrize("raw, fragment", [
    ({"database": "openalex", "source_id": "x"}, "title saknas"),
    ({"title": "T", "source_id": "x"}, "database saknas"),
    ({"title": "T", "database": "openalex"}, "external_id"),
])
def test_from_raw_hit_rejects_incomplete_hit(raw, fragment):
    with pytest.raises(sm.SourceError) as exc:
        sm.from_raw_hit(raw)
    assert fragment in str(exc.value)


def test_normalize_doi():
    assert sm.normalize_doi("https://doi.org/10.1/ABC") == "10.1/abc"
    assert sm.normalize_doi("doi:10.1/x") == "10.1/x"
    assert sm.normalize_doi("  ") is None
    assert sm.normalize_doi(None) is None


# ── Validering ────────────────────────────────────────────────────────────────

def test_valid_source_passes():
    sm.validate_source(make_source())


def test_valid_source_with_fetch_and_assessment_passes():
    source = make_source(
        read_level="fulltext", read_note=None, text_path="kallor/k03.md",
        fetch={"route": "openalex_pdf", "license": "cc-by", "chars": 70094, "excerpt": "Abstract …", "error": None},
    )
    source["quality"]["assessment"] = {"method": 2, "independence": 3, "falsification": 0, "why": "Kontrollerad studie."}
    sm.validate_source(source)


@pytest.mark.parametrize("change, fragment", [
    ({"n": 0}, "n måste vara ett positivt heltal"),
    ({"n": True}, "n måste vara ett positivt heltal"),
    ({"n": None}, "n är inte satt"),
    ({"title": " "}, "title måste vara"),
    ({"authors": "Rospars"}, "authors måste vara en lista"),
    ({"year": "2014"}, "year måste vara heltal"),
    ({"source_type": "artikel"}, "source_type 'artikel'"),
    ({"country_codes": ["France"]}, "country_codes"),
    ({"country_codes": ["fr"]}, "country_codes"),
    ({"country_codes": None}, "country_codes"),
    ({"read_level": "abstract"}, "read_level 'abstract'"),
    ({"read_note": None}, "read_note måste förklara"),
    ({"read_level": "fulltext"}, "fulltext kräver text_path"),
    ({"text_path": "k03.md"}, "text_path måste ha formen"),
    ({"abstract": None}, "sammanfattning kräver abstract"),
    ({"quotes": [{"text": "x"}]}, "quotes[0]"),
    ({"quotes": [{"text": "", "where": "s. 1"}]}, "quotes[0] har tom"),
    ({"relevance": {"role": "direkt", "why": "x"}}, "relevance måste ha exakt"),
    ({"relevance": {"role": "kanske", "why": "x", "similarity": 0.1}}, "relevance.role 'kanske'"),
    ({"relevance": {"role": "direkt", "why": "", "similarity": 0.1}}, "relevance.why"),
    ({"relevance": {"role": None, "why": None, "similarity": None}}, "relevance.role är inte satt"),
    ({"relevance": {"role": "direkt", "why": "x", "similarity": 1.7}}, "relevance.similarity"),
    ({"quality": {"citations": -1, "age_years": 3, "assessment": None}}, "quality.citations"),
    ({"quality": {"citations": 1, "assessment": None}}, "quality måste ha exakt"),
    ({"fetch": {"route": "scihub", "license": "x", "chars": 1, "excerpt": "", "error": None}}, "fetch.route 'scihub'"),
    ({"fetch": {"route": "none", "license": "unknown", "chars": 0, "excerpt": "x" * 8001, "error": "HTTP 403"}}, "fetch.excerpt"),
    ({"fetch": {"route": "none", "license": "unknown", "chars": 5, "excerpt": "", "error": None}}, "route none"),
    ({"fetch": {"route": "core", "chars": 5, "excerpt": ""}}, "fetch måste ha exakt"),
    ({"credibility_score": 7}, "okänt fält: credibility_score"),
])
def test_invalid_source_names_the_field(change, fragment):
    source = make_source(**change)
    with pytest.raises(sm.SourceError) as exc:
        sm.validate_source(source)
    assert fragment in str(exc.value)


def test_missing_field_is_reported_not_defaulted():
    source = make_source()
    del source["country_codes"]
    with pytest.raises(sm.SourceError) as exc:
        sm.validate_source(source)
    assert "country_codes saknas" in exc.value.problems
    assert "country_codes" not in source


def test_all_problems_are_listed_together():
    source = make_source(year="x", read_level="nej", country_codes=["SWE"])
    with pytest.raises(sm.SourceError) as exc:
        sm.validate_source(source)
    assert len(exc.value.problems) == 3


def test_incomplete_source_allowed_only_when_asked():
    source = make_source(n=None, relevance={"role": None, "why": None, "similarity": None})
    sm.validate_source(source, complete=False)
    with pytest.raises(sm.SourceError):
        sm.validate_source(source, complete=True)


@pytest.mark.parametrize("assessment, level, fragment", [
    ({"method": 4, "independence": 0, "falsification": 0, "why": "x"}, "sammanfattning", "assessment.method"),
    ({"method": 1, "independence": 0, "falsification": 0, "why": ""}, "sammanfattning", "assessment.why"),
    ({"method": 1, "independence": 0, "why": "x"}, "sammanfattning", "assessment måste ha exakt"),
    ({"method": 1, "independence": 0, "falsification": 0, "why": "x"}, "bara titel", "får bara finnas"),
])
def test_assessment_rules(assessment, level, fragment):
    source = make_source(read_level=level, read_note="Skäl.")
    source["quality"]["assessment"] = assessment
    with pytest.raises(sm.SourceError) as exc:
        sm.validate_source(source)
    assert fragment in str(exc.value)


# ── Numrering ─────────────────────────────────────────────────────────────────

def test_assign_numbers_fills_gaps_after_highest_and_keeps_existing():
    sources = [make_source(n=None), make_source(n=4), make_source(n=None)]
    sm.assign_numbers(sources)
    assert [s["n"] for s in sources] == [5, 4, 6]


def test_assign_numbers_respects_numbers_taken_elsewhere():
    sources = [make_source(n=None)]
    sm.assign_numbers(sources, taken={1, 2, 7})
    assert sources[0]["n"] == 8


def test_assign_numbers_rejects_duplicates_and_clash_with_taken():
    with pytest.raises(sm.SourceError, match="n=2 används av flera"):
        sm.assign_numbers([make_source(n=2), make_source(n=2)])
    with pytest.raises(sm.SourceError, match="n=2 används av flera"):
        sm.assign_numbers([make_source(n=2)], taken={2})


def test_text_path_for():
    assert sm.text_path_for(3) == "kallor/k03.md"
    assert sm.text_path_for(112) == "kallor/k112.md"
    with pytest.raises(sm.SourceError):
        sm.text_path_for(0)


# ── Filer ─────────────────────────────────────────────────────────────────────

def test_write_and_read_sources_roundtrip_keeps_swedish_characters(tmp_path):
    sources = [make_source(n=1), make_source(n=3, read_level="ej åtkomlig", read_note="Tryckt källa.", abstract=None)]
    path = sm.write_sources(tmp_path, sources)
    raw = path.read_text(encoding="utf-8")
    assert "ej åtkomlig" in raw
    assert json.loads(raw)["schema"] == "clio-research/sources"
    assert sm.read_sources(tmp_path) == sources
    assert not list(tmp_path.glob("*.tmp"))


def test_write_sources_rejects_duplicate_n_and_writes_nothing(tmp_path):
    with pytest.raises(sm.SourceError, match="n=2 förekommer"):
        sm.write_sources(tmp_path, [make_source(n=2), make_source(n=2)])
    assert not (tmp_path / sm.SOURCES_FILE).exists()


def test_write_sources_rejects_mismatch_and_unjudged(tmp_path):
    mismatch = make_source(relevance={"role": "felträff", "why": "Handlar om fåglar.", "similarity": 0.3})
    with pytest.raises(sm.SourceError, match="felträff hör hemma i 01_filtered.json"):
        sm.write_sources(tmp_path, [mismatch])
    unjudged = make_source(relevance={"role": None, "why": None, "similarity": 0.3})
    with pytest.raises(sm.SourceError, match="relevance.role är inte satt"):
        sm.write_sources(tmp_path, [unjudged])


def test_filtered_roundtrip_and_reason_required(tmp_path):
    by_model = make_source(
        n=2, relevance={"role": "felträff", "why": "Handlar om fåglar.", "similarity": 0.3},
        filtered={"stage": "relevans", "reason": "Handlar om fåglar."},
    )
    by_similarity = make_source(
        n=None, relevance={"role": None, "why": None, "similarity": 0.05},
        filtered={"stage": "likhet", "reason": "Likhet 0.05 under gränsen 0.20."},
    )
    sm.write_filtered(tmp_path, [by_model, by_similarity])
    assert sm.read_filtered(tmp_path) == [by_model, by_similarity]

    no_reason = copy.deepcopy(by_model)
    del no_reason["filtered"]
    with pytest.raises(sm.SourceError, match="filtered med stage och reason saknas"):
        sm.write_filtered(tmp_path, [no_reason])


def test_read_filtered_missing_file_means_nothing_filtered(tmp_path):
    assert sm.read_filtered(tmp_path) == []


def test_read_sources_failures(tmp_path):
    with pytest.raises(FileNotFoundError):
        sm.read_sources(tmp_path)
    path = tmp_path / sm.SOURCES_FILE
    path.write_text("{trasig", encoding="utf-8")
    with pytest.raises(sm.SourceError, match="inte giltig JSON"):
        sm.read_sources(tmp_path)
    path.write_text(json.dumps([make_source()]), encoding="utf-8")
    with pytest.raises(sm.SourceError, match="saknar schema"):
        sm.read_sources(tmp_path)
    path.write_text(json.dumps({"schema": "clio-research/sources", "version": 99, "sources": []}), encoding="utf-8")
    with pytest.raises(sm.SourceError, match="version 99"):
        sm.read_sources(tmp_path)
    payload = {"schema": "clio-research/sources", "version": 1, "sources": [make_source(read_level="x")]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(sm.SourceError, match="read_level 'x'"):
        sm.read_sources(tmp_path)
