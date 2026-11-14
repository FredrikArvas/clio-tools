"""
test_research_connectors.py — Land, institution och källtyp ur sparade API-svar (spår 1).

Fixturerna i tests/fixtures/research/ är riktiga svar från OpenAlex och CrossRef,
sparade 2026-11-14. Inga nätverksanrop: `requests.get` ersätts där en sökning körs.
"""

import copy
import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import source_model as sm  # noqa: E402
from connectors import crossref, metadata, openalex  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "research"
EMAIL = "kontakt.person@example.org"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


# ── OpenAlex ──────────────────────────────────────────────────────────────────

def test_openalex_country_and_institution_from_authorships():
    hit = openalex._normalize(load("openalex_work.json"))
    assert hit["country_codes"] == ["US"]
    assert hit["institutions"] == ["Society for UAP Studies"]
    assert hit["region"] == "US"
    assert hit["source_type"] == "peer-reviewed"
    assert hit["citation_count"] == 5
    assert hit["external_id"] == "W4391389886"


def test_openalex_without_institutions_gives_empty_lists():
    work = load("openalex_work.json")
    for authorship in work["authorships"]:
        authorship["institutions"] = []
        authorship["countries"] = []
    hit = openalex._normalize(work)
    assert hit["country_codes"] == []
    assert hit["institutions"] == []
    assert hit["region"] is None


def test_openalex_hit_becomes_valid_contract_source():
    source = sm.from_raw_hit(openalex._normalize(load("openalex_work.json")))
    assert source["source_id"] == "openalex:W4391389886"
    sm.validate_source(source, complete=False)


@pytest.mark.parametrize("work_type, venue_type, expected", [
    ("article", "journal", "peer-reviewed"),
    ("review", "journal", "peer-reviewed"),
    ("article", "conference", "konferens"),
    ("article", "repository", "preprint"),
    ("article", None, None),
    ("preprint", "repository", "preprint"),
    ("book-chapter", "ebook platform", "bok"),
    ("report", None, "rapport"),
    ("dataset", "repository", None),
    ("paratext", "journal", None),
    (None, None, None),
])
def test_openalex_source_type(work_type, venue_type, expected):
    assert metadata.openalex_source_type(work_type, venue_type) == expected


def test_openalex_search_requests_the_fields_it_reads(monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None, **kwargs):
        seen.update(params)
        return FakeResponse({"results": [load("openalex_work.json")]})

    monkeypatch.setattr(openalex.requests, "get", fake_get)
    monkeypatch.setattr(openalex.time, "sleep", lambda s: None)
    hits = openalex.search("uap", max_results=5)
    assert len(hits) == 1
    for field in ("authorships", "type", "cited_by_count", "primary_location"):
        assert field in seen["select"].split(",")


# ── CrossRef ──────────────────────────────────────────────────────────────────

def test_crossref_country_only_when_affiliation_names_it():
    hit = crossref._normalize(load("crossref_work_affil.json")["message"])
    assert hit["country_codes"] == ["US", "CA", "GB", "ES"]
    assert "Galileo Project, 60 Garden Street, Cambridge, MA, USA 02138" in hit["institutions"]
    assert hit["source_type"] == "peer-reviewed"
    assert hit["citation_count"] == 17
    assert hit["external_id"] == "10.1142/s2251171723400068"


def test_crossref_affiliation_without_country_gives_institutions_but_no_country():
    hit = crossref._normalize(load("crossref_work_nocountry.json")["message"])
    assert hit["country_codes"] == []
    assert "Wellesley College" in hit["institutions"]
    assert hit["region"] is None


def test_crossref_without_affiliation_gives_empty_lists_and_types_from_api():
    hits = [crossref._normalize(item) for item in load("crossref_search.json")["message"]["items"]]
    assert all(h["country_codes"] == [] and h["institutions"] == [] for h in hits)
    assert [h["source_type"] for h in hits] == ["bok", "bok", "preprint", "bok", "bok"]


def test_crossref_unknown_type_is_none():
    item = copy.deepcopy(load("crossref_work_affil.json")["message"])
    item["type"] = "component"
    assert crossref._normalize(item)["source_type"] is None


@pytest.mark.parametrize("affiliation, expected", [
    ("Galileo Project, 60 Garden Street, Cambridge, MA, USA 02138", "US"),
    ("Human Flourishing Program Harvard University  Cambridge Massachusetts USA", "US"),
    ("Athabasca University, 1 University Dr., Athabasca, AB, Canada T9S 3A3", "CA"),
    ("University of Aberdeen Meston Building, Aberdeen, Scotland, UK AB24 3UE", "GB"),
    ("CNES, Toulouse, France", "FR"),
    ("Uppsala universitet, Sverige.", "SE"),
    ("University of New Mexico", None),
    ("Department of Physics, University of Georgia", None),
    ("Division of Physics University of Kyoto", None),
    ("Independent Scholar", None),
    ("France", None),
    ("", None),
])
def test_country_from_affiliation(affiliation, expected):
    assert metadata.country_from_affiliation(affiliation) == expected


# ── Kontaktadressen ───────────────────────────────────────────────────────────

def test_crossref_sends_contact_in_header_only_and_never_logs_it(monkeypatch, caplog):
    monkeypatch.setenv("CLIO_CONTACT_EMAIL", EMAIL)
    calls = []

    def failing_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers})
        raise crossref.requests.ConnectionError(f"Max retries exceeded for {url}?mailto={EMAIL}")

    monkeypatch.setattr(crossref.requests, "get", failing_get)
    monkeypatch.setattr(crossref.time, "sleep", lambda s: None)
    with caplog.at_level(logging.DEBUG):
        assert crossref.search("uap") == []

    assert EMAIL in calls[0]["headers"]["User-Agent"]
    assert EMAIL not in json.dumps(calls[0]["params"])
    assert EMAIL not in calls[0]["url"]
    assert "misslyckades" in caplog.text
    assert EMAIL not in caplog.text


def test_crossref_without_contact_sends_no_address(monkeypatch):
    monkeypatch.delenv("CLIO_CONTACT_EMAIL", raising=False)
    assert crossref._headers() == {"User-Agent": crossref.USER_AGENT}
