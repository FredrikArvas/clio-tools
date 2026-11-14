"""
test_research_quality.py — Relevansbedömning och källkvalitet (spår 1).

Inga nätverksanrop och inga modellanrop: embeddningen ersätts av en fejk, och
insamlarmodellens svar är förbestämda listor.
"""

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import credibility_scorer as cs  # noqa: E402
import relevance_filter as rf  # noqa: E402
import source_model as sm  # noqa: E402


def make_source(n, title="Titel", **overrides) -> dict:
    source = sm.from_raw_hit({
        "title": title, "database": "openalex", "external_id": f"W{n}",
        "abstract": "Sammanfattning.", "year": 2014, "citation_count": 12,
        "country_codes": ["FR"], "institutions": ["CNES"],
    })
    source["n"] = n
    source.update(overrides)
    return source


def verdict(n, role="direkt", why="Hör till frågan."):
    return {"n": n, "role": role, "why": why}


# ── Grovsållning ──────────────────────────────────────────────────────────────

def fake_embed(texts):
    """Frågan pekar längs x-axeln; källor med 'fågel' i titeln längs y-axeln."""
    return [[0.0, 1.0] if "fågel" in t else [1.0, 0.1] for t in texts]


def test_coarse_filter_sets_similarity_and_moves_low_ones_with_reason():
    sources = [make_source(1, "UAP-klassificering"), make_source(2, "En fågel i skogen")]
    kept, dropped = rf.coarse_filter(sources, "Hur klassificeras UAP?", embed_fn=fake_embed)

    assert [s["n"] for s in kept] == [1]
    assert [s["n"] for s in dropped] == [2]
    assert kept[0]["relevance"]["similarity"] == pytest.approx(1.0, abs=1e-3)
    assert "filtered" not in kept[0]
    assert dropped[0]["relevance"]["similarity"] == pytest.approx(0.0995, abs=1e-3)
    assert dropped[0]["filtered"]["stage"] == "likhet"
    assert "under gränsen 0.20" in dropped[0]["filtered"]["reason"]
    sm.validate_filtered(dropped)


def test_coarse_filter_embedding_failure_keeps_all_without_invented_similarity(caplog):
    def broken(texts):
        raise RuntimeError("Ollama svarar inte")

    sources = [make_source(1), make_source(2)]
    kept, dropped = rf.coarse_filter(sources, "fråga", embed_fn=broken)
    assert kept == sources and dropped == []
    assert all(s["relevance"]["similarity"] is None for s in sources)
    assert "ingen grovsållning gjord" in caplog.text


def test_coarse_filter_empty_input():
    assert rf.coarse_filter([], "fråga", embed_fn=fake_embed) == ([], [])


# ── Relevansbedömning ─────────────────────────────────────────────────────────

def test_apply_verdicts_sets_role_and_moves_mismatches_with_reason_kept(tmp_path):
    sources = [make_source(1), make_source(2), make_source(3)]
    sources[1]["relevance"]["similarity"] = 0.31
    reply = [
        verdict(1, "direkt", "Prövar klassificeringen empiriskt."),
        verdict(2, "felträff", "Handlar om   fågelsträck, inte UAP."),
        verdict(3, "analogi", "Samma metodproblem inom medicinsk diagnostik."),
    ]
    kept, mismatches = rf.apply_verdicts(sources, reply)

    assert [s["n"] for s in kept] == [1, 3]
    assert kept[0]["relevance"] == {"role": "direkt", "why": "Prövar klassificeringen empiriskt.", "similarity": None}
    assert [s["n"] for s in mismatches] == [2]
    moved = mismatches[0]
    assert moved["relevance"] == {"role": "felträff", "why": "Handlar om fågelsträck, inte UAP.", "similarity": 0.31}
    assert moved["filtered"] == {"stage": "relevans", "reason": "Handlar om fågelsträck, inte UAP."}

    sm.write_sources(tmp_path, kept)
    sm.write_filtered(tmp_path, mismatches)
    assert [s["n"] for s in sm.read_sources(tmp_path)] == [1, 3]
    assert sm.read_filtered(tmp_path)[0]["filtered"]["reason"] == "Handlar om fågelsträck, inte UAP."


def test_apply_verdicts_accepts_model_text_with_code_fence():
    sources = [make_source(1)]
    reply = 'Här är bedömningen:\n```json\n[{"n": 1, "role": "bakgrund", "why": "Ger historiken."}]\n```\nKlart.'
    kept, mismatches = rf.apply_verdicts(sources, reply)
    assert kept[0]["relevance"]["role"] == "bakgrund"
    assert mismatches == []


def test_parse_verdicts_finds_bare_list_in_text():
    assert rf.parse_verdicts('Svar: [{"n": 1, "role": "direkt", "why": "x"}] slut') == [
        {"n": 1, "role": "direkt", "why": "x"}
    ]


@pytest.mark.parametrize("reply, fragment", [
    ("Jag kan inte bedöma detta.", "ingen JSON-lista"),
    ("[{trasig]", "inte giltig JSON"),
    ('```json\n{"n": 1}\n```', "inte en lista"),
    (42, "varken lista eller text"),
])
def test_parse_verdicts_rejects_unusable_reply(reply, fragment):
    with pytest.raises(rf.RelevanceError) as exc:
        rf.parse_verdicts(reply)
    assert fragment in str(exc.value)


@pytest.mark.parametrize("reply, fragment", [
    ([verdict(1), verdict(2, role="kanske")], "role 'kanske'"),
    ([verdict(1), verdict(2, why="  ")], "why saknas"),
    ([verdict(1)], "bedömning saknas för n=2"),
    ([verdict(1), verdict(2), verdict(9)], "ingen källa har det numret"),
    ([verdict(1), verdict(2), verdict(2, "felträff")], "bedöms mer än en gång"),
    ([verdict(1), {"n": "2", "role": "direkt", "why": "x"}], "n måste vara ett heltal"),
    ([verdict(1), "n=2 direkt"], "är inte ett objekt"),
])
def test_apply_verdicts_rejects_bad_reply_and_changes_nothing(reply, fragment):
    sources = [make_source(1), make_source(2)]
    before = copy.deepcopy(sources)
    with pytest.raises(rf.RelevanceError) as exc:
        rf.apply_verdicts(sources, reply)
    assert fragment in str(exc.value)
    assert sources == before


def test_apply_verdicts_lists_every_problem():
    sources = [make_source(1), make_source(2), make_source(3)]
    with pytest.raises(rf.RelevanceError) as exc:
        rf.apply_verdicts(sources, [verdict(1, role="x"), verdict(2, why="")])
    assert len(exc.value.problems) == 3


def test_apply_verdicts_requires_numbered_sources():
    with pytest.raises(rf.RelevanceError, match="saknar n"):
        rf.apply_verdicts([make_source(None)], [])


# ── Äldre flöde ───────────────────────────────────────────────────────────────

def test_legacy_filter_by_relevance_still_works_on_raw_hits(monkeypatch):
    monkeypatch.setattr(rf, "embed", fake_embed)
    raw = [{"title": "En fågel", "abstract": ""}, {"title": "UAP", "abstract": "x"}]
    selected = rf.filter_by_relevance(raw, "fråga")
    assert [s["title"] for s in selected] == ["UAP"]
    assert selected[0]["relevance_score"] == pytest.approx(1.0, abs=1e-3)


# ── Källkvalitet ──────────────────────────────────────────────────────────────

def test_assess_counts_age_and_keeps_citations_and_leaves_assessment_null():
    source = cs.assess(make_source(1), current_year=2026)
    assert source["quality"] == {"citations": 12, "age_years": 12, "assessment": None}
    assert "credibility_score" not in source
    sm.validate_source(source, complete=False)


def test_assess_without_year_or_citations_gives_null_not_zero():
    source = make_source(1, year=None)
    source["quality"]["citations"] = None
    cs.assess(source, current_year=2026)
    assert source["quality"] == {"citations": None, "age_years": None, "assessment": None}


def test_assess_future_year_and_bad_citations_give_null():
    source = make_source(1, year=2031)
    source["quality"]["citations"] = -3
    cs.assess(source, current_year=2026)
    assert source["quality"]["age_years"] is None
    assert source["quality"]["citations"] is None


def test_assess_keeps_analysts_assessment():
    source = make_source(1)
    given = {"method": 2, "independence": 3, "falsification": 1, "why": "Kontrollerad studie."}
    source["quality"]["assessment"] = given
    cs.assess(source, current_year=2026)
    assert source["quality"]["assessment"] == given


def test_quality_ignores_abstract_keywords():
    plain = cs.assess(make_source(1, abstract="An anecdote."), current_year=2026)
    loaded = cs.assess(make_source(2, abstract="A randomized double-blind replicated meta-analysis with equations, "
                                               "funded by nobody, null result."), current_year=2026)
    assert plain["quality"] == loaded["quality"]


def test_geographic_spread_counts_per_set_and_separates_unknown():
    sources = [
        make_source(1, country_codes=["FR"]),
        make_source(2, country_codes=["FR", "US", "FR"]),
        make_source(3, country_codes=[]),
    ]
    assert cs.geographic_spread(sources) == {"countries": {"FR": 2, "US": 1}, "known": 2, "unknown": 1}
    assert cs.geographic_spread([]) == {"countries": {}, "known": 0, "unknown": 0}


def test_legacy_score_all_keeps_main_py_fields_without_keyword_scoring():
    raw = [
        {"title": "A", "abstract": "randomized replicated equation", "year": 1990, "citation_count": 40},
        {"title": "B", "abstract": None, "year": None},
    ]
    scored = cs.score_all(raw)
    assert scored is raw
    assert raw[0]["credibility_breakdown"] == {"temporal_stability": 3}
    assert raw[0]["credibility_score"] == 3
    assert raw[0]["quality"]["citations"] == 40
    assert raw[0]["quality"]["assessment"] is None
    assert raw[1]["credibility_score"] == 0
    assert raw[1]["quality"] == {"citations": None, "age_years": None, "assessment": None}
    # Äldre anropare sorterar på poängen och räknar med den.
    sorted(raw, key=lambda s: s.get("credibility_score", 0))
    assert cs.score_all(raw, raw) is raw
