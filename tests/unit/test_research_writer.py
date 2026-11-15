"""
test_research_writer.py — Enhetstester för analyssteget S2 (report_writer.py), spår 2.

Modellen ersätts av en låtsaslöpare som returnerar ett färdigt svar. Inga modell- eller
nätverksanrop; Word-testet med riktig md2docx hoppas över om node_modules saknas.
Körs en fil i taget: `python -m pytest tests/unit/test_research_writer.py`.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import report_lint as rl  # noqa: E402
import report_writer as rw  # noqa: E402
import source_model as sm  # noqa: E402
from claude_runner import MODEL_ANALYST, MODEL_ANALYST_QUICK, ClaudeResult  # noqa: E402

TODAY = "2026-11-15"
FULLTEXT_3 = ("Introduction. Rospars argues that the classification of witness reports into "
              "categories A to D depends on the information available to the investigator. End.")


def source(n, **kw):
    s = {
        "n": n, "source_id": f"openalex:W{n}", "title": f"Titel {n}", "authors": ["A. Författare"],
        "year": 2014, "doi": f"10.1000/{n}", "url": f"https://example.org/{n}", "database": "openalex",
        "source_type": "peer-reviewed", "country_codes": [], "institutions": [],
        "read_level": "sammanfattning", "read_note": "Fulltext inte hämtad.", "text_path": None, "abstract": "Abstract.",
        "quotes": [], "relevance": {"role": "direkt", "why": "Hör till frågan.", "similarity": 0.4},
        "quality": {"citations": 1, "age_years": 12, "assessment": None},
    }
    s.update(kw)
    return s


def make_sources():
    return [
        source(3, title="Statistical analysis of UAP", authors=["J.-P. Rospars"], country_codes=["FR"],
               read_level="fulltext", read_note=None, text_path="kallor/k03.md",
               fetch={"route": "openalex_pdf", "license": "cc-by", "chars": len(FULLTEXT_3),
                      "excerpt": FULLTEXT_3[:80], "error": None}),
        source(7, title="The UFO Handbook", authors=["A. Hendry"], country_codes=["US"], year=1979,
               abstract="Most reports were identified as known objects."),
        source(9, title="Galileo satellite navigation", read_level="bara titel", abstract=None,
               relevance={"role": "bakgrund", "why": "Namnlikhet.", "similarity": 0.2}),
    ]


@pytest.fixture
def run_dir(tmp_path):
    sm.write_sources(tmp_path, make_sources())
    (tmp_path / "kallor").mkdir()
    (tmp_path / "kallor" / "k03.md").write_text(FULLTEXT_3, encoding="utf-8")
    return tmp_path


PROTOCOL = {
    "protocol_id": "clio-research-021",
    "question": {"natural_language": "Är UAP-klassificeringarnas kategorier ömsesidigt uteslutande?",
                 "sub_questions": ["Är kategorierna ömsesidigt uteslutande?"]},
    "output": {"niva": "standard"},
}

REPORT = """# Klassificering av UAP-observationer

## Kort svar

Klassningen beror på informationen i rapporterna [3]. Enligt sammanfattningen identifierades de flesta rapporter [7].

## Evidensläge

| Delfråga | Bedömning (1–5) | Säkerhet | Viktigaste källor |
|---|---|---|---|
| A. Uteslutande kategorier | 2 | låg | [3] |

## Fråga och avgränsning

- A. Är kategorierna ömsesidigt uteslutande?

## Fynd

### Uteslutande kategorier

Rospars skriver “the classification of witness reports into categories A to D” (klassningen av vittnesrapporter i kategorierna A till D) [3].

## Motbild

Hendry visar enligt sammanfattningen att de flesta rapporter fick en förklaring [7].

## Luckor

### Luckor i forskningen

Vi har inte funnit någon mätning av samstämmighet i OpenAlex eller CrossRef.

### Det vi inte kunde läsa

Källan om satellitnavigering fanns bara som titel.
"""

REGISTER = {
    "claims": [
        {"id": "P1", "claim": "Klassningen beror på informationen.", "subquestion": "A", "sources": [3],
         "quote": "classification of witness reports into categories A to D", "read_level": "fulltext",
         "status": "belagt"},
        {"id": "P2", "claim": "De flesta rapporter identifierades.", "subquestion": "A", "sources": [7],
         "quote": "Most reports were identified", "read_level": "sammanfattning", "status": "belagt"},
    ],
    "sources_used": [{"n": 3, "role": "direkt", "stance": None}, {"n": 7, "role": "bakgrund", "stance": None}],
    "unused": [{"n": 9, "why": "Handlar om satellitnavigering."}],
}


def response(report=REPORT, register=REGISTER, end=True, fence=False):
    reg = json.dumps(register, ensure_ascii=False)
    if fence:
        reg = f"```json\n{reg}\n```"
    return f"{rw.MARK_REPORT}\n{report}\n{rw.MARK_REGISTER}\n{reg}\n" + (rw.MARK_END if end else "")


class FakeRunner:
    """Ersätter claude_runner.run_claude. Returnerar svaren i tur och ordning."""

    def __init__(self, *texts, status="ok", output_tokens=8000):
        self.texts = list(texts)
        self.calls = []
        self.status = status
        self.output_tokens = output_tokens

    def __call__(self, role, prompt, model, workdir, system_prompt=None, **kw):
        self.calls.append({"role": role, "prompt": prompt, "model": model, "workdir": workdir,
                           "system": system_prompt})
        text = self.texts.pop(0) if self.texts else ""
        return ClaudeResult(self.status, text=text, model=model, message="" if self.status == "ok" else "fel",
                            usage={"output_tokens": self.output_tokens})


def protocol(**kw):
    p = json.loads(json.dumps(PROTOCOL))
    p.update(kw)
    return p


# ── Protokoll och underlag ────────────────────────────────────────────────────

def test_protocol_view_reads_old_json():
    v = rw.protocol_view(protocol(hypothesis={"primary": "H1", "adversarial": "H0"}))
    assert v["level"] == "standard" and v["spread"] == "intern"
    assert v["hypothesis"] == "H1"
    assert v["subquestions"] == ["Är kategorierna ömsesidigt uteslutande?"]


def test_protocol_view_rejects_unknown_level():
    with pytest.raises(ValueError):
        rw.protocol_view(protocol(niva="lång"))


def test_load_sources_strict_and_prov(tmp_path):
    prov = make_sources()
    prov[0]["relevance"] = {"role": None, "why": None, "similarity": None}
    (tmp_path / sm.SOURCES_FILE).write_text(json.dumps({"schema": "clio-research/prov", "version": 1,
                                                        "sources": prov}), encoding="utf-8")
    with pytest.raises(sm.SourceError):
        rw.load_sources(tmp_path)
    assert len(rw.load_sources(tmp_path, complete=False)) == 3


# ── Prompt ────────────────────────────────────────────────────────────────────

def test_prompt_contains_sources_and_rules():
    system, user = rw.build_prompts(rw.protocol_view(protocol()), make_sources(), rw.load_prompts())
    assert "rapporten konstaterar" in system.lower()          # tonen ur prompts.yaml
    assert rw.MARK_REPORT in system and rw.MARK_END in system
    assert "[3] Statistical analysis of UAP" in user
    assert "Läsnivå: fulltext." in user and "Läsnivå: bara titel." in user
    assert "Land: okänt" in user                                # källa 9 saknar land
    assert FULLTEXT_3[:80] in user                              # utdraget
    assert "- A. Är kategorierna ömsesidigt uteslutande?" in user
    assert "ingen uttalad hypotes" in user and "Skriv ingen tabell eller kolumn med" in user
    assert "- Metod" not in user and "- Källförteckning" not in user


def test_prompt_with_hypothesis_asks_for_stance():
    system, user = rw.build_prompts(rw.protocol_view(protocol(hypothesis="H1")), make_sources(),
                                    rw.load_prompts())
    assert '"stödjer" | "neutral" | "avvisar"' in system
    assert "stödjer, är neutral till eller avvisar" in user


def test_prompt_sections_follow_level():
    prompts = rw.load_prompts()
    _, quick = rw.build_prompts(rw.protocol_view(protocol(niva="snabb")), make_sources(), prompts)
    _, share = rw.build_prompts(rw.protocol_view(protocol(niva="delbar")), make_sources(), prompts)
    assert "- Fråga och avgränsning\n" not in quick and "punktlista" in quick
    assert "Vad en människa bör kontrollera" in share


# ── Uppdelning av svaret ──────────────────────────────────────────────────────

def test_parse_response_ok():
    report, register, complete, problems = rw.parse_response(response())
    assert report.startswith("# Klassificering") and complete and problems == []
    assert register["claims"][0]["id"] == "P1"


def test_parse_response_fenced_json():
    _, register, _, problems = rw.parse_response(response(fence=True))
    assert problems == [] and len(register["claims"]) == 2


def test_parse_response_without_end_is_incomplete():
    _, _, complete, _ = rw.parse_response(response(end=False))
    assert complete is False


def test_parse_response_bad_json_is_problem():
    text = f"{rw.MARK_REPORT}\n# T\n{rw.MARK_REGISTER}\n{{\"claims\": [\n{rw.MARK_END}"
    _, register, _, problems = rw.parse_response(text)
    assert register["claims"] == [] and "JSON" in problems[0]


def test_parse_response_without_report_marker_raises():
    with pytest.raises(rw.ResponseError):
        rw.parse_response("# Bara text")


def test_strip_code_sections():
    md, removed = rw.strip_code_sections("# T\n\n## Fynd\n\nText.\n\n## Källförteckning\n\n[1] X.\n")
    assert removed == ["Källförteckning"] and "[1] X." not in md and "## Fynd" in md


# ── analyse, check och revise ─────────────────────────────────────────────────

def test_analyse_writes_draft_claims_and_raw(run_dir):
    runner = FakeRunner(response())
    draft = rw.analyse(run_dir, protocol(), runner=runner, today=TODAY)
    assert draft.ok and draft.version == 1
    assert (run_dir / "02_draft_v1.md").exists() and (run_dir / "02_response_v1.txt").exists()
    claims = json.loads((run_dir / "02_claims_v1.json").read_text(encoding="utf-8"))
    assert claims["schema"] == "clio-research/claims" and len(claims["claims"]) == 2
    call = runner.calls[0]
    assert call["role"] == "analyst" and call["model"] == MODEL_ANALYST and call["workdir"] == run_dir


def test_quick_level_uses_quick_model(run_dir):
    runner = FakeRunner(response())
    rw.analyse(run_dir, protocol(niva="snabb"), runner=runner, today=TODAY)
    assert runner.calls[0]["model"] == MODEL_ANALYST_QUICK


def test_good_response_passes_lint(run_dir):
    draft = rw.analyse(run_dir, protocol(), runner=FakeRunner(response()), today=TODAY)
    lint = rw.check(run_dir, protocol(), draft)
    assert lint.status == "PASS", lint.requirements()
    assert (run_dir / "03_lint_v1.md").exists()


@pytest.mark.parametrize("level", ["snabb", "delbar"])
def test_good_response_passes_lint_other_levels(run_dir, level):
    report = REPORT
    if level == "snabb":
        report = report.replace("## Fråga och avgränsning\n\n- A. Är kategorierna ömsesidigt uteslutande?\n\n", "")
    if level == "delbar":
        report += "\n### Vad en människa bör kontrollera\n\nLäs källa 7 i fulltext.\n"
    draft = rw.analyse(run_dir, protocol(niva=level), runner=FakeRunner(response(report)), today=TODAY)
    lint = rw.check(run_dir, protocol(niva=level), draft)
    assert lint.status == "PASS", lint.requirements()


def test_assembled_draft_metadata_and_footer(run_dir):
    draft = rw.analyse(run_dir, protocol(spridning="delbar"), runner=FakeRunner(response()), today=TODAY)
    md = draft.markdown
    assert "Datum: 2026-11-15. Nivå: standard. Spridning: delbar. Protokoll: clio-research-021." in md
    assert "får spridas i oförändrat skick" in md and "© 2026" in md
    intern = rw.analyse(run_dir, protocol(), runner=FakeRunner(response()), today=TODAY).markdown
    assert "för internt bruk" in intern


def test_references_only_cited_with_read_level(run_dir):
    md = rw.analyse(run_dir, protocol(), runner=FakeRunner(response()), today=TODAY).markdown
    refs = md.split("## Källförteckning")[1].split("## Bilagor")[0]
    assert "[3] J.-P. Rospars (2014)." in refs and "Läsnivå: fulltext." in refs
    assert "[7]" in refs and "[9]" not in refs
    assert "Land enligt metadata: FR." in refs and "None" not in md
    assert "Roll: direkt." in refs and "Ställningstagande" not in md


def test_appendix_register_and_unused(run_dir):
    md = rw.analyse(run_dir, protocol(), runner=FakeRunner(response()), today=TODAY).markdown
    appendix = md.split("## Bilagor")[1]
    assert "| P1 | Klassningen beror på informationen. | A | [3] | fulltext | belagt |" in appendix
    assert "| 9 | Galileo satellite navigation | Handlar om satellitnavigering. |" in appendix
    assert "Citat |" not in appendix and "Söklogg" not in appendix


def test_delbar_appendix_has_quotes_and_search_log(run_dir):
    md = rw.analyse(run_dir, protocol(niva="delbar"), runner=FakeRunner(response()), today=TODAY).markdown
    assert "| Citat |" in md and "### Söklogg" in md


def test_snabb_has_no_appendix(run_dir):
    md = rw.analyse(run_dir, protocol(niva="snabb"), runner=FakeRunner(response()), today=TODAY).markdown
    assert "## Bilagor" not in md and "Nivå snabb, analys med" in md


def test_model_written_references_are_replaced(run_dir):
    report = REPORT + "\n## Källförteckning\n\n[3] Påhittad. None.\n"
    md = rw.analyse(run_dir, protocol(), runner=FakeRunner(response(report)), today=TODAY).markdown
    assert "Påhittad" not in md and md.count("## Källförteckning") == 1


def test_truncated_response_is_revise(run_dir):
    draft = rw.analyse(run_dir, protocol(), runner=FakeRunner(response(end=False)), today=TODAY)
    lint = rw.check(run_dir, protocol(), draft)
    assert "R06" in lint.rules_hit() and lint.status == "REVISE"


def test_invented_quote_and_source_are_revise(run_dir):
    register = json.loads(json.dumps(REGISTER))
    register["claims"][0]["quote"] = "no study has measured agreement"
    report = REPORT.replace("informationen i rapporterna [3].", "informationen i rapporterna [3, 12].")
    draft = rw.analyse(run_dir, protocol(), runner=FakeRunner(response(report, register)), today=TODAY)
    lint = rw.check(run_dir, protocol(), draft)
    assert {"R17", "R07", "R09"} <= lint.rules_hit()


def test_failed_call_gives_must(run_dir):
    draft = rw.analyse(run_dir, protocol(), runner=FakeRunner("", status="limit"), today=TODAY)
    assert not draft.ok
    lint = rw.check(run_dir, protocol(), draft)
    assert lint.status == "REVISE" and "R00" in lint.rules_hit()


def test_revise_sends_requirements_and_previous_draft(run_dir):
    rw.analyse(run_dir, protocol(), runner=FakeRunner(response(end=False)), today=TODAY)
    runner = FakeRunner(response())
    draft = rw.revise(run_dir, protocol(), ["MÅSTE [R06 avbrutet-svar] svaret: Skriv kortare."],
                      previous=1, runner=runner, today=TODAY)
    prompt = runner.calls[0]["prompt"]
    assert "1. MÅSTE [R06 avbrutet-svar] svaret: Skriv kortare." in prompt
    assert "Föregående rapport:" in prompt and "# Klassificering av UAP-observationer" in prompt
    assert draft.version == 2 and (run_dir / "02_draft_v2.md").exists()


def test_write_report_revises_until_pass(run_dir):
    runner = FakeRunner(response(end=False), response())
    draft, lint = rw.write_report(run_dir, protocol(), runner=runner, revisions=1, today=TODAY)
    assert len(runner.calls) == 2 and draft.version == 2 and lint.status == "PASS"
    assert (run_dir / "03_lint_v1.md").exists() and (run_dir / "03_lint_v2.md").exists()


def test_write_report_stops_after_max_revisions(run_dir):
    runner = FakeRunner(response(end=False), response(end=False))
    draft, lint = rw.write_report(run_dir, protocol(), runner=runner, revisions=1, today=TODAY)
    assert len(runner.calls) == 2 and lint.status == "REVISE"


# ── Word ──────────────────────────────────────────────────────────────────────

def test_word_not_built_for_snabb(tmp_path):
    assert rw.build_word(tmp_path / "x.md", "snabb", runner=lambda *a, **k: pytest.fail("körd")) is None


def test_word_command_uses_aiab_profile(tmp_path):
    calls = []

    def fake(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    out = rw.build_word(tmp_path / "02_draft_v1.md", "standard", script=tmp_path / "md2docx.js", runner=fake)
    cmd, kw = calls[0]
    assert cmd[0] == "node" and cmd[-2:] == ["--profile", "aiab"]
    assert out == tmp_path / "02_draft_v1.docx" and kw["cwd"] == str(tmp_path)


def test_word_failure_raises(tmp_path):
    def fake(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "Cannot find module 'docx'")

    with pytest.raises(rw.WordError):
        rw.build_word(tmp_path / "x.md", "delbar", script=tmp_path / "md2docx.js", runner=fake)


@pytest.mark.skipif(not (rw.MD2DOCX.parent / "node_modules").exists(), reason="clio-docx/node_modules saknas")
def test_word_real_md2docx(run_dir):
    draft = rw.analyse(run_dir, protocol(), runner=FakeRunner(response()), today=TODAY)
    out = rw.build_word(draft.md_path, "standard")
    assert out.exists() and out.stat().st_size > 2000
