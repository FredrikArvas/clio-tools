"""
test_pipeline.py — Integrationstester mot externa API:er.

OBS: Dessa tester gör riktiga nätverksanrop (Wikidata, Wikipedia, Libris).
De är långsamma (~10-30s) och kräver internetanslutning.

Kör med: python -m pytest tests/test_pipeline.py -v -s
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from sources.wikidata import WikidataSource, WikidataResult
from sources.wikipedia import WikipediaSource, WikipediaResult
from sources.libris import LibrisSource, LibrisResult


@pytest.fixture(scope="module")
def ws_wikidata():
    return WikidataSource()


@pytest.fixture(scope="module")
def ws_wikipedia():
    return WikipediaSource()


@pytest.fixture(scope="module")
def ls_libris():
    return LibrisSource()


# --- Wikidata ---

class TestWikidataGetByQId:
    def test_dag_arvas_found(self, ws_wikidata):
        r = ws_wikidata.get_by_q_id("Q5560391")
        assert r.found is True

    def test_dag_arvas_label(self, ws_wikidata):
        r = ws_wikidata.get_by_q_id("Q5560391")
        assert "Arvas" in (r.label or "")

    def test_dag_arvas_fodelsedag(self, ws_wikidata):
        r = ws_wikidata.get_by_q_id("Q5560391")
        assert r.fodelsedag is not None
        assert "1913" in r.fodelsedag

    def test_dag_arvas_wikipedia_sv(self, ws_wikidata):
        r = ws_wikidata.get_by_q_id("Q5560391")
        assert r.wikipedia_sv is not None
        assert "sv.wikipedia.org" in r.wikipedia_sv

    def test_nonexistent_qid(self, ws_wikidata):
        r = ws_wikidata.get_by_q_id("Q99999999999")
        assert r.found is False

    def test_not_multiple_candidates_for_single(self, ws_wikidata):
        r = ws_wikidata.get_by_q_id("Q5560391")
        assert r.multiple_candidates is False


class TestWikidataSearch:
    def test_birgitta_arvas_not_found_or_multiple(self, ws_wikidata):
        r = ws_wikidata.search_by_name_and_year("Birgitta", "Arvas", "1945")
        # Ska returnera found=False eller multiple_candidates=True (ADR-004)
        assert r.found is False or r.multiple_candidates is True

    def test_invalid_year(self, ws_wikidata):
        r = ws_wikidata.search_by_name_and_year("Test", "Person", "INVALID")
        assert r.error is not None or r.found is False


# --- Wikipedia ---

class TestWikipediaSearch:
    def test_dag_arvas_found(self, ws_wikipedia):
        r = ws_wikipedia.search("Dag Arvas")
        assert r.found is True

    def test_dag_arvas_title(self, ws_wikipedia):
        r = ws_wikipedia.search("Dag Arvas")
        assert "Arvas" in (r.title or "")

    def test_dag_arvas_has_extract(self, ws_wikipedia):
        r = ws_wikipedia.search("Dag Arvas")
        assert r.sammanfattning is not None
        assert len(r.sammanfattning) > 20

    def test_dag_arvas_url(self, ws_wikipedia):
        r = ws_wikipedia.search("Dag Arvas")
        assert r.url is not None
        assert "wikipedia.org" in r.url

    def test_birgitta_arvas_not_found(self, ws_wikipedia):
        # Birgitta Arvas har ingen personartikel
        r = ws_wikipedia.search("Birgitta Arvas")
        assert r.found is False

    def test_get_by_url_sv(self, ws_wikipedia):
        r = ws_wikipedia.get_by_url("https://sv.wikipedia.org/wiki/Dag_Arvas")
        assert r.found is True
        assert "Arvas" in (r.title or "")

    def test_get_by_url_en(self, ws_wikipedia):
        r = ws_wikipedia.get_by_url("https://en.wikipedia.org/wiki/Dag_Arvas")
        assert r.found is True


# --- Libris ---

class TestLibrisSearch:
    def test_birgitta_arvas_found(self, ls_libris):
        r = ls_libris.search_by_creator("Arvas", "Birgitta")
        assert r.found is True

    def test_birgitta_arvas_har_publikationer(self, ls_libris):
        r = ls_libris.search_by_creator("Arvas", "Birgitta")
        assert len(r.publikationer) >= 1

    def test_birgitta_arvas_antal(self, ls_libris):
        r = ls_libris.search_by_creator("Arvas", "Birgitta")
        assert r.antal_träffar >= 1

    def test_birgitta_arvas_publikation_har_titel(self, ls_libris):
        r = ls_libris.search_by_creator("Arvas", "Birgitta")
        titlar = [p.titel for p in r.publikationer if p.titel]
        assert len(titlar) >= 1

    def test_dag_arvas_publikationer(self, ls_libris):
        r = ls_libris.search_by_creator("Arvas", "Dag")
        # Dag Arvas har skrifter i Libris
        assert r.found is True
