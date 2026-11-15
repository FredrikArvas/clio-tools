"""
test_research_collect.py — Enhetstester för insamlingssteget S1 (collector.py).

Connectorer, inbäddning, fulltextkedja, CrossRef och modell är simulerade. Inga nät-
eller modellanrop. Körs en fil i taget: `python -m pytest tests/unit/test_research_collect.py`.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import collector  # noqa: E402
import source_model as sm  # noqa: E402
from claude_runner import MODEL_COLLECTOR, ClaudeResult  # noqa: E402

YEAR = 2026


def raw(i, title, doi=None, abstract="Ett abstrakt.", db="openalex"):
    return {"source_id": f"sha{i}", "external_id": f"W{i}", "title": title, "authors": ["A. Forskare"],
            "year": 2014, "doi": doi, "database": db, "abstract": abstract, "citation_count": 3,
            "country_codes": ["FR"], "institutions": ["CNES"], "source_type": "peer-reviewed"}


PHASE_HITS = {
    1: [raw(1, "Nära källa ett", doi="10.1/a"), raw(2, "Nära källa två"), raw(3, "Fjärran om fiskar")],
    2: [raw(4, "Nära källa ett, dubblett", doi="10.1/A"), raw(5, "Nära men felträff")],
    3: [raw(6, "Nära regional källa")],
}


def protocol(niva="standard", **kw):
    p = {
        "protocol_id": "clio-research-099", "niva": niva, "spridning": "intern", "format": "md",
        "question": {"natural_language": "Fråga om klassificering?", "sub_questions": ["Delfråga A"]},
        "hypothesis": None, "scope": "", "context": "",
        "search_strategy": {"phases": [
            {"phase": 1, "label": "Primärkällor", "databases": ["openalex"], "max_results": 20},
            {"phase": 2, "label": "Bred", "databases": ["openalex", "crossref"], "max_results": 100},
            {"phase": 3, "label": "Regional", "databases": ["jstage"], "max_results": 30},
            {"phase": 5, "label": "Citation chase"},
        ]},
        "primary_sources": [{"source": "Hynek 1972", "where": "", "priority": "Hög"}],
        "web_targets": [{"database": "Google Scholar", "term": "Hynek review", "purpose": "kritik"}],
        "direct_urls": ["https://example.org/rapport.pdf"],
    }
    p.update(kw)
    return p


class Fakes:
    def __init__(self, replies=(), status="ok"):
        self.replies = list(replies)
        self.status = status
        self.prompts = []
        self.phases = []
        self.fetched = []
        self.crossref = {"10.9/web": {"DOI": "10.9/WEB", "title": ["Riktig titel ur CrossRef"],
                                      "author": [{"given": "Ana", "family": "Ruiz"}],
                                      "published": {"date-parts": [[2019]]}, "type": "journal-article",
                                      "container-title": ["Journal of Tests"], "is-referenced-by-count": 7}}
        self.crossref_calls = []

    def search(self, phase, protocol, seen):
        self.phases.append(phase)
        return [dict(h) for h in PHASE_HITS.get(phase["phase"], [])]

    @staticmethod
    def embed(texts):
        return [[1.0, 0.0]] + [[0.0, 1.0] if "Fjärran" in t else [1.0, 0.1] for t in texts[1:]]

    def fetch(self, sources, run_dir, level):
        for s in sources:
            self.fetched.append((s["n"], level))
            path = Path(run_dir) / sm.text_path_for(s["n"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"Text för {s['title']}", encoding="utf-8")
            s.update(read_level="fulltext", read_note=None, text_path=sm.text_path_for(s["n"]))
            s["fetch"] = {"route": "openalex_pdf", "license": "cc-by", "chars": 20,
                          "excerpt": f"Utdrag {s['n']}", "error": None}
        return sources

    def crossref_get(self, url):
        self.crossref_calls.append(url)
        return self.crossref.get(url.rsplit("/works/", 1)[1])

    def runner(self, role, prompt, model, workdir, system_prompt=None, max_turns=None, **kw):
        assert role == "collector" and model == MODEL_COLLECTOR
        self.prompts.append(prompt)
        text = self.replies.pop(0) if self.replies else ""
        return ClaudeResult(self.status, text=text, model=model,
                            usage={"input_tokens": 1000, "output_tokens": 200}, cost_usd=0.01,
                            message="You've hit your usage limit" if self.status == "limit" else "")

    def collect(self, run_dir, proto):
        return collector.collect(run_dir, proto, runner=self.runner, search_fn=self.search, embed_fn=self.embed,
                                 fetch_fn=self.fetch, crossref_get=self.crossref_get, current_year=YEAR)


def reply(verdicts, finds=()):
    return "Här är svaret:\n```json\n" + json.dumps({"bedomning": verdicts, "webbfynd": list(finds)},
                                                   ensure_ascii=False) + "\n```"


def verdicts_for(n_roles):
    return [{"n": n, "role": r, "why": f"Motivering för {n}."} for n, r in n_roles]


# kept efter grovsållning: n1 "Nära källa ett", n2 "Nära källa två", n3 "Nära men felträff",
# n4 "Nära regional källa". "Fjärran om fiskar" sorteras bort på likhet, dubbletten (DOI) försvinner.
GOOD = verdicts_for([(1, "direkt"), (2, "analogi"), (3, "felträff"), (4, "bakgrund")])
FINDS = [
    {"title": "Påhittad titel från modellen", "url": "https://x.org", "doi": "10.9/web",
     "role": "direkt", "why": "Fynd med DOI.", "query": "q"},
    {"title": "GEIPAN årsrapport", "url": "https://www.geipan.fr/rapport", "doi": None,
     "role": "bakgrund", "why": "Myndighetsrapport.", "query": "geipan"},
    {"title": "Saknas i CrossRef", "url": None, "doi": "10.9/finns-inte", "role": "direkt", "why": "x", "query": "q"},
    {"title": "Dubblett", "url": None, "doi": "10.1/a", "role": "direkt", "why": "x", "query": "q"},
    {"title": "Felträff på webben", "url": "https://y.org", "doi": None, "role": "felträff", "why": "x", "query": "q"},
]


def test_s1_merges_indexes_web_and_moves_mismatches(tmp_path):
    f = Fakes([reply(GOOD, FINDS)])
    res = f.collect(tmp_path, protocol())
    assert res.is_ok, res.message

    sources = sm.read_sources(tmp_path)              # validerar mot kontraktet
    filtered = sm.read_filtered(tmp_path)
    by_title = {s["title"]: s for s in sources}
    assert [s["n"] for s in sources] == [1, 2, 4, 5, 6]
    assert by_title["Nära källa ett"]["relevance"] == {"role": "direkt", "why": "Motivering för 1.", "similarity": 0.995}
    assert "Nära källa ett, dubblett" not in by_title

    # felträffen behåller sitt n i 01_filtered.json; likhetsbortfallet saknar n
    stages = {s["title"]: (s["n"], s["filtered"]["stage"]) for s in filtered}
    assert stages["Nära men felträff"] == (3, "relevans")
    assert stages["Fjärran om fiskar"] == (None, "likhet")

    # webbfynd: metadata ur CrossRef, aldrig ur modellens svar
    web_doi = by_title["Riktig titel ur CrossRef"]
    assert web_doi["n"] == 5 and web_doi["doi"] == "10.9/web" and web_doi["authors"] == ["Ana Ruiz"]
    assert web_doi["year"] == 2019 and web_doi["database"] == "crossref"
    assert "Påhittad titel från modellen" not in by_title
    web_url = by_title["GEIPAN årsrapport"]
    assert web_url["database"] == "webb" and web_url["source_type"] == "webb" and web_url["n"] == 6

    # samma fulltextkedja för webbfynden, på samma nivå
    assert sorted(f.fetched) == [(1, "standard"), (2, "standard"), (3, "standard"), (4, "standard"),
                                 (5, "standard"), (6, "standard")]
    assert (tmp_path / "kallor" / "k06.md").exists()
    assert res.counts["web"] == 2 and res.counts["web_rejected"] == 3 and res.counts["mismatches"] == 1

    md = (tmp_path / "01_sources.md").read_text(encoding="utf-8")
    assert "Saknas i CrossRef: DOI:n gick inte att slå upp i CrossRef" in md
    assert "| 3 | Nära men felträff | relevans |" in md


def test_prompt_has_sources_and_web_task(tmp_path):
    f = Fakes([reply(GOOD)])
    f.collect(tmp_path, protocol())
    prompt = f.prompts[0]
    assert "[1] Nära källa ett (2014)" in prompt and "Utdrag 1" in prompt
    assert "Hynek 1972" in prompt and "https://example.org/rapport.pdf" in prompt
    assert "Google Scholar: Hynek review" in prompt and "högst 10 fynd" in prompt
    assert "Fjärran om fiskar" not in prompt


def test_delbar_asks_for_more_languages(tmp_path):
    f = Fakes([reply(GOOD)])
    f.collect(tmp_path, protocol("delbar"))
    assert "flera språk" in f.prompts[0] and "högst 20 fynd" in f.prompts[0]


def test_snabb_skips_web_and_late_phases(tmp_path):
    f = Fakes([reply(verdicts_for([(1, "direkt"), (2, "direkt"), (3, "felträff")]), FINDS)])
    res = f.collect(tmp_path, protocol("snabb"))
    assert res.is_ok
    assert [p["phase"] for p in f.phases] == [1, 2]
    assert f.phases[1]["max_results"] == 50                       # halverat på snabb
    assert "Sök inte på webben" in f.prompts[0] and "Hynek 1972" not in f.prompts[0]
    assert res.counts["web"] == 0 and f.crossref_calls == []
    assert {lvl for _, lvl in f.fetched} == {"snabb"}


def test_invalid_reply_is_retried_once(tmp_path):
    f = Fakes(["inget json här", reply(GOOD)])
    res = f.collect(tmp_path, protocol())
    assert res.is_ok and len(res.calls) == 2
    assert "Ditt förra svar gick inte att använda" in f.prompts[1]


def test_reply_missing_a_source_is_retried(tmp_path):
    f = Fakes([reply(GOOD[:2]), reply(GOOD)])
    res = f.collect(tmp_path, protocol())
    assert res.is_ok and "bedömning saknas för n=3, 4" in f.prompts[1]


def test_invalid_twice_is_error_without_files(tmp_path):
    f = Fakes(["fel", "fel igen"])
    res = f.collect(tmp_path, protocol())
    assert res.status == "error" and len(res.calls) == 2
    assert not (tmp_path / sm.SOURCES_FILE).exists()


def test_limit_pauses_and_rerun_uses_checkpoint(tmp_path):
    f = Fakes(status="limit")
    res = f.collect(tmp_path, protocol())
    assert res.status == "limit" and "prenumerationsgräns" in res.message
    assert (tmp_path / collector.CANDIDATES_FILE).exists()
    assert not (tmp_path / sm.SOURCES_FILE).exists()

    g = Fakes([reply(GOOD)])
    res = g.collect(tmp_path, protocol())
    assert res.is_ok
    assert g.phases == [] and g.fetched == []                     # ingen ny sökning eller hämtning
    assert len(sm.read_sources(tmp_path)) == 3


def test_cap_by_level_moves_the_least_similar():
    sources = [{"title": str(i), "relevance": {"similarity": i / 100}} for i in range(20)]
    kept, over = collector.cap_by_level(sources, "snabb")
    assert len(kept) == 15 and len(over) == 5
    assert {s["title"] for s in over} == {"0", "1", "2", "3", "4"}
    assert all(s["filtered"]["stage"] == "likhet" for s in over)


def test_cap_without_embedding_says_so():
    sources = [{"title": str(i), "relevance": {"similarity": None}} for i in range(20)]
    kept, over = collector.cap_by_level(sources, "snabb")
    assert [s["title"] for s in kept] == [str(i) for i in range(15)]
    assert "Ingen likhet beräknad" in over[0]["filtered"]["reason"]


def test_crossref_lookup_uses_python_metadata():
    f = Fakes()
    raw_hit = collector.crossref_lookup("10.9/web", f.crossref_get)
    assert raw_hit["title"] == "Riktig titel ur CrossRef" and raw_hit["journal"] == "Journal of Tests"
    assert f.crossref_calls == ["https://api.crossref.org/works/10.9/web"]
    assert collector.crossref_lookup("10.9/saknas", f.crossref_get) is None


def test_parse_reply_variants():
    v, w = collector.parse_reply('{"bedomning": [], "webbfynd": []}')
    assert v == [] and w == []
    with pytest.raises(Exception):
        collector.parse_reply('{"webbfynd": []}')
