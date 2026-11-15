"""
test_research_parser.py — Enhetstester för protocol_parser.py (mall v2.0 och JSON).
Körs en fil i taget: `python -m pytest tests/unit/test_research_parser.py`.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import protocol_parser as pp  # noqa: E402

FILLED = """# clio-research — Prov

## METADATA

```
Run-ID:       clio-research-099
Titel:        Klassificering av observationer
Datum:        2026-11-15
Författare:   Fredrik Arvas / Arvas International AB
Projekt:      Vigil
Version:      v1
Nivå:         snabb
Spridning:    delbar
Max revisionsvarv: 1
```

Nivå: `snabb`, `standard` eller `delbar` (förklarande text utanför blocket läses inte).

---

## BAKGRUNDSKONTEXT

### Projekt och syfte
Ett prov av mallparsern.

### Avgränsning
Inga enskilda fall.

---

## FORSKNINGSUPPGIFTER

### Huvudfråga
Har klassificeringssystemen ömsesidigt uteslutande kategorier?

### Hypotes (valfritt)
ingen

### Del 1 — Primärkällor

| # | Källa | URL / Sökterm | Prioritet |
|---|-------|---------------|-----------|
| 1 | Hynek, J.A. (1972). *The UFO Experience.* | https://archive.org/details/ufoexperience | Hög |

### Del 2 — Databassökning

| Databas | Sökterm | Syfte |
|---------|---------|-------|
| OpenAlex | UAP classification | Översikt |
| Google Scholar | Hynek classification review | Kritik |
| J-STAGE | UFO 分類 | Japanska källor |

### Del 3 — Specifika frågor att besvara

**Om systemen:**
1. Finns interbedömarstudier?
2. Hur stor är kategori D?

---

## GRANSKNINGSKRITERIER (valfritt)

- Kontrollera att GEIPAN-siffrorna har årtal.
"""


def write(tmp_path, text, name="clio-research-099.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_filled_template_parses(tmp_path):
    p = pp.load_protocol(write(tmp_path, FILLED))
    assert p["format"] == "md" and p["protocol_id"] == "clio-research-099"
    assert p["niva"] == "snabb" and p["spridning"] == "delbar" and p["max_revisions"] == 1
    assert p["question"]["natural_language"].startswith("Har klassificeringssystemen")
    assert p["question"]["sub_questions"] == ["Finns interbedömarstudier?", "Hur stor är kategori D?"]
    assert p["hypothesis"] is None
    assert p["scope"] == "Inga enskilda fall."
    assert p["review_criteria"] == ["Kontrollera att GEIPAN-siffrorna har årtal."]
    assert p["direct_urls"] == ["https://archive.org/details/ufoexperience"]
    assert [t["database"] for t in p["web_targets"]] == ["Google Scholar"]


def test_template_builds_phases_with_connectors(tmp_path):
    phases = pp.load_protocol(write(tmp_path, FILLED))["search_strategy"]["phases"]
    assert phases[0]["label"] == "Primärkällor"
    assert phases[0]["keywords"] == ["Hynek, J.A. (1972). The UFO Experience."]
    assert phases[1]["keywords"] == ["UAP classification", "Hynek classification review", "UFO 分類"]
    assert phases[1]["databases"] == ["openalex", "crossref", "core", "jstage"]


def test_level_and_spread_default_when_missing(tmp_path):
    text = FILLED.replace("Nivå:         snabb\n", "").replace("Spridning:    delbar\n", "")
    p = pp.load_protocol(write(tmp_path, text))
    assert p["niva"] == "standard" and p["spridning"] == "intern"


def test_unfilled_template_lists_every_problem():
    template = ROOT / "clio-research" / "PROMPT_TEMPLATE.md"
    with pytest.raises(pp.ProtocolError) as exc:
        pp.load_protocol(template)
    problems = exc.value.problems
    assert any("{{Kort beskrivande titel}}" in p for p in problems)
    assert any("{{Fråga 1}}" in p for p in problems)
    assert any("Run-ID" in p for p in problems)


@pytest.mark.parametrize("change, expected", [
    (("### Huvudfråga\nHar klassificeringssystemen ömsesidigt uteslutande kategorier?\n", ""), "huvudfrågan saknas"),
    (("1. Finns interbedömarstudier?\n2. Hur stor är kategori D?\n", ""), "Del 3 har inga numrerade frågor"),
    (("Nivå:         snabb", "Nivå:         grundlig"), "nivå 'grundlig'"),
    (("Spridning:    delbar", "Spridning:    publik"), "spridning 'publik'"),
    (("Max revisionsvarv: 1", "Max revisionsvarv: 5"), "Max revisionsvarv måste vara 0–2"),
    (("Titel:        Klassificering av observationer\n", ""), "Titel saknas"),
    (("Ett prov av mallparsern.", "{{Beskriv projektet}}"), "platshållare kvar"),
])
def test_incomplete_template_gives_clear_error(tmp_path, change, expected):
    old, new = change
    assert old in FILLED
    with pytest.raises(pp.ProtocolError) as exc:
        pp.load_protocol(write(tmp_path, FILLED.replace(old, new)))
    assert any(expected in p for p in exc.value.problems), exc.value.problems
    assert "Protokollet är ofullständigt" in str(exc.value)


def test_no_search_terms_is_error(tmp_path):
    start = FILLED.index("### Del 1")
    end = FILLED.index("### Del 3")
    with pytest.raises(pp.ProtocolError) as exc:
        pp.load_protocol(write(tmp_path, FILLED[:start] + FILLED[end:]))
    assert any("inga söktermer" in p for p in exc.value.problems)


def old_json(**kw):
    data = {
        "protocol_id": "clio-research-098",
        "question": {"natural_language": "Fråga?", "keywords_primary": {"en": ["uap"], "fr": ["ovni"]},
                     "key_sources_to_fetch": ["Rospars 2014"]},
        "search_strategy": {"phases": [{"phase": 1, "label": "Broad", "databases": ["openalex"],
                                        "direct_fetches": ["https://example.org/a.pdf"]}]},
        "output": {"word": True},
    }
    data.update(kw)
    return data


def test_old_json_protocol(tmp_path):
    path = tmp_path / "clio-research-098.json"
    path.write_text(json.dumps(old_json()), encoding="utf-8")
    p = pp.load_protocol(path)
    assert p["format"] == "json" and p["niva"] == "standard" and p["spridning"] == "intern"
    assert p["question"]["keywords_primary"] == {"en": ["uap"], "fr": ["ovni"]}
    assert p["direct_urls"] == ["https://example.org/a.pdf"]
    assert p["primary_sources"][0]["source"] == "Rospars 2014"


def test_old_json_with_level_in_output(tmp_path):
    p = pp.parse_json(old_json(output={"niva": "delbar", "spridning": "delbar"}))
    assert p["niva"] == "delbar" and p["spridning"] == "delbar"


def test_old_json_missing_fields():
    with pytest.raises(pp.ProtocolError) as exc:
        pp.parse_json({"protocol_id": "x", "question": {}, "niva": "grundlig"})
    joined = " ".join(exc.value.problems)
    assert "natural_language" in joined and "search_strategy" in joined and "grundlig" in joined


def test_find_protocol_prefers_md_and_accepts_suffix(tmp_path):
    (tmp_path / "clio-research-097.json").write_text("{}", encoding="utf-8")
    (tmp_path / "clio-research-097_kort.md").write_text("x", encoding="utf-8")
    assert pp.find_protocol("clio-research-097", tmp_path).name == "clio-research-097_kort.md"
    (tmp_path / "clio-research-097.md").write_text("x", encoding="utf-8")
    assert pp.find_protocol("clio-research-097", tmp_path).name == "clio-research-097.md"
    with pytest.raises(FileNotFoundError):
        pp.find_protocol("clio-research-000", tmp_path)
