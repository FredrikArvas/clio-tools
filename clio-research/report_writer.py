"""
report_writer.py
Analyssteget S2 i research-pipeline v2: skriver rapport och påståenderegister ur
protokollet och 01_sources.json, kontrollerar utkastet med report_lint och har en
revisionsväg som tar emot en kravlista.

Usage:
    from report_writer import analyse, revise, check, build_word
    draft = analyse(run_dir, protocol)                    # → 02_draft_v1.md, 02_claims_v1.json
    lint = check(run_dir, protocol, draft)                # → 03_lint_v1.md
    if lint.status == "REVISE":
        draft = revise(run_dir, protocol, lint.requirements(), previous=1)
    build_word(draft.md_path, level)                      # standard och delbar

    python clio-research/report_writer.py --run-dir RUN --protocol P.json --level standard \
        [--sources-file prov_sources.json] [--revisions 1] [--word]

Fördelning mellan modell och kod:
    Modellen skriver titel, Kort svar, Evidensläge, Fråga och avgränsning, Fynd, Motbild
    och Luckor, plus registret som JSON. Python skriver Metod, Källförteckning, Bilagor
    och sidfot ur underlaget, så att källistan bara innehåller citerade källor och aldrig
    uppgifter som saknas i metadata.

Modellanrop går bara via claude_runner.run_claude (prenumerationen, roll analyst utan
verktyg). Ta `runner` som parameter för att köra utan modell i testerna.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import yaml

sys.path.insert(0, str(Path(__file__).parent))

import report_lint as rl  # noqa: E402
import source_model as sm  # noqa: E402
from claude_runner import MODEL_ANALYST, MODEL_ANALYST_QUICK, ClaudeResult, run_claude  # noqa: E402

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "1.0.0"

HERE = Path(__file__).parent
PROMPTS_V1 = HERE / "config" / "prompts.yaml"
PROMPTS_V2 = HERE / "config" / "prompts_v2.yaml"
MD2DOCX = Path(os.environ.get("CLIO_MD2DOCX", HERE.parent / "clio-docx" / "md2docx.js"))
WORD_PROFILE = "aiab"
WORD_LEVELS = ("standard", "delbar")
WORD_TIMEOUT_S = 180

ROLE = "analyst"
MODEL_BY_LEVEL = {"snabb": MODEL_ANALYST_QUICK, "standard": MODEL_ANALYST, "delbar": MODEL_ANALYST}
SPREADS = ("intern", "delbar")
DEFAULT_SPREAD = "intern"

MARK_REPORT = "<<<RAPPORT>>>"
MARK_REGISTER = "<<<REGISTER>>>"
MARK_END = "<<<SLUT>>>"

EXCERPT_BUDGET_CHARS = 240_000     # totalt för alla fulltextutdrag i prompten
PROMPT_ROLES = ("direkt", "analogi", "bakgrund")
STANCES = ("stödjer", "neutral", "avvisar")
CODE_SECTIONS = ("metod", "källförteckning", "bilagor")

log = logging.getLogger(__name__)


class ResponseError(ValueError):
    """Svaret kunde inte delas upp i rapport och register."""


@dataclass
class Draft:
    version: int
    level: str
    ok: bool
    md_path: Path | None = None
    claims_path: Path | None = None
    raw_path: Path | None = None
    markdown: str = ""
    register: dict = field(default_factory=dict)
    complete: bool = False
    problems: list[str] = field(default_factory=list)
    result: ClaudeResult | None = None

    @property
    def claims(self) -> list | None:
        return self.register.get("claims") if self.ok else None

    def response_meta(self) -> dict:
        usage = (self.result.usage if self.result else {}) or {}
        return {"complete": self.complete, "output_tokens": usage.get("output_tokens", 0),
                "stop_reason": usage.get("stop_reason")}


# ── Underlag ──────────────────────────────────────────────────────────────────

def load_prompts(path: Path = PROMPTS_V2, tone_path: Path = PROMPTS_V1) -> dict:
    prompts = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    tone = yaml.safe_load(Path(tone_path).read_text(encoding="utf-8")) if Path(tone_path).exists() else {}
    prompts["tone"] = (tone or {}).get("System", "").strip()
    return prompts


def load_sources(run_dir: Path, complete: bool = True) -> list[dict]:
    """Läs 01_sources.json. complete=False tillåter provunderlag där insamlingen inte
    satt relevance.role (validering med source_model, complete=False)."""
    if complete:
        return sm.read_sources(run_dir)
    data = json.loads((Path(run_dir) / sm.SOURCES_FILE).read_text(encoding="utf-8"))
    sources = data["sources"] if isinstance(data, dict) else data
    for src in sources:
        sm.validate_source(src, complete=False)
    return sources


def load_filtered(run_dir: Path) -> list[dict]:
    try:
        return sm.read_filtered(run_dir)
    except sm.SourceError as exc:
        log.warning("01_filtered.json ogiltig, används inte: %s", exc)
        return []


def protocol_view(protocol: dict) -> dict:
    """Plocka det rapportsteget behöver ur protokollet (JSON-formatet i inbox/, eller ett
    redan normaliserat protokoll från mall-parsern)."""
    q = protocol.get("question") or {}
    question = q.get("natural_language", "") if isinstance(q, dict) else str(q)
    subq = (q.get("sub_questions") if isinstance(q, dict) else None) or protocol.get("subquestions") or []
    hyp = protocol.get("hypothesis")
    if isinstance(hyp, dict):
        hyp = hyp.get("primary") or ""
    output = protocol.get("output") or {}
    level = protocol.get("niva") or output.get("niva") or rl.DEFAULT_LEVEL
    spread = protocol.get("spridning") or output.get("spridning") or DEFAULT_SPREAD
    if level not in rl.LEVELS:
        raise ValueError(f"Okänd nivå i protokollet: {level!r}")
    if spread not in SPREADS:
        raise ValueError(f"Okänd spridning i protokollet: {spread!r}")
    context = protocol.get("context") or ""
    if isinstance(context, dict):
        context = "\n".join(f"{k}: {v}" for k, v in context.items() if isinstance(v, str))
    keywords = q.get("keywords_primary") if isinstance(q, dict) else None
    return {
        "id": protocol.get("protocol_id") or protocol.get("id") or "",
        "title": protocol.get("title") or "",
        "question": question.strip(),
        "subquestions": [str(s).strip() for s in subq if str(s).strip()],
        "hypothesis": (hyp or "").strip() or None,
        "context": str(context).strip(),
        "scope": str(protocol.get("scope") or protocol.get("avgransning") or "").strip(),
        "languages": sorted(keywords) if isinstance(keywords, dict) else [],
        "level": level,
        "spread": spread,
    }


# ── Prompt ────────────────────────────────────────────────────────────────────

def _by_level(table: dict, level: str):
    return table.get(level, table.get("default"))


def source_block(src: dict, excerpt_chars: int) -> str:
    """Ett källblock i prompten: metadata, läsnivå, sammanfattning, citat och utdrag."""
    n = src["n"]
    src = {k: (" ".join(v.split()) if isinstance(v, str) and k not in ("abstract",) else v)
           for k, v in src.items()}
    authors = ", ".join(src.get("authors") or []) or "upphovsperson saknas i metadata"
    year = src.get("year") or "år saknas"
    lines = [f"### [{n}] {src.get('title') or 'titel saknas i metadata'}",
             f"Upphov: {authors} ({year}). Databas: {src.get('database') or '-'}. "
             f"Källtyp: {src.get('source_type') or 'ej angiven'}."]
    if src.get("journal"):
        lines.append(f"Publicerad i: {src['journal']}.")
    countries = ", ".join(src.get("country_codes") or []) or "okänt (saknas i metadata, påstå inget land)"
    institutions = "; ".join(src.get("institutions") or []) or "okänd (saknas i metadata)"
    lines.append(f"Land: {countries}. Institution: {institutions}.")
    if src.get("language"):
        lines.append(f"Språk: {src['language']}.")
    lines.append(f"Läsnivå: {src.get('read_level')}." + (f" {src['read_note']}" if src.get("read_note") else ""))
    rel = src.get("relevance") or {}
    if rel.get("role"):
        lines.append(f"Relevans enligt insamlaren: {rel['role']}. {rel.get('why') or ''}".strip())
    if src.get("abstract"):
        lines += ["Sammanfattning:", src["abstract"].strip()]
    quotes = [q for q in src.get("quotes") or [] if isinstance(q, dict) and q.get("text")]
    if quotes:
        lines.append("Citat ur insamlingen:")
        lines += [f"- \"{q['text']}\" ({q.get('where') or 'plats ej angiven'})" for q in quotes]
    fetch = src.get("fetch") or {}
    excerpt = (fetch.get("excerpt") or "").strip()
    if excerpt and excerpt_chars > 0:
        shown = excerpt[:excerpt_chars]
        total = fetch.get("chars") or len(excerpt)
        lines += [f"Utdrag ur fulltexten ({len(shown)} av {total} tecken):", "<<<UTDRAG", shown, "UTDRAG>>>"]
    return "\n".join(lines)


def build_prompts(view: dict, sources: list[dict], prompts: dict) -> tuple[str, str]:
    """Systemprompt och användarprompt för första utkastet."""
    level = view["level"]
    stance_values = '"stödjer" | "neutral" | "avvisar"' if view["hypothesis"] else "null"
    system = "\n\n".join(p for p in (
        prompts.get("tone", ""),
        prompts["analyst_system"].format(quote_rule=_by_level(prompts["quote_rule"], level),
                                         stance_values=stance_values).strip(),
    ) if p)

    model_sections = [s for s in rl.REQUIRED_SECTIONS[level] if s in rl.MODEL_SECTIONS]
    section_texts = "\n".join(f"- {s}: {_by_level(prompts['sections'][s], level)}" for s in model_sections)
    columns = "Delfråga, Bedömning (1–5), Säkerhet (hög, medel, låg), Viktigaste källor"
    task = prompts["analyst_task"].format(
        level=level,
        length=prompts["length"][level],
        sections="\n".join(f"- {s}" for s in model_sections),
        section_texts=section_texts,
        table_columns=columns,
        scale=prompts["scale"].strip(),
        hypothesis_rule=prompts["hypothesis_rule"]["with" if view["hypothesis"] else "without"],
        register_rule=prompts["register_rule"][level],
    ).strip()

    with_text = [s for s in sources if (s.get("fetch") or {}).get("excerpt")]
    per_source = EXCERPT_BUDGET_CHARS // max(1, len(with_text))
    blocks = "\n\n".join(source_block(s, per_source) for s in sorted(sources, key=lambda s: s["n"]))

    protocol_lines = [f"Protokoll: {view['id']}", f"Fråga: {view['question']}"]
    if view["title"]:
        protocol_lines.insert(1, f"Titel: {view['title']}")
    if view["subquestions"]:
        protocol_lines.append("Delfrågor:")
        protocol_lines += [f"- {chr(65 + i)}. {s}" for i, s in enumerate(view["subquestions"])]
    else:
        protocol_lines.append("Delfrågor: inte angivna. Dela själv frågan i två till fyra delfrågor (A, B …).")
    protocol_lines.append(f"Hypotes: {view['hypothesis'] or 'ingen uttalad hypotes'}")
    if view["scope"]:
        protocol_lines.append(f"Avgränsning: {view['scope']}")
    if view["context"]:
        protocol_lines += ["Bakgrund:", view["context"]]

    user = "\n\n".join([
        task,
        "## Protokoll\n\n" + "\n".join(protocol_lines),
        f"## Källunderlag ({len(sources)} källor)\n\n" + blocks,
        f"Svara nu, med {MARK_REPORT} först och {MARK_END} sist.",
    ])
    return system, user


def build_revision_prompt(base_user: str, previous: int, requirements: list[str],
                          previous_report: str, previous_register: dict, prompts: dict) -> str:
    task = prompts["revision_task"].format(
        previous=previous,
        requirements="\n".join(f"{i}. {r}" for i, r in enumerate(requirements, start=1)) or "1. (inga)",
        previous_report=previous_report.strip(),
        previous_register=json.dumps(previous_register, ensure_ascii=False, indent=1),
    ).strip()
    return base_user + "\n\n## Revision\n\n" + task


# ── Svaret ────────────────────────────────────────────────────────────────────

def parse_response(text: str) -> tuple[str, dict, bool, list[str]]:
    """Dela upp svaret. Returnerar (rapport, register, komplett, problem).

    Raises:
        ResponseError: om rapportmarkören saknas.
    """
    text = text or ""
    if MARK_REPORT not in text:
        raise ResponseError(f"Svaret saknar {MARK_REPORT}.")
    after = text.split(MARK_REPORT, 1)[1]
    complete = MARK_END in after
    problems: list[str] = []
    if MARK_REGISTER in after:
        report, rest = after.split(MARK_REGISTER, 1)
    else:
        report, rest = after, ""
        problems.append(f"Svaret saknar {MARK_REGISTER}.")
    report = report.split(MARK_END, 1)[0].strip()
    raw_json = rest.split(MARK_END, 1)[0].strip()
    raw_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json).strip()
    register: dict = {}
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            problems.append(f"Registret är inte giltig JSON: {exc.msg} (rad {exc.lineno}).")
            parsed = {}
        if isinstance(parsed, list):
            parsed = {"claims": parsed}
        if isinstance(parsed, dict):
            register = parsed
        else:
            problems.append("Registret ska vara ett JSON-objekt.")
    register.setdefault("claims", [])
    register.setdefault("sources_used", [])
    register.setdefault("unused", [])
    return report, register, complete, problems


def strip_code_sections(report: str) -> tuple[str, list[str]]:
    """Ta bort H2-avsnitt som koden skriver (Metod, Källförteckning, Bilagor) om modellen
    ändå skrivit dem."""
    out, removed, skipping = [], [], False
    in_fence = False
    for line in report.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else re.match(r"^(#{1,2})\s+(.*)$", line)
        if m:
            skipping = len(m.group(1)) == 2 and rl.normalize_title(m.group(2)) in CODE_SECTIONS
            if skipping:
                removed.append(m.group(2).strip())
        if not skipping:
            out.append(line)
    return "\n".join(out).rstrip() + "\n", removed


# ── Delar som koden skriver ───────────────────────────────────────────────────

def _clean(value) -> str:
    s = "" if value is None else " ".join(str(value).split())
    return "" if s.lower() in ("none", "null", "nan", "?") else s


def _cell(value) -> str:
    return _clean(value).replace("|", "/").replace("\n", " ") or "-"


def _sentence(s: str) -> str:
    s = s.strip()
    return s if not s or s.endswith(tuple(".!?")) else s + "."


def reference_entry(src: dict, used: dict | None, with_stance: bool) -> str:
    authors = [a for a in (src.get("authors") or []) if _clean(a)]
    head = ", ".join(authors[:3]) + (" m.fl." if len(authors) > 3 else "")
    year = _clean(src.get("year")) or "u.å."
    parts = [f"[{src['n']}]", (f"{head} ({year})." if head else f"({year})."), _sentence(_clean(src.get("title")))]
    if _clean(src.get("journal")):
        parts.append(_sentence(_clean(src["journal"])))
    doi = _clean(src.get("doi"))
    link = f"https://doi.org/{doi}" if doi else _clean(src.get("url"))
    if link:
        parts.append(link + ".")
    if _clean(src.get("source_type")):
        parts.append(f"Källtyp: {src['source_type']}.")
    if src.get("country_codes"):
        parts.append(f"Land enligt metadata: {', '.join(src['country_codes'])}.")
    role = (used or {}).get("role") or (src.get("relevance") or {}).get("role")
    if role in PROMPT_ROLES:
        parts.append(f"Roll: {role}.")
    stance = (used or {}).get("stance")
    if with_stance and stance in STANCES:
        parts.append(f"Ställningstagande: {stance}.")
    parts.append(f"Läsnivå: {src.get('read_level')}.")
    return " ".join(p for p in parts if p)


def render_method(view: dict, sources: list[dict], filtered: list[dict], cited: list[int],
                  model: str, today: str) -> str:
    levels = Counter(s.get("read_level") for s in sources)
    read = ", ".join(f"{rl_}: {levels.get(rl_, 0)}" for rl_ in rl.READ_LEVELS)
    databases = Counter(_clean(s.get("database")) or "okänd" for s in sources)
    db_text = ", ".join(f"{k} ({v})" for k, v in databases.most_common())
    if view["level"] == "snabb":
        return (f"## Metod\n\nNivå snabb, analys med {model}, {today}. {len(sources)} källor i underlaget "
                f"ur {db_text}; läsnivå {read}; {len(cited)} citerade.\n")
    langs = Counter(_clean(s.get("language")) for s in sources if _clean(s.get("language")))
    lines = [
        "## Metod", "",
        f"- Nivå: {view['level']}. Analys: {model}, ett sammanhållet anrop utan verktyg. Datum: {today}.",
        f"- Databaser: {db_text}.",
    ]
    if langs:
        lines.append("- Språk i underlaget: " + ", ".join(f"{k} ({v})" for k, v in langs.most_common()) + ".")
    if view["languages"]:
        lines.append("- Sökspråk enligt protokollet: " + ", ".join(view["languages"]) + ".")
    lines += [
        f"- Källor: {len(sources) + len(filtered)} granskade, varav {len(filtered)} bortfiltrerade och "
        f"{len(sources)} i underlaget. Läsnivå i underlaget: {read}. Citerade i rapporten: {len(cited)}.",
        "- Antal sökningar: insamlingssteget lämnar ännu ingen söklogg, så antalet redovisas inte.",
        "- Kontroll: deterministisk rapportkontroll (report_lint) av struktur, källhänvisningar och "
        "påståenderegister.",
    ]
    return "\n".join(lines) + "\n"


def render_references(sources: list[dict], cited: list[int], register: dict, with_stance: bool) -> str:
    by_n = {s["n"]: s for s in sources}
    used = {u.get("n"): u for u in register.get("sources_used") or [] if isinstance(u, dict)}
    entries = [reference_entry(by_n[n], used.get(n), with_stance) for n in cited if n in by_n]
    entries = entries or ["Rapporten citerar inga källor ur underlaget."]
    return "## Källförteckning\n\n" + "\n\n".join(entries) + "\n"


def render_appendix(view: dict, sources: list[dict], filtered: list[dict], cited: list[int],
                    register: dict) -> str:
    level = view["level"]
    with_quote = level == "delbar"
    claims = [c for c in register.get("claims") or [] if isinstance(c, dict)]
    head = "| Id | Påstående | Delfråga | Källor | Läsnivå | Status |"
    sep = "|---|---|---|---|---|---|"
    if with_quote:
        head, sep = head + " Citat |", sep + "---|"
    lines = ["## Bilagor", "", "### Påståenderegister", ""]
    if claims:
        lines += [head, sep]
        for c in claims:
            nums = c.get("sources") if isinstance(c.get("sources"), list) else []
            row = [_cell(c.get("id")), _cell(c.get("claim")), _cell(c.get("subquestion")),
                   _cell(", ".join(f"[{n}]" for n in nums)), _cell(c.get("read_level")), _cell(c.get("status"))]
            if with_quote:
                row.append(_cell(c.get("quote")))
            lines.append("| " + " | ".join(row) + " |")
    else:
        lines.append("Registret är tomt.")
    if level == "delbar":
        lines += ["", "### Söklogg", "",
                  "Insamlingssteget lämnar ännu ingen söklogg. Underlaget består av "
                  f"{len(sources)} källor och {len(filtered)} bortfiltrerade."]
    reasons = {u.get("n"): _clean(u.get("why")) for u in register.get("unused") or [] if isinstance(u, dict)}
    unused = [s for s in sources if s["n"] not in cited]
    rows = [(s["n"], s.get("title"), reasons.get(s["n"]) or "Analytikern angav inget skäl.") for s in unused]
    rows += [(s["n"], s.get("title"), _clean((s.get("filtered") or {}).get("reason")) or "Bortfiltrerad.")
             for s in filtered]
    lines += ["", "### Granskade källor som inte användes", ""]
    if rows:
        lines += ["| Nr | Titel | Skäl |", "|---|---|---|"]
        lines += [f"| {n} | {_cell(t)} | {_cell(why)} |" for n, t, why in sorted(rows)]
    else:
        lines.append("Alla källor i underlaget används.")
    return "\n".join(lines) + "\n"


def render_footer(view: dict, prompts: dict, today: str) -> str:
    text = prompts["footer"][view["spread"]].format(date=today, year=today[:4]).strip()
    return f"---\n\n{text}\n"


def assemble(view: dict, report: str, register: dict, sources: list[dict], filtered: list[dict],
             model: str, prompts: dict, today: str) -> str:
    """Modellens rapport plus metadata, Metod, Källförteckning, Bilagor och sidfot."""
    report, removed = strip_code_sections(report)
    if removed:
        log.info("Tog bort avsnitt som koden skriver: %s", ", ".join(removed))
    meta = (f"Datum: {today}. Nivå: {view['level']}. Spridning: {view['spread']}."
            + (f" Protokoll: {view['id']}." if view["id"] else ""))
    lines = report.splitlines()
    h1 = next((i for i, ln in enumerate(lines) if re.match(r"^#\s+\S", ln)), None)
    if h1 is None:
        lines = [meta, ""] + lines
    else:
        lines = lines[:h1 + 1] + ["", meta] + lines[h1 + 1:]
    body = "\n".join(lines).rstrip() + "\n"
    cited = rl.cited_numbers(body)
    parts = [body, render_method(view, sources, filtered, cited, model, today),
             render_references(sources, cited, register, bool(view["hypothesis"]))]
    if "Bilagor" in rl.REQUIRED_SECTIONS[view["level"]]:
        parts.append(render_appendix(view, sources, filtered, cited, register))
    parts.append(render_footer(view, prompts, today))
    return "\n".join(parts)


# ── Steg ──────────────────────────────────────────────────────────────────────

def _write_draft(run_dir: Path, version: int, view: dict, result: ClaudeResult, sources: list[dict],
                 filtered: list[dict], model: str, prompts: dict, today: str) -> Draft:
    run_dir = Path(run_dir)
    draft = Draft(version=version, level=view["level"], ok=False, result=result)
    draft.raw_path = run_dir / f"02_response_v{version}.txt"
    draft.raw_path.write_text(result.text or "", encoding="utf-8")
    if not result.is_ok:
        draft.problems.append(f"Anropet misslyckades ({result.status}): {result.message}")
        return draft
    try:
        report, register, complete, problems = parse_response(result.text)
    except ResponseError as exc:
        draft.problems.append(str(exc))
        return draft
    draft.markdown = assemble(view, report, register, sources, filtered, model, prompts, today)
    draft.register, draft.complete, draft.problems, draft.ok = register, complete, problems, True
    draft.md_path = run_dir / f"02_draft_v{version}.md"
    draft.md_path.write_text(draft.markdown, encoding="utf-8")
    draft.claims_path = run_dir / f"02_claims_v{version}.json"
    payload = {"schema": "clio-research/claims", "version": 1, "draft": version, **register}
    draft.claims_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return draft


def analyse(run_dir: Path, protocol: dict, runner: Callable = run_claude, version: int = 1,
            sources: list[dict] | None = None, prompts: dict | None = None,
            today: str | None = None) -> Draft:
    """Första utkastet: prompt ur protokoll och underlag, ett anrop, delat och sparat."""
    run_dir = Path(run_dir)
    view = protocol_view(protocol)
    prompts = prompts or load_prompts()
    sources = sources if sources is not None else load_sources(run_dir)
    filtered = load_filtered(run_dir)
    today = today or date.today().isoformat()
    model = MODEL_BY_LEVEL[view["level"]]
    system, user = build_prompts(view, sources, prompts)
    result = runner(ROLE, user, model, run_dir, system_prompt=system)
    return _write_draft(run_dir, version, view, result, sources, filtered, model, prompts, today)


def revise(run_dir: Path, protocol: dict, requirements: list[str], previous: int,
           runner: Callable = run_claude, sources: list[dict] | None = None,
           prompts: dict | None = None, today: str | None = None) -> Draft:
    """Nytt utkast (previous + 1) som åtgärdar kravlistan. Läser föregående svar ur
    02_response_v<previous>.txt."""
    run_dir = Path(run_dir)
    view = protocol_view(protocol)
    prompts = prompts or load_prompts()
    sources = sources if sources is not None else load_sources(run_dir)
    filtered = load_filtered(run_dir)
    today = today or date.today().isoformat()
    model = MODEL_BY_LEVEL[view["level"]]
    raw = (run_dir / f"02_response_v{previous}.txt").read_text(encoding="utf-8")
    try:
        prev_report, prev_register, _, _ = parse_response(raw)
    except ResponseError:
        prev_report, prev_register = raw, {}
    system, user = build_prompts(view, sources, prompts)
    user = build_revision_prompt(user, previous, requirements, prev_report, prev_register, prompts)
    result = runner(ROLE, user, model, run_dir, system_prompt=system)
    return _write_draft(run_dir, previous + 1, view, result, sources, filtered, model, prompts, today)


def check(run_dir: Path, protocol: dict, draft: Draft, sources: list[dict] | None = None) -> rl.LintResult:
    """Kör report_lint på utkastet och skriv 03_lint_v<k>.md. Ett utkast som inte gick att
    dela upp ger ett MÅSTE."""
    view = protocol_view(protocol)
    sources = sources if sources is not None else load_sources(run_dir)
    if not draft.ok:
        result = rl.LintResult(view["level"])
        for p in draft.problems or ["Inget utkast."]:
            result.findings.append(rl.Finding(rl.MUST, "R00 svarsformat", "svaret", p))
    else:
        result = rl.lint_report(draft.markdown, level=view["level"], sources=sources,
                                claims=draft.claims, run_dir=Path(run_dir),
                                response=draft.response_meta(), has_hypothesis=bool(view["hypothesis"]))
        for p in draft.problems:
            result.findings.insert(0, rl.Finding(rl.MUST, "R00 svarsformat", "svaret", p))
    rl.write_lint(run_dir, draft.version, result)
    return result


def write_report(run_dir: Path, protocol: dict, runner: Callable = run_claude, revisions: int = 0,
                 word: bool = False, sources: list[dict] | None = None,
                 today: str | None = None) -> tuple[Draft, rl.LintResult]:
    """Utkast, kontroll och högst `revisions` revisionsvarv. Word på nivå standard och delbar."""
    prompts = load_prompts()
    sources = sources if sources is not None else load_sources(run_dir)
    draft = analyse(run_dir, protocol, runner, 1, sources, prompts, today)
    lint = check(run_dir, protocol, draft, sources)
    rounds = 0
    while lint.status == "REVISE" and rounds < revisions and draft.raw_path and draft.raw_path.exists():
        rounds += 1
        draft = revise(run_dir, protocol, lint.requirements(), draft.version, runner, sources, prompts, today)
        lint = check(run_dir, protocol, draft, sources)
    if word and draft.ok:
        build_word(draft.md_path, draft.level, created=today)
    return draft, lint


# ── Word ──────────────────────────────────────────────────────────────────────

class WordError(RuntimeError):
    pass


def build_word(md_path: Path, level: str, profile: str = WORD_PROFILE, script: Path | None = None,
               runner: Callable = subprocess.run, created: str | None = None) -> Path | None:
    """Word via clio-docx/md2docx.js, med filnamn och skapad-datum i sidhuvudet och
    sidnummer i sidfoten. Nivå snabb ger ingen Word-fil (None)."""
    if level not in WORD_LEVELS:
        return None
    script = Path(script or MD2DOCX)
    md_path = Path(md_path)
    out = md_path.with_suffix(".docx")
    command = ["node", str(script), str(md_path), str(out), "--profile", profile,
               "--header", "--page-numbers", f"--date={created or date.today().isoformat()}"]
    try:
        completed = runner(command, cwd=str(script.parent), capture_output=True, text=True,
                           encoding="utf-8", timeout=WORD_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise WordError(f"md2docx kunde inte köras: {exc}") from exc
    if completed.returncode != 0:
        raise WordError(f"md2docx avslutades med {completed.returncode}: {(completed.stderr or '')[:300]}")
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────

def _prepare_run_dir(run_dir: Path, sources_file: Path) -> None:
    """Kopiera ett sparat källunderlag (till exempel prov_sources.json) och dess kallor/
    till körkatalogen som 01_sources.json."""
    run_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(sources_file.read_text(encoding="utf-8"))
    sources = data["sources"] if isinstance(data, dict) else data
    payload = {"schema": "clio-research/sources", "version": sm.SCHEMA_VERSION, "sources": sources}
    (run_dir / sm.SOURCES_FILE).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    src_texts = sources_file.parent / sm.TEXT_DIR
    if src_texts.is_dir():
        shutil.copytree(src_texts, run_dir / sm.TEXT_DIR, dirs_exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Analyssteget S2: rapport och påståenderegister.")
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--protocol", required=True, type=Path, help="Protokoll som JSON")
    ap.add_argument("--level", choices=rl.LEVELS, help="Skriver över protokollets niva")
    ap.add_argument("--spread", choices=SPREADS, help="Skriver över protokollets spridning")
    ap.add_argument("--sources-file", type=Path, help="Sparat källunderlag att kopiera in")
    ap.add_argument("--revisions", type=int, default=0)
    ap.add_argument("--word", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    if args.level:
        protocol["niva"] = args.level
    if args.spread:
        protocol["spridning"] = args.spread
    complete = True
    if args.sources_file:
        _prepare_run_dir(args.run_dir, args.sources_file)
        complete = False
    sources = load_sources(args.run_dir, complete=complete)
    draft, lint = write_report(args.run_dir, protocol, revisions=args.revisions, word=args.word,
                               sources=sources)
    print(f"Utkast v{draft.version}: {draft.md_path or draft.problems}")
    print(f"Kontroll: {lint.status}, MÅSTE {len(lint.must)}, BÖR {len(lint.should)}")
    return 0 if lint.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
