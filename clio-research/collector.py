"""
collector.py
Insamlingssteget S1 i research-pipeline v2 (PLAN_research_pipeline_v2.md avsnitt 4,
10–12; PLAN_fulltext_v1.0.md avsnitt 5).

Kedjan:
    1. connectorerna via search_runner (faser 1–4 ur protokollet, färre på nivå snabb)
    2. råträff → källformat (source_model), dubbletter bort, räknebar kvalitet
    3. grovsållning på likhet (relevance_filter.coarse_filter) och tak per nivå
    4. fulltextkedjan för nivån (fulltext_fetcher) → kallor/
       → kontrollpunkt 01_candidates.json, så att ett återupptaget S1 inte söker om
    5. insamlarmodellen (claude_runner, roll collector, Sonnet 4.6):
       relevans per källa (role, why) och, på standard och delbar, webbfynd utanför indexen
    6. felträffar → 01_filtered.json (relevance_filter.apply_verdicts)
    7. webbfynd: DOI → metadata från CrossRef (i Python, aldrig ur modellens svar);
       utan DOI → webbkälla. Samma källformat och samma fulltextkedja.
    8. 01_sources.json, 01_filtered.json, 01_sources.md

Usage:
    from collector import collect
    result = collect(run_dir, protocol)          # protocol från protocol_parser
    if result.status == "limit": ...             # prenumerationsgräns → paused_limit

Modellen har WebSearch och WebFetch men inga filverktyg. Python skriver alla filer.
Alla nät- och modellanrop kan bytas ut (search_fn, embed_fn, fetch_fn, crossref_get,
runner) så att testerna kör utan nät och utan modell.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

sys.path.insert(0, str(Path(__file__).parent))

import credibility_scorer  # noqa: E402
import relevance_filter  # noqa: E402
import source_model as sm  # noqa: E402
from claude_runner import MODEL_COLLECTOR, STATUS_LIMIT, ClaudeResult, run_claude  # noqa: E402
from contact import redact  # noqa: E402

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "1.0.0"

PROMPTS_S1 = Path(__file__).parent / "config" / "prompts_s1.yaml"
CANDIDATES_FILE = "01_candidates.json"
RESPONSE_FILE = "01_response_{attempt}.txt"
SOURCES_MD = "01_sources.md"
ROLE = "collector"

MAX_SOURCES_BY_LEVEL = {"snabb": 15, "standard": 40, "delbar": 60}
MAX_PHASE_BY_LEVEL = {"snabb": 2, "standard": 4, "delbar": 4}
RESULT_FACTOR_BY_LEVEL = {"snabb": 0.5, "standard": 1.0, "delbar": 1.0}
MAX_WEB_FINDS = {"snabb": 0, "standard": 10, "delbar": 20}
MAX_TURNS_BY_LEVEL = {"snabb": 3, "standard": 40, "delbar": 60}
PROMPT_EXCERPT_CHARS = 600
MAX_TITLE_CHARS = 300
CROSSREF_WORK = "https://api.crossref.org/works/"
CROSSREF_TIMEOUT = 20

ROLE_TEXT = {
    "direkt": "källan handlar om frågan eller en delfråga",
    "analogi": "källan handlar om något annat men ger en metod eller jämförelse som frågan behöver",
    "bakgrund": "källan ger sammanhang (historik, begrepp, översikt)",
    "felträff": "källan handlar inte om frågan",
}

log = logging.getLogger(__name__)


@dataclass
class CollectResult:
    status: str                                  # ok | limit | error
    message: str = ""
    calls: list[tuple[str, ClaudeResult]] = field(default_factory=list)   # (etikett, svar)
    counts: dict = field(default_factory=dict)

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"


# ── Steg 1–4: index, källformat, grovsållning, fulltext ───────────────────────

def search_indexes(protocol: dict, level: str, search_fn: Callable | None = None) -> tuple[list[dict], list[dict]]:
    """Kör faserna 1–4 (snabb: 1–2) via search_runner. Returnerar (råträffar, söklogg)."""
    if search_fn is None:
        import search_runner
        search_fn = search_runner.run_phase
    seen: set = set()
    raw: list[dict] = []
    searchlog = []
    for phase in protocol.get("search_strategy", {}).get("phases", []):
        num = phase.get("phase")
        if not isinstance(num, int) or num > MAX_PHASE_BY_LEVEL[level] or not phase.get("databases"):
            continue
        phase = dict(phase)
        factor = RESULT_FACTOR_BY_LEVEL[level]
        for key in ("max_results", "max_results_per_region"):
            if key in phase:
                phase[key] = max(5, int(phase[key] * factor))
        try:
            hits = search_fn(phase, protocol, seen)
        except Exception as exc:                 # en connector får inte fälla hela steget
            log.warning("[S1] fas %s misslyckades: %s", num, redact(exc))
            hits = []
        raw.extend(hits)
        searchlog.append({"phase": num, "label": phase.get("label", ""),
                          "databases": phase.get("databases"), "hits": len(hits)})
    return raw, searchlog


def to_sources(raw_hits: list[dict], current_year: int | None = None) -> list[dict]:
    """Råträffar → källor i kontraktets format, utan dubbletter (source_id eller DOI)."""
    out, ids, dois = [], set(), set()
    for raw in raw_hits:
        try:
            src = sm.from_raw_hit(raw)
        except sm.SourceError as exc:
            log.info("[S1] råträff hoppas över: %s", exc)
            continue
        if src["source_id"] in ids or (src["doi"] and src["doi"] in dois):
            continue
        ids.add(src["source_id"])
        if src["doi"]:
            dois.add(src["doi"])
        out.append(src)
    return credibility_scorer.assess_all(out, current_year)


def cap_by_level(kept: list[dict], level: str) -> tuple[list[dict], list[dict]]:
    """Behåll de mest lika källorna upp till nivåns tak. Resten blir bortsorterade på likhet."""
    limit = MAX_SOURCES_BY_LEVEL[level]
    if len(kept) <= limit:
        return kept, []
    measured = any(s["relevance"].get("similarity") is not None for s in kept)
    order = sorted(kept, key=lambda s: -(s["relevance"].get("similarity") or 0.0))
    over = order[limit:]
    reason = (f"Över gränsen men utanför de {limit} mest lika för nivå {level}." if measured else
              f"Ingen likhet beräknad (inbäddningen gick inte att köra); utanför de {limit} första "
              f"i sökordningen för nivå {level}.")
    for src in over:
        src["filtered"] = {"stage": "likhet", "reason": reason}
    over_ids = {id(s) for s in over}
    return [s for s in kept if id(s) not in over_ids], over


def gather_candidates(run_dir: Path, protocol: dict, level: str, search_fn=None, embed_fn=None,
                      fetch_fn=None, current_year: int | None = None) -> dict:
    """Steg 1–4. Skriver och returnerar kontrollpunkten 01_candidates.json.
    Finns den redan (återupptagen körning) läses den i stället."""
    path = Path(run_dir) / CANDIDATES_FILE
    if path.exists():
        log.info("[S1] återupptar från %s", CANDIDATES_FILE)
        return json.loads(path.read_text(encoding="utf-8"))

    raw, searchlog = search_indexes(protocol, level, search_fn)
    sources = to_sources(raw, current_year)
    question = protocol["question"]["natural_language"]
    kept, dropped = relevance_filter.coarse_filter(sources, question, embed_fn=embed_fn)
    kept, over = cap_by_level(kept, level)
    dropped += over
    sm.assign_numbers(kept)
    if fetch_fn is None:
        import fulltext_fetcher
        fetch_fn = fulltext_fetcher.fetch_fulltexts
    fetch_fn(kept, Path(run_dir), level)
    data = {"schema": "clio-research/candidates", "version": 1, "level": level,
            "kept": kept, "dropped": dropped, "searchlog": searchlog}
    _write_json(path, data)
    log.info("[S1] %d råträffar, %d källor, %d behålls, %d bortsorterade på likhet",
             len(raw), len(sources), len(kept), len(dropped))
    return data


# ── Steg 5: insamlarmodellen ──────────────────────────────────────────────────

def load_prompts(path: Path = PROMPTS_S1) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def source_line(src: dict) -> str:
    authors = ", ".join(src.get("authors", [])[:3]) or "okänd upphovsperson"
    text = ((src.get("fetch") or {}).get("excerpt") or src.get("abstract") or "").strip()
    text = " ".join(text.split())[:PROMPT_EXCERPT_CHARS]
    parts = [f"[{src['n']}] {src['title']} ({src.get('year') or 'u.å.'}). {authors}.",
             f"Databas: {src['database']}. Läsnivå: {src['read_level']}."]
    if src.get("journal"):
        parts.append(f"Publicerad i: {src['journal']}.")
    if text:
        parts.append(f"Utdrag: {text}")
    return " ".join(parts)


def build_prompt(protocol: dict, level: str, sources: list[dict], prompts: dict) -> tuple[str, str]:
    q = protocol["question"]
    roles = "\n".join(f"  - {r}: {t}" for r, t in ROLE_TEXT.items())
    parts = [prompts["relevance_task"].format(roles=roles).strip()]
    if MAX_WEB_FINDS[level]:
        parts.append(prompts["web_task"].format(max_finds=MAX_WEB_FINDS[level]).strip())
        if level == "delbar":
            parts.append(prompts["web_task_delbar"].strip())
    else:
        parts.append(prompts["no_web_task"].strip())
    parts.append(prompts["answer_format"].strip())

    lines = [f"Protokoll: {protocol['protocol_id']}", f"Fråga: {q['natural_language']}"]
    if q.get("sub_questions"):
        lines.append("Delfrågor:")
        lines += [f"- {s}" for s in q["sub_questions"]]
    if protocol.get("hypothesis"):
        lines.append(f"Hypotes: {protocol['hypothesis']}")
    if protocol.get("scope"):
        lines.append(f"Avgränsning: {protocol['scope']}")
    if MAX_WEB_FINDS[level]:
        if protocol.get("primary_sources"):
            lines.append("Primärkällor att leta efter:")
            lines += [f"- {p['source']} {p.get('where') or ''}".rstrip() for p in protocol["primary_sources"]]
        if protocol.get("direct_urls"):
            lines.append("Kända URL:er att öppna:")
            lines += [f"- {u}" for u in protocol["direct_urls"]]
        if protocol.get("web_targets"):
            lines.append("Söktjänster utan connector (sök där via webben):")
            lines += [f"- {t['database']}: {t['term']} ({t.get('purpose') or ''})" for t in protocol["web_targets"]]

    listing = "\n".join(source_line(s) for s in sorted(sources, key=lambda s: s["n"])) or "(inga källor ur indexen)"
    user = "\n\n".join(["\n\n".join(parts), "## Protokoll\n\n" + "\n".join(lines),
                        f"## Källor ur indexen ({len(sources)})\n\n" + listing])
    return prompts["collector_system"].strip(), user


def parse_reply(text: str) -> tuple[list, list]:
    """Modellens svar → (bedömningar, webbfynd). Kastar RelevanceError vid fel format."""
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise relevance_filter.RelevanceError(["svaret innehåller inget JSON-objekt"])
        raw = raw[start:end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise relevance_filter.RelevanceError([f"svaret är inte giltig JSON: {exc}"]) from exc
    if not isinstance(data, dict) or not isinstance(data.get("bedomning"), list):
        raise relevance_filter.RelevanceError(["fältet bedomning saknas eller är inte en lista"])
    finds = data.get("webbfynd") or []
    if not isinstance(finds, list):
        raise relevance_filter.RelevanceError(["fältet webbfynd är inte en lista"])
    return data["bedomning"], finds


# ── Steg 7: webbfynd ──────────────────────────────────────────────────────────

def crossref_lookup(doi: str, get: Callable | None = None) -> dict | None:
    """Metadata för en DOI från CrossRef (/works/<doi>). None om den inte finns eller
    anropet nekas. Inga omförsök vid 403."""
    from connectors import crossref
    if get is None:
        import requests

        def get(url):
            try:
                r = requests.get(url, headers=crossref._headers(), timeout=CROSSREF_TIMEOUT)
            except requests.RequestException as exc:
                log.warning("[S1] CrossRef-uppslag misslyckades: %s", redact(exc))
                return None
            if r.status_code != 200:
                log.info("[S1] CrossRef svarade %s för en DOI", r.status_code)
                return None
            return (r.json() or {}).get("message")
    item = get(CROSSREF_WORK + doi)
    if not item:
        return None
    return crossref._normalize(item)


def web_sources(finds: list, existing: list[dict], level: str, crossref_get=None,
                current_year: int | None = None) -> tuple[list[dict], list[dict]]:
    """Webbfynd → källor. Returnerar (nya källor utan n, avvisade fynd med skäl)."""
    dois = {s["doi"] for s in existing if s.get("doi")}
    urls = {(s.get("url") or "").rstrip("/") for s in existing if s.get("url")}
    new, rejected = [], []
    for item in finds[:MAX_WEB_FINDS[level]]:
        if not isinstance(item, dict):
            rejected.append({"find": item, "reason": "inte ett objekt"})
            continue
        role, why = item.get("role"), " ".join(str(item.get("why") or "").split())
        if role not in sm.ROLES or role == sm.ROLE_MISMATCH or not why:
            rejected.append({"find": item, "reason": "roll eller motivering saknas eller är felträff"})
            continue
        doi = sm.normalize_doi(item.get("doi")) if isinstance(item.get("doi"), str) else None
        url = str(item.get("url") or "").strip()
        if doi:
            if doi in dois:
                rejected.append({"find": item, "reason": "DOI finns redan i underlaget"})
                continue
            raw = crossref_lookup(doi, crossref_get)
            if not raw:
                rejected.append({"find": item, "reason": "DOI:n gick inte att slå upp i CrossRef"})
                continue
            raw["database"] = "crossref"
        elif url.startswith(("http://", "https://")):
            if url.rstrip("/") in urls:
                rejected.append({"find": item, "reason": "URL:en finns redan i underlaget"})
                continue
            title = " ".join(str(item.get("title") or "").split())[:MAX_TITLE_CHARS]
            if not title:
                rejected.append({"find": item, "reason": "titel saknas"})
                continue
            raw = {"title": title, "database": "webb", "external_id": url, "url": url, "source_type": "webb"}
        else:
            rejected.append({"find": item, "reason": "varken DOI eller URL"})
            continue
        try:
            src = sm.from_raw_hit(raw)
        except sm.SourceError as exc:
            rejected.append({"find": item, "reason": str(exc)})
            continue
        src["relevance"] = {"role": role, "why": why, "similarity": None}
        if src["doi"]:
            dois.add(src["doi"])
        if src.get("url"):
            urls.add(src["url"].rstrip("/"))
        new.append(src)
    return credibility_scorer.assess_all(new, current_year), rejected


# ── Huvudfunktion ─────────────────────────────────────────────────────────────

def collect(run_dir: Path, protocol: dict, runner: Callable = run_claude, search_fn=None, embed_fn=None,
            fetch_fn=None, crossref_get=None, prompts: dict | None = None,
            current_year: int | None = None) -> CollectResult:
    """Kör hela S1. Kastar inte vid modellfel: status `limit` eller `error` i resultatet."""
    run_dir = Path(run_dir)
    level = protocol.get("niva") or "standard"
    prompts = prompts or load_prompts()
    cand = gather_candidates(run_dir, protocol, level, search_fn, embed_fn, fetch_fn, current_year)
    kept, dropped = cand["kept"], cand["dropped"]

    system, user = build_prompt(protocol, level, kept, prompts)
    result = CollectResult("error")
    verdicts = finds = None
    prompt = user
    for attempt in (1, 2):
        reply = runner(ROLE, prompt, MODEL_COLLECTOR, run_dir, system_prompt=system,
                       max_turns=MAX_TURNS_BY_LEVEL[level])
        result.calls.append((f"S1_collect/{attempt}", reply))
        (run_dir / RESPONSE_FILE.format(attempt=attempt)).write_text(reply.text or "", encoding="utf-8")
        if reply.status == STATUS_LIMIT:
            return _fail(result, "limit", f"prenumerationsgräns: {reply.message}")
        if not reply.is_ok:
            return _fail(result, "error", f"insamlarmodellen: {reply.message}")
        try:
            verdicts, finds = parse_reply(reply.text)
            # Prövas på kopior: ett ogiltigt svar får inte ändra källorna.
            relevance_filter.apply_verdicts(json.loads(json.dumps(kept)), verdicts)
            break
        except relevance_filter.RelevanceError as exc:
            log.warning("[S1] relevanssvar %d ogiltigt: %s", attempt, exc)
            verdicts = None
            prompt = user + "\n\n" + prompts["retry_task"].format(
                problems="\n".join(f"- {p}" for p in exc.problems))
    if verdicts is None:
        return _fail(result, "error", "insamlarmodellens svar var ogiltigt två gånger")

    relevant, mismatches = relevance_filter.apply_verdicts(kept, verdicts)
    web, rejected = web_sources(finds if MAX_WEB_FINDS[level] else [], relevant + mismatches + dropped,
                                level, crossref_get, current_year)
    taken = {s["n"] for s in relevant + mismatches if s.get("n")}
    sm.assign_numbers(web, taken)
    if web:
        if fetch_fn is None:
            import fulltext_fetcher
            fetch_fn = fulltext_fetcher.fetch_fulltexts
        fetch_fn(web, run_dir, level)

    sources = sorted(relevant + web, key=lambda s: s["n"])
    filtered = mismatches + dropped
    sm.write_sources(run_dir, sources)
    sm.write_filtered(run_dir, filtered)
    (run_dir / SOURCES_MD).write_text(render_markdown(protocol, level, sources, filtered, rejected,
                                                      cand.get("searchlog", [])), encoding="utf-8")
    result.status = "ok"
    result.counts = {"sources": len(sources), "filtered": len(filtered), "web": len(web),
                     "web_rejected": len(rejected), "mismatches": len(mismatches),
                     "read_levels": dict(Counter(s["read_level"] for s in sources))}
    result.message = (f"{len(sources)} källor ({len(web)} webbfynd), {len(mismatches)} felträffar, "
                      f"{len(dropped)} bortsorterade på likhet")
    if kept and all(s["relevance"].get("similarity") is None for s in kept):
        result.message += "; OBS: ingen likhetssållning, inbäddningen gick inte att köra"
    return result


def _fail(result: CollectResult, status: str, message: str) -> CollectResult:
    result.status, result.message = status, message
    return result


# ── 01_sources.md ─────────────────────────────────────────────────────────────

def _cell(value) -> str:
    return " ".join(str(value if value is not None else "").split()).replace("|", "/")


def render_markdown(protocol: dict, level: str, sources: list[dict], filtered: list[dict],
                    rejected: list[dict], searchlog: list[dict]) -> str:
    levels = Counter(s["read_level"] for s in sources)
    lines = [f"# Källunderlag {protocol['protocol_id']}", "",
             f"Nivå: {level}. Källor: {len(sources)}. Bortfiltrerade: {len(filtered)}. "
             "Läsnivå: " + ", ".join(f"{k} {levels.get(k, 0)}" for k in sm.READ_LEVELS) + ".", "",
             "## Sökningar", "", "| Fas | Etikett | Databaser | Träffar |", "|---|---|---|---|"]
    for entry in searchlog:
        dbs = entry.get("databases")
        dbs = ", ".join(dbs) if isinstance(dbs, list) else ", ".join(f"{k}: {v}" for k, v in (dbs or {}).items())
        lines.append(f"| {entry.get('phase')} | {_cell(entry.get('label'))} | {_cell(dbs)} | {entry.get('hits')} |")
    lines += ["", "## Källor", "", "| n | Titel | År | Databas | Läsnivå | Roll | Varför |", "|---|---|---|---|---|---|---|"]
    for s in sources:
        lines.append(f"| {s['n']} | {_cell(s['title'])} | {s.get('year') or ''} | {s['database']} | "
                     f"{s['read_level']} | {s['relevance']['role']} | {_cell(s['relevance']['why'])} |")
    lines += ["", "## Bortfiltrerade", "", "| n | Titel | Steg | Skäl |", "|---|---|---|---|"]
    for s in filtered:
        lines.append(f"| {s.get('n') or ''} | {_cell(s['title'])} | {s['filtered']['stage']} | "
                     f"{_cell(s['filtered']['reason'])} |")
    if rejected:
        lines += ["", "## Avvisade webbfynd", ""]
        for r in rejected:
            find = r["find"] if isinstance(r["find"], dict) else {"title": str(r["find"])}
            lines.append(f"- {_cell(find.get('title') or find.get('url') or find.get('doi'))}: {r['reason']}.")
    return redact("\n".join(lines) + "\n")


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
