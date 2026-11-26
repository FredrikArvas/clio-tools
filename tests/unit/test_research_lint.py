"""
test_research_lint.py — Enhetstester för rapportkontrollen (report_lint.py), spår 2.

Varje regel har en lyckad och en misslyckad väg. Rapport 021 är fixtur för den
misslyckade vägen. Inga modell- eller nätverksanrop.
Körs en fil i taget: `python -m pytest tests/unit/test_research_lint.py`.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import report_lint as rl  # noqa: E402

FIXTURE_021 = ROOT / "tests" / "fixtures" / "research" / "report_021.md"

KALLA_3 = ("Rospars argues that the classification of witness reports into categories A to D "
           "depends on the information available to the investigator.")


def good_report(level="standard", extra_body="", refs=None, appendix=True) -> str:
    """En rapport som klarar alla regler på given nivå."""
    refs = refs if refs is not None else [
        "[3] Rospars J.-P. (2014). *Statistical analysis of UAP*. Källtyp: konferens. Land: FR. Läsnivå: fulltext.",
        "[7] Hendry A. (1979). *The UFO Handbook*. Källtyp: bok. Läsnivå: sammanfattning.",
    ]
    parts = [
        "# Klassificering av UAP-observationer",
        "",
        "Datum: 2026-11-15. Nivå: " + level + ".",
        "",
        "## Kort svar",
        "",
        "Klassningen beror på informationen i rapporterna [3]. Vi har inte funnit mätningar av samstämmighet [7].",
        "",
        "## Evidensläge",
        "",
        "| Delfråga | Bedömning | Säkerhet | Källor |",
        "|---|---|---|---|",
        "| A. Uteslutande kategorier | 2 | låg | [3] |",
        "",
    ]
    if level != "snabb":
        parts += ["## Fråga och avgränsning", "", "- A. Är kategorierna ömsesidigt uteslutande?", ""]
    parts += [
        "## Fynd",
        "",
        "### Uteslutande kategorier",
        "",
        "Rospars skriver “the classification of witness reports into categories A to D” (klassningen "
        "av vittnesrapporter i kategorierna A till D) [3].",
        extra_body,
        "",
        "## Motbild",
        "",
        "Enligt sammanfattningen identifierades de flesta rapporter [7].",
        "",
        "## Luckor",
        "",
        "- Vi har inte funnit någon mätning i OpenAlex eller CrossRef.",
        "",
        "## Metod",
        "",
        "Nivå " + level + ", två källor citerade.",
        "",
        "## Källförteckning",
        "",
        *refs,
        "",
    ]
    if appendix and level != "snabb":
        parts += ["## Bilagor", "", "### Påståenderegister", "",
                  "| Id | Påstående | Källor | Status |", "|---|---|---|---|",
                  "| P1 | Klassningen beror på informationen. | [3] | belagt |", ""]
    parts += ["---", "", "*Arvas International AB, 2026-11-15.*", ""]
    return "\n".join(parts)


def make_sources():
    return [
        {"n": 3, "title": "Statistical analysis of UAP", "read_level": "fulltext",
         "text_path": "kallor/k03.md", "abstract": "Short abstract.", "country_codes": ["FR"], "quotes": []},
        {"n": 7, "title": "The UFO Handbook", "read_level": "sammanfattning", "text_path": None,
         "abstract": "Most reports were identified as known objects.", "country_codes": ["US"], "quotes": []},
    ]


def good_claims():
    return [{"id": "P1", "claim": "Klassningen beror på informationen.", "subquestion": "A",
             "sources": [3], "quote": "classification of witness reports into categories A to D",
             "read_level": "fulltext", "status": "belagt"}]


@pytest.fixture
def run_dir(tmp_path):
    (tmp_path / "kallor").mkdir()
    (tmp_path / "kallor" / "k03.md").write_text(
        "Intro.\n" + KALLA_3.replace("classification", "classi-\nfication") + "\nMore.", encoding="utf-8")
    return tmp_path


def lint(md, **kw):
    kw.setdefault("level", "standard")
    kw.setdefault("has_hypothesis", False)
    return rl.lint_report(md, **kw)


def rules(result):
    return result.rules_hit()


# ── Hela rapporten ────────────────────────────────────────────────────────────

def test_good_report_passes_all_rules(run_dir):
    r = lint(good_report(), sources=make_sources(), claims=good_claims(), run_dir=run_dir,
             response={"complete": True, "output_tokens": 9000})
    assert r.findings == [], [f.as_requirement() for f in r.findings]
    assert r.status == "PASS"


def test_good_snabb_report_passes():
    r = lint(good_report("snabb"), level="snabb", sources=make_sources(), claims=[])
    assert r.status == "PASS", r.requirements()


def test_unknown_level_raises():
    with pytest.raises(ValueError):
        rl.lint_report("# T", level="lång")


# ── Rapport 021 ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def r021():
    return rl.lint_report(FIXTURE_021.read_text(encoding="utf-8"), level="standard", has_hypothesis=False)


def test_021_is_revise(r021):
    assert r021.status == "REVISE"


def test_021_finds_truncated_sections(r021):
    places = [f.place for f in r021.findings if f.rule.startswith("R05")]
    for line in (153, 190, 244):
        assert any(p.startswith(f"rad {line},") for p in places), places


def test_021_finds_empty_section_2_3(r021):
    empty = [f.place for f in r021.findings if f.rule.startswith("R04")]
    assert any("2.3 Evidenskluster 2" in p for p in empty)


def test_021_finds_uncited_sources(r021):
    f = next(f for f in r021.findings if f.rule.startswith("R08"))
    assert "45 poster" in f.action


def test_021_finds_none_in_region_column(r021):
    f = next(f for f in r021.findings if f.rule.startswith("R11") and "ställningstaganden" in f.place)
    assert "None" in f.action


def test_021_other_known_faults(r021):
    assert {"R01", "R03", "R10", "R12", "R13", "R14", "R15", "R16"} <= rules(r021)


# ── R01–R03 rubriker ──────────────────────────────────────────────────────────

def test_r01_one_h1_ok():
    assert "R01" not in rules(lint(good_report()))


def test_r01_two_h1_fails():
    assert "R01" in rules(lint(good_report() + "\n# Ny titel\n\nText.\n"))


def test_r01_heading_in_code_block_ignored():
    md = good_report(extra_body="```\n# inte en rubrik\n```")
    assert "R01" not in rules(lint(md))


def test_r02_no_skipped_level_ok():
    assert "R02" not in rules(lint(good_report()))


def test_r02_skipped_level_fails():
    md = good_report().replace("### Uteslutande kategorier", "#### Uteslutande kategorier")
    assert "R02" in rules(lint(md))


def test_r03_plain_titles_ok():
    assert "R03" not in rules(lint(good_report()))


@pytest.mark.parametrize("title", ["## 4. Fynd", "## Sektion 0 – Fynd", "### 2.3 Kluster"])
def test_r03_numbered_title_fails(title):
    md = good_report().replace("## Fynd", title) if title.startswith("## ") else \
        good_report().replace("### Uteslutande kategorier", title)
    assert "R03" in rules(lint(md))


# ── R04–R05 avsnitt ───────────────────────────────────────────────────────────

def test_r04_parent_with_children_is_not_empty():
    assert "R04" not in rules(lint(good_report()))


def test_r04_empty_section_fails():
    md = good_report().replace("## Motbild\n", "### Tomt\n\n---\n\n## Motbild\n")
    r = lint(md)
    assert any(f.rule.startswith("R04") and "Tomt" in f.place for f in r.findings)


def test_r05_ends_with_punctuation_or_table_ok():
    assert "R05" not in rules(lint(good_report()))


@pytest.mark.parametrize("ending", ["Källorna [18],", "inte mellan bedö", "se källa [3]"])
def test_r05_truncated_section_fails(ending):
    md = good_report().replace("Enligt sammanfattningen identifierades de flesta rapporter [7].", ending)
    assert "R05" in rules(lint(md))


def test_r05_bold_and_quote_endings_ok():
    md = good_report().replace("rapporter [7].", "rapporter [7].**")
    assert "R05" not in rules(lint(md))


# ── R06 avbrutet svar ─────────────────────────────────────────────────────────

def test_r06_complete_response_ok():
    assert "R06" not in rules(lint(good_report(), response={"complete": True, "output_tokens": 12000}))


@pytest.mark.parametrize("response", [
    {"complete": False, "output_tokens": 100},
    {"complete": True, "output_tokens": 31900},
    {"complete": True, "stop_reason": "max_tokens"},
])
def test_r06_cut_response_fails(response):
    assert "R06" in rules(lint(good_report(), response=response))


def test_r06_skipped_without_response():
    r = lint(good_report())
    assert any(s.startswith("R06") for s in r.skipped)


# ── R07–R09, R16 källor ───────────────────────────────────────────────────────

def test_r07_all_citations_listed_ok():
    assert "R07" not in rules(lint(good_report()))


def test_r07_citation_missing_from_list_fails():
    md = good_report(extra_body="Ett påstående till [9].")
    r = lint(md)
    assert any(f.rule.startswith("R07") and "[9]" in f.place for f in r.findings)


def test_r07_ranges_are_expanded():
    md = good_report(extra_body="Flera källor [3–7].")
    r = lint(md)
    assert {"[4]", "[5]", "[6]"} <= {f.place.split(", ")[-1] for f in r.findings if f.rule.startswith("R07")}


def test_r08_every_entry_cited_ok():
    assert "R08" not in rules(lint(good_report()))


def test_r08_uncited_entry_fails():
    refs = ["[3] A (2014). *T*. Läsnivå: fulltext.", "[7] B (1979). *U*. Läsnivå: fulltext.",
            "[12] C (2001). *Galileo satellites*. Läsnivå: bara titel."]
    r = lint(good_report(refs=refs))
    f = next(f for f in r.findings if f.rule.startswith("R08"))
    assert "12" in f.action


def test_r08_appendix_citations_do_not_count():
    body, appendix = good_report().split("## Bilagor")
    body = body.replace(" [7].", ".")
    md = body + "## Bilagor" + appendix.replace("| [3] | belagt |", "| [3], [7] | belagt |")
    r = lint(md)
    assert any(f.rule.startswith("R08") and "(7)" in f.action for f in r.findings)


def test_r09_citations_in_sources_ok():
    assert "R09" not in rules(lint(good_report(), sources=make_sources()))


def test_r09_invented_source_fails():
    sources = [s for s in make_sources() if s["n"] != 7]
    r = lint(good_report(), sources=sources)
    assert any(f.rule.startswith("R09") and "7" in f.action for f in r.findings)


def test_r16_read_level_in_references_ok():
    assert "R16" not in rules(lint(good_report()))


def test_r16_missing_read_level_fails():
    refs = ["[3] A (2014). *T*. Läsnivå: fulltext.", "[7] B (1979). *U*."]
    assert "R16" in rules(lint(good_report(refs=refs)))


# ── R10 obligatoriska avsnitt ─────────────────────────────────────────────────

@pytest.mark.parametrize("level", ["snabb", "standard", "delbar"])
def test_r10_required_sections_ok(level):
    assert "R10" not in rules(lint(good_report(level), level=level))


def test_r10_missing_section_fails():
    md = good_report().replace("## Motbild", "### Motbild")
    r = lint(md)
    assert any(f.rule.startswith("R10") and "Motbild" in f.place for f in r.findings)


def test_r10_missing_appendix_on_standard_fails():
    assert "R10" in rules(lint(good_report(appendix=False)))


def test_r10_wrong_order_fails():
    md = good_report()
    a = md.index("## Motbild")
    b = md.index("## Luckor")
    c = md.index("## Metod")
    md = md[:a] + md[b:c] + md[a:b] + md[c:]
    r = lint(md)
    assert any(f.rule.startswith("R10") and f.place == "avsnittsordningen" for f in r.findings)


# ── R11 tomma värden ──────────────────────────────────────────────────────────

def test_r11_clean_tables_ok():
    assert "R11" not in rules(lint(good_report()))


@pytest.mark.parametrize("cell", ["None", "?", "Okänd titel"])
def test_r11_bad_table_cell_fails(cell):
    md = good_report().replace("| låg | [3] |", f"| {cell} | [3] |")
    assert "R11" in rules(lint(md))


def test_r11_bad_reference_entry_fails():
    refs = ["[3] None (2014). *Okänd titel*. Läsnivå: fulltext.", "[7] B (1979). *U*. Läsnivå: fulltext."]
    assert "R11" in rules(lint(good_report(refs=refs)))


def test_r11_question_mark_in_prose_ok():
    md = good_report(extra_body="Är kategorierna uteslutande? Det prövas här [3].")
    assert "R11" not in rules(lint(md))


# ── R12 dubbla citat ──────────────────────────────────────────────────────────

def test_r12_unique_quotes_ok():
    assert "R12" not in rules(lint(good_report()))


def test_r12_repeated_quote_fails():
    md = good_report(extra_body="Igen: “the classification of witness reports into categories A to D” "
                                "(en annan översättning) [3].")
    assert "R12" in rules(lint(md))


def test_r12_quote_in_appendix_not_counted():
    md = good_report() + "\n### Citat\n\n“the classification of witness reports into categories A to D”.\n"
    assert "R12" not in rules(lint(md))


# ── R13 negativa slutsatser ───────────────────────────────────────────────────

def test_r13_we_have_not_found_ok():
    assert "R13" not in rules(lint(good_report()))


@pytest.mark.parametrize("phrase", ["Det finns ingen sådan studie [3].", "Ingen studie har mätt detta [3].",
                                    "Det finns inga mätningar [3]."])
def test_r13_negative_conclusion_warns(phrase):
    r = lint(good_report(extra_body=phrase))
    f = next(f for f in r.findings if f.rule.startswith("R13"))
    assert f.level == rl.SHOULD
    assert r.status == "PASS"


# ── R14 emojier och token-räkning ─────────────────────────────────────────────

def test_r14_plain_text_ok():
    assert "R14" not in rules(lint(good_report()))


@pytest.mark.parametrize("text", ["Stödjer 🟢 [3].", "📊 Tokens: ~1200 (svar)."])
def test_r14_emoji_or_tokens_fails(text):
    assert "R14" in rules(lint(good_report(extra_body=text)))


# ── R15 ställningstagande utan hypotes ────────────────────────────────────────

STANCE_TABLE = "| Källa | Ställningstagande |\n|---|---|\n| [3] | stödjer |"


def test_r15_stance_allowed_with_hypothesis():
    assert "R15" not in rules(lint(good_report(extra_body=STANCE_TABLE), has_hypothesis=True))


def test_r15_stance_without_hypothesis_fails():
    assert "R15" in rules(lint(good_report(extra_body=STANCE_TABLE), has_hypothesis=False))


def test_r15_role_column_without_hypothesis_ok():
    table = "| Källa | Roll i rapporten |\n|---|---|\n| [3] | direkt |"
    assert "R15" not in rules(lint(good_report(extra_body=table), has_hypothesis=False))


# ── R17–R19 påståenderegistret ────────────────────────────────────────────────

def test_r17_quote_found_in_fulltext_ok(run_dir):
    r = lint(good_report(), sources=make_sources(), claims=good_claims(), run_dir=run_dir)
    assert not {"R17", "R18", "R19"} & rules(r)


def test_r17_quote_found_in_abstract_ok(run_dir):
    claims = [{"id": "P2", "claim": "De flesta identifierades.", "sources": [7],
               "quote": "Most reports were identified", "read_level": "sammanfattning", "status": "belagt"}]
    assert "R17" not in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


def test_r17_quote_with_ellipsis_ok(run_dir):
    claims = good_claims()
    claims[0]["quote"] = "classification of witness reports … depends on the information"
    assert "R17" not in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


def test_r17_belagt_without_quote_fails(run_dir):
    claims = good_claims()
    claims[0]["quote"] = ""
    assert "R17" in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


def test_r17_invented_quote_fails(run_dir):
    claims = good_claims()
    claims[0]["quote"] = "no study has ever measured inter-rater agreement"
    assert "R17" in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


def test_r17_partial_claim_needs_no_quote(run_dir):
    claims = good_claims()
    claims[0].update(quote="", status="delvis")
    assert "R17" not in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


def test_r18_unknown_source_fails(run_dir):
    claims = good_claims()
    claims[0]["sources"] = [3, 99]
    assert "R18" in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


def test_r18_overclaimed_read_level_fails(run_dir):
    claims = [{"id": "P2", "claim": "x", "sources": [7], "quote": "Most reports were identified",
               "read_level": "fulltext", "status": "belagt"}]
    assert "R18" in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


@pytest.mark.parametrize("bad", [{"status": "säkert"}, {"sources": "3"}, {"read_level": "läst"}, {"claim": ""}])
def test_r18_bad_format_fails(run_dir, bad):
    claims = good_claims()
    claims[0].update(bad)
    assert "R18" in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


def test_r18_empty_register_fails_on_standard():
    assert "R18" in rules(lint(good_report(), sources=make_sources(), claims=[]))


def test_r19_convergence_with_two_countries_ok(run_dir):
    claims = [{"id": "P3", "claim": "Geografisk konvergens mellan Frankrike och USA.", "sources": [3, 7],
               "quote": "", "read_level": "sammanfattning", "status": "delvis"}]
    assert "R19" not in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


def test_r19_convergence_with_one_country_fails(run_dir):
    claims = [{"id": "P3", "claim": "Fynden visar geografisk konvergens.", "sources": [3],
               "quote": "", "read_level": "fulltext", "status": "delvis"}]
    assert "R19" in rules(lint(good_report(), sources=make_sources(), claims=claims, run_dir=run_dir))


# ── R20 längd ─────────────────────────────────────────────────────────────────

def test_r20_short_snabb_ok():
    assert "R20" not in rules(lint(good_report("snabb"), level="snabb"))


def test_r20_long_snabb_warns():
    long_text = "Detta är en mening om fynden [3]. " * 200
    r = lint(good_report("snabb", extra_body=long_text), level="snabb")
    assert "R20" in rules(r)
    assert r.status == "PASS"


# ── Utdata ────────────────────────────────────────────────────────────────────

def test_write_lint_file(tmp_path, r021):
    path = rl.write_lint(tmp_path, 1, r021)
    assert path.name == "03_lint_v1.md"
    text = path.read_text(encoding="utf-8")
    assert "Status: REVISE" in text and "## MÅSTE" in text and "## BÖR" in text


def test_requirements_list_must_before_should(r021):
    reqs = r021.requirements()
    assert reqs[0].startswith("MÅSTE")
    assert reqs[-1].startswith("BÖR")


def test_quote_found_normalizes_pdf_text():
    hay = rl.normalize_text("The ﬁrst classi-\nfication “works”.")
    assert rl.quote_found("the first classification \"works\"", hay)
    assert not rl.quote_found("the second classification", hay)
