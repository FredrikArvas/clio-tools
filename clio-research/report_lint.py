"""
report_lint.py
Deterministisk rapportkontroll för analyssteget S2 (PROMPT_rapportforbattring v1.1, del 3).
Ren Python, inga modellanrop och inga nätverksanrop.

Usage:
    from report_lint import lint_report, write_lint
    result = lint_report(markdown, level="standard", sources=sources, claims=claims,
                         run_dir=run_dir, response={"complete": True, "output_tokens": 9000},
                         has_hypothesis=False)
    write_lint(run_dir, 1, result)        # → 03_lint_v1.md
    result.status                         # "PASS" eller "REVISE"
    result.requirements()                 # kraven till analytikerns revision

Varje fynd har nivå MÅSTE eller BÖR, regel, plats och åtgärd. Ett enda MÅSTE ger REVISE.
Regler som behöver underlag som saknas (källor, register, svarsdata) hoppas över.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "1.0.0"

MUST = "MÅSTE"
SHOULD = "BÖR"

LEVELS = ("snabb", "standard", "delbar")
DEFAULT_LEVEL = "standard"

# Avsnitt per nivå, i ordning. report_writer bygger dispositionen härifrån.
ALL_SECTIONS = (
    "Kort svar", "Evidensläge", "Fråga och avgränsning", "Fynd", "Motbild",
    "Luckor", "Metod", "Källförteckning", "Bilagor",
)
REQUIRED_SECTIONS = {
    "snabb":    ("Kort svar", "Evidensläge", "Fynd", "Motbild", "Luckor", "Metod",
                 "Källförteckning"),
    "standard": ALL_SECTIONS,
    "delbar":   ALL_SECTIONS,
}
MODEL_SECTIONS = ("Kort svar", "Evidensläge", "Fråga och avgränsning", "Fynd", "Motbild", "Luckor")

REFERENCE_TITLES = ("källförteckning", "referenser", "litteratur", "litteraturlista", "källor")
APPENDIX_TITLES = ("bilagor", "bilaga")

READ_LEVELS = ("fulltext", "sammanfattning", "bara titel", "ej åtkomlig")
READ_RANK = {"ej åtkomlig": 0, "bara titel": 1, "sammanfattning": 2, "fulltext": 3}
CLAIM_STATUSES = ("belagt", "delvis", "obelagt", "motsagt")

OUTPUT_TOKEN_CEILING = 32000      # standardtaket för svar i Claude Code
CEILING_MARGIN = 0.98
WORD_LIMITS = {"snabb": 1000, "standard": 4500}   # ord före källförteckningen
MIN_QUOTE_CHARS = 25
MIN_FRAGMENT_CHARS = 4

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_NUMBERED_TITLE_RE = re.compile(r"^(\d+(\.\d+)*\.?\s+|sektion\s+\d+)", re.IGNORECASE)
_CITE_RE = re.compile(r"\[(\d+(?:\s*[,;–-]\s*\d+)*)\]")
_REF_ENTRY_RE = re.compile(r"^\s*(?:[-*]\s+)?(?:\[(\d+)\]|(\d+)\.)\s+")
_END_OK = tuple(".!?:;)\"”»’'…")
_TRAILING_MARKUP = "*_` "
_QUOTE_RES = (
    re.compile(r"“([^”\n]+)”"),
    re.compile(r"„([^“”\n]+)[“”]"),
    re.compile(r"«\s*([^»\n]+?)\s*»"),
    re.compile(r"(?<![\w=])\"([^\"\n]+)\"(?!\w)"),
)
_NEGATIVE_RES = (
    re.compile(r"\bdet finns (ingen|inga|inget)\b", re.IGNORECASE),
    re.compile(r"\bingen studie (har|finns)\b", re.IGNORECASE),
    re.compile(r"\binga studier (har|finns)\b", re.IGNORECASE),
)
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]"
)
_TOKENS_RE = re.compile(r"\btokens?\s*:\s*~?\d", re.IGNORECASE)
_BAD_CELL_RE = re.compile(r"^(none|null|nan|\?+|okänd titel|okänd upphovsman)$", re.IGNORECASE)
_BAD_REF_RE = re.compile(r"\bNone\b|\bnull\b|Okänd titel|Okänd upphovsman|(?<!\S)\?(?!\S)")
_CONVERGENCE_RE = re.compile(r"konvergen|flera länder|olika länder|oberoende länder", re.IGNORECASE)
_ELLIPSIS_RE = re.compile(r"\s*(?:\[\s*(?:…|\.\.\.)\s*\]|\(\s*(?:…|\.\.\.)\s*\)|…|\.\.\.)\s*")


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class Finding:
    level: str          # MÅSTE eller BÖR
    rule: str           # t.ex. "R05 avsnittsslut"
    place: str          # rad och avsnitt, eller register-id
    action: str         # vad analytikern ska göra

    def as_requirement(self) -> str:
        return f"{self.level} [{self.rule}] {self.place}: {self.action}"


@dataclass
class LintResult:
    level: str
    findings: list[Finding] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def must(self) -> list[Finding]:
        return [f for f in self.findings if f.level == MUST]

    @property
    def should(self) -> list[Finding]:
        return [f for f in self.findings if f.level == SHOULD]

    @property
    def status(self) -> str:
        return "REVISE" if self.must else "PASS"

    def rules_hit(self) -> set[str]:
        return {f.rule.split()[0] for f in self.findings}

    def requirements(self) -> list[str]:
        return [f.as_requirement() for f in self.must + self.should]

    def to_markdown(self, version: int) -> str:
        lines = [f"# Rapportkontroll, utkast {version}", "",
                 f"Status: {self.status}. Nivå: {self.level}. "
                 f"MÅSTE: {len(self.must)}. BÖR: {len(self.should)}.", ""]
        for title, items in (("MÅSTE", self.must), ("BÖR", self.should)):
            lines += [f"## {title}", ""]
            if not items:
                lines += ["Inga fynd.", ""]
                continue
            lines += ["| Regel | Plats | Åtgärd |", "|---|---|---|"]
            lines += [f"| {_cell(f.rule)} | {_cell(f.place)} | {_cell(f.action)} |" for f in items]
            lines.append("")
        if self.skipped:
            lines += ["## Ej kontrollerat", ""]
            lines += [f"- {s}" for s in self.skipped]
            lines.append("")
        return "\n".join(lines)


# ── Markdown-struktur ─────────────────────────────────────────────────────────

@dataclass
class Section:
    level: int
    title: str
    line: int                                   # 1-baserat radnummer för rubriken
    body: list[tuple[int, str]] = field(default_factory=list)   # egna rader före nästa rubrik

    @property
    def key(self) -> str:
        return normalize_title(self.title)


def normalize_title(title: str) -> str:
    """'## 9. Källförteckning' → 'källförteckning'."""
    t = _NUMBERED_TITLE_RE.sub("", title.strip())
    t = re.sub(r"^[–—:\-\s]+", "", t)
    return t.strip().strip("*").strip().lower()


def parse_sections(markdown: str) -> tuple[list[tuple[int, str]], list[Section]]:
    """Dela texten i rader (utanför kodblock) och avsnitt. Text före första rubriken
    hamnar i ett avsnitt med nivå 0."""
    lines: list[tuple[int, str]] = []
    sections: list[Section] = [Section(0, "", 0)]
    in_fence = False
    for no, raw in enumerate(markdown.splitlines(), start=1):
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            sections[-1].body.append((no, raw))
            continue
        if not in_fence:
            m = _HEADING_RE.match(raw)
            if m:
                sections.append(Section(len(m.group(1)), m.group(2).strip(), no))
                continue
        lines.append((no, raw))
        sections[-1].body.append((no, raw))
    return lines, sections


def _content(body: list[tuple[int, str]]) -> list[tuple[int, str]]:
    out = []
    for no, text in body:
        s = text.strip()
        if not s or re.fullmatch(r"[-*_]{3,}", s) or s.startswith("<!--"):
            continue
        out.append((no, text))
    return out


def _place(section: Section, line: int | None = None) -> str:
    name = section.title or "(före första rubriken)"
    return f"rad {line or section.line}, avsnitt \"{name}\""


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _expand_citation(group: str) -> list[int]:
    nums: list[int] = []
    for part in re.split(r"\s*[,;]\s*", group):
        m = re.fullmatch(r"(\d+)\s*[–-]\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 < b - a < 50:
                nums.extend(range(a, b + 1))
                continue
            nums.extend([a, b])
        elif part.isdigit():
            nums.append(int(part))
    return nums


def _is_reference(section: Section) -> bool:
    return section.level >= 1 and section.key in REFERENCE_TITLES


def _is_appendix(section: Section) -> bool:
    return section.level >= 1 and section.key.split(" ")[0] in APPENDIX_TITLES


def _split_regions(sections: list[Section]) -> tuple[list[Section], list[Section], list[Section]]:
    """Dela avsnitten i brödtext, källförteckning och bilagor (inklusive underavsnitt)."""
    body, refs, appx = [], [], []
    mode, mode_level = "body", 0
    for sec in sections:
        if mode != "body" and sec.level and sec.level <= mode_level:
            mode = "body"
        if _is_reference(sec):
            mode, mode_level = "refs", sec.level
        elif _is_appendix(sec):
            mode, mode_level = "appx", sec.level
        {"body": body, "refs": refs, "appx": appx}[mode].append(sec)
    return body, refs, appx


# ── Normalisering för citatsökning ────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Gör källtext och citat jämförbara: ligaturer, citattecken, bindestreck och blanktecken."""
    s = unicodedata.normalize("NFKC", text or "")
    s = s.replace("\u00ad", "")
    # Alla citattecken likställs: citat skrivs ofta om från “…” till '…' eller tvärtom.
    s = s.translate(str.maketrans({"’": "'", "‘": "'", "‚": "'", "“": "'", "”": "'", "„": "'",
                                   "«": "'", "»": "'", '"': "'", "–": "-", "—": "-", "‐": "-", "‑": "-"}))
    s = re.sub(r"\s+", " ", s).lower()
    s = re.sub(r"(\w)- (\w)", r"\1\2", s)     # avstavning över radbrytning i PDF-text
    s = re.sub(r"[*_`]", "", s)
    return s.strip()


def quote_found(quote: str, haystack: str) -> bool:
    """Sant om citatet finns i texten. '…' delar citatet i delar som ska hittas i ordning."""
    fragments = [normalize_text(f) for f in _ELLIPSIS_RE.split(quote or "")]
    fragments = [f.strip(" '") for f in fragments if len(f.strip(" '")) >= MIN_FRAGMENT_CHARS]
    if not fragments:
        return False
    pos = 0
    for frag in fragments:
        idx = haystack.find(frag, pos)
        if idx < 0:
            return False
        pos = idx + len(frag)
    return True


def source_haystack(source: dict, run_dir: Path | None) -> str:
    """All text vi har läst för en källa: fulltextfilen, sammanfattningen, utdrag och citat."""
    parts = [source.get("abstract") or "", (source.get("fetch") or {}).get("excerpt") or ""]
    parts += [q.get("text") or "" for q in source.get("quotes") or [] if isinstance(q, dict)]
    text_path = source.get("text_path")
    if run_dir and text_path:
        path = Path(run_dir) / text_path
        if path.exists():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return normalize_text("\n".join(parts))


# ── Regler: struktur ──────────────────────────────────────────────────────────

def check_headings(sections: list[Section], out: list[Finding]) -> None:
    """R01 exakt en H1, R02 ingen hoppad rubriknivå, R03 ingen egen numrering."""
    h1 = [s for s in sections if s.level == 1]
    if len(h1) != 1:
        where = ", ".join(str(s.line) for s in h1) or "ingen"
        out.append(Finding(MUST, "R01 en-h1", f"H1 på rad {where}",
                           f"Rapporten har {len(h1)} H1. Behåll en H1 (titeln) och gör övriga till H2/H3."))
    prev = 0
    for s in sections[1:]:
        if prev and s.level > prev + 1:
            out.append(Finding(MUST, "R02 rubrikniva", _place(s),
                               f"Rubriken hoppar från H{prev} till H{s.level}. Använd H{prev + 1}."))
        prev = s.level
    numbered = [s.line for s in sections[1:] if _NUMBERED_TITLE_RE.match(s.title)]
    if numbered:
        out.append(Finding(MUST, "R03 numrering", f"rubrikerna på rad {_numlist(numbered)}",
                           f"{len(numbered)} rubriker har egen numrering. Ta bort numreringen."))


def check_sections(sections: list[Section], out: list[Finding]) -> None:
    """R04 inget tomt avsnitt, R05 varje avsnitt slutar med skiljetecken eller tabellrad."""
    for i, s in enumerate(sections):
        if s.level == 0:
            continue
        content = _content(s.body)
        nxt = sections[i + 1] if i + 1 < len(sections) else None
        if not content:
            if nxt is None or nxt.level <= s.level:
                out.append(Finding(MUST, "R04 tomt-avsnitt", _place(s),
                                   "Avsnittet är tomt. Skriv innehållet eller ta bort rubriken."))
            continue
        if s.level == 1 or _is_reference(s) or _is_appendix(s):
            continue
        no, last = content[-1]
        stripped = last.strip()
        if stripped.startswith("|") or _FENCE_RE.match(stripped):
            continue
        tail = stripped.rstrip(_TRAILING_MARKUP)
        if not tail.endswith(_END_OK):
            snippet = stripped[-60:]
            out.append(Finding(MUST, "R05 avsnittsslut", _place(s, no),
                               f"Avsnittet slutar mitt i en mening (\"…{snippet}\"). Skriv klart avsnittet."))


def check_response(response: dict | None, out: list[Finding], skipped: list[str]) -> None:
    """R06 svaret avbröts inte för att det blev för långt."""
    if response is None:
        skipped.append("R06 avbrutet-svar: inga svarsdata från anropet.")
        return
    stop = (response.get("stop_reason") or "").lower()
    tokens = int(response.get("output_tokens") or 0)
    ceiling = int(response.get("ceiling") or OUTPUT_TOKEN_CEILING)
    if response.get("complete") is False:
        out.append(Finding(MUST, "R06 avbrutet-svar", "svaret",
                           "Slutmarkören saknas, svaret avbröts. Skriv en kortare rapport som ryms i ett svar."))
    elif stop in ("max_tokens", "length"):
        out.append(Finding(MUST, "R06 avbrutet-svar", "svaret",
                           f"Anropet stoppades av {stop}. Skriv en kortare rapport."))
    elif tokens >= ceiling * CEILING_MARGIN:
        out.append(Finding(MUST, "R06 avbrutet-svar", "svaret",
                           f"Svaret har {tokens} tokens, vid taket {ceiling}. Skriv en kortare rapport."))


def check_required(sections: list[Section], level: str, out: list[Finding]) -> None:
    """R10 alla obligatoriska avsnitt för nivån finns, som H2, i rätt ordning."""
    required = REQUIRED_SECTIONS[level]
    found = [s.key for s in sections if s.level == 2]
    wanted = [r.lower() for r in required]
    for name in required:
        if name.lower() not in found:
            out.append(Finding(MUST, "R10 obligatoriska-avsnitt", f"avsnittet \"{name}\"",
                               f"Avsnittet \"{name}\" saknas för nivå {level}. Lägg till det som H2."))
    present = [k for k in found if k in wanted]
    if present != sorted(present, key=wanted.index):
        out.append(Finding(MUST, "R10 obligatoriska-avsnitt", "avsnittsordningen",
                           "Avsnitten står i fel ordning. Ordningen är: " + ", ".join(required) + "."))


# ── Regler: källor ────────────────────────────────────────────────────────────

def _citations(sections: list[Section]) -> dict[int, int]:
    """n → första rad där [n] citeras."""
    cited: dict[int, int] = {}
    for s in sections:
        for no, text in s.body:
            for m in _CITE_RE.finditer(text):
                for n in _expand_citation(m.group(1)):
                    cited.setdefault(n, no)
    return cited


def _reference_entries(refs: list[Section]) -> dict[int, tuple[int, str]]:
    entries: dict[int, tuple[int, str]] = {}
    for s in refs:
        for no, text in s.body:
            m = _REF_ENTRY_RE.match(text)
            if m:
                entries.setdefault(int(m.group(1) or m.group(2)), (no, text))
    return entries


def check_references(body: list[Section], refs: list[Section], sources: list[dict] | None,
                     out: list[Finding], skipped: list[str]) -> None:
    """R07 [n] finns i källförteckningen, R08 varje post citeras, R09 [n] finns i underlaget,
    R16 läsnivån står i källförteckningen."""
    cited = _citations(body)
    if not refs:
        if cited:
            out.append(Finding(MUST, "R07 ref-saknas", "Källförteckning",
                               "Källförteckningen saknas men texten citerar källor."))
        return
    entries = _reference_entries(refs)
    for n, line in sorted(cited.items()):
        if n not in entries:
            out.append(Finding(MUST, "R07 ref-saknas", f"rad {line}, [{n}]",
                               f"[{n}] citeras men finns inte i källförteckningen."))
    uncited = sorted(n for n in entries if n not in cited)
    if uncited:
        out.append(Finding(MUST, "R08 ociterad-kalla", "Källförteckning",
                           f"{len(uncited)} poster citeras inte i texten ({_numlist(uncited)}). "
                           "Ta bort dem; ta bara med källor som texten citerar."))
    if sources is None:
        skipped.append("R09 ref-i-underlag: 01_sources.json saknas.")
    else:
        known = {s.get("n") for s in sources}
        unknown = sorted(n for n in set(cited) | set(entries) if n not in known)
        if unknown:
            out.append(Finding(MUST, "R09 ref-i-underlag", "text och källförteckning",
                               f"Källorna {_numlist(unknown)} finns inte i 01_sources.json. "
                               "Använd bara källor ur underlaget."))
    missing_level = sorted(n for n, (_, text) in entries.items()
                           if not any(rl in text.lower() for rl in READ_LEVELS))
    if missing_level:
        out.append(Finding(MUST, "R16 lasniva", "Källförteckning",
                           f"Läsnivån saknas för {_numlist(missing_level)}. Ange fulltext, sammanfattning, "
                           "bara titel eller ej åtkomlig per post."))


def check_values(sections: list[Section], refs: list[Section], out: list[Finding]) -> None:
    """R11 inga None, ? eller 'Okänd titel' i tabeller och källförteckning."""
    ref_ids = {id(s) for s in refs}
    for s in sections:
        bad_rows: list[int] = []
        bad_values: set[str] = set()
        for no, text in s.body:
            stripped = text.strip()
            if stripped.startswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                hits = [c for c in cells if _BAD_CELL_RE.match(c)]
            elif id(s) in ref_ids and _REF_ENTRY_RE.match(text):
                hits = _BAD_REF_RE.findall(text)
            else:
                continue
            if hits:
                bad_rows.append(no)
                bad_values.update(h if isinstance(h, str) else h[0] for h in hits)
        if bad_rows:
            out.append(Finding(MUST, "R11 tomma-varden", _place(s, bad_rows[0]),
                               f"{len(bad_rows)} rader innehåller {', '.join(sorted(bad_values))} "
                               f"(rad {_numlist(bad_rows)}). Utelämna uppgiften eller hämta den ur metadata."))


# ── Regler: text ──────────────────────────────────────────────────────────────

def check_quotes(body: list[Section], out: list[Finding]) -> None:
    """R12 inget citat förekommer två gånger."""
    seen: dict[str, int] = {}
    for s in body:
        for no, text in s.body:
            for rx in _QUOTE_RES:
                for m in rx.finditer(text):
                    q = normalize_text(m.group(1))
                    if len(q) < MIN_QUOTE_CHARS:
                        continue
                    if q in seen and seen[q] != no:
                        out.append(Finding(MUST, "R12 dubbelt-citat", _place(s, no),
                                           f"Citatet \"{m.group(1)[:60]}\" finns redan på rad {seen[q]}. "
                                           "Använd det en gång."))
                    seen.setdefault(q, no)


def check_wording(sections: list[Section], body: list[Section], level: str,
                  has_hypothesis: bool | None, out: list[Finding], skipped: list[str]) -> None:
    """R13 negativa slutsatser, R14 emojier och token-räkning, R15 ställningstagande utan
    hypotes, R20 längd."""
    for s in sections:
        for no, text in s.body:
            for rx in _NEGATIVE_RES:
                m = rx.search(text)
                if m:
                    out.append(Finding(SHOULD, "R13 negativ-slutsats", _place(s, no),
                                       f"\"{m.group(0)}\": skriv \"vi har inte funnit\" och ange var vi sökte."))
        hits = [no for no, text in s.body if _EMOJI_RE.search(text) or _TOKENS_RE.search(text)]
        if hits:
            out.append(Finding(MUST, "R14 emoji-tokens", _place(s, hits[0]),
                               f"Emojier eller token-räkning på rad {_numlist(hits)}. Ta bort dem."))
    if has_hypothesis is None:
        skipped.append("R15 stallningstagande: okänt om protokollet har en hypotes.")
    elif not has_hypothesis:
        for s in sections:
            hit = next((no for no, t in s.body if t.strip().startswith("|")
                        and re.search(r"ställningstagande", t, re.IGNORECASE)), None)
            if hit or re.search(r"ställningstagande", s.title, re.IGNORECASE):
                out.append(Finding(MUST, "R15 stallningstagande", _place(s, hit),
                                   "Protokollet har ingen hypotes. Ersätt ställningstagandet med "
                                   "\"roll i rapporten\" (direkt, analogi, bakgrund)."))
    limit = WORD_LIMITS.get(level)
    if limit:
        words = sum(len(t.split()) for s in body for _, t in s.body)
        if words > limit:
            out.append(Finding(SHOULD, "R20 langd", "hela rapporten",
                               f"Rapporten har {words} ord före källförteckningen; nivå {level} "
                               f"tål cirka {limit}. Korta."))


# ── Regler: påståenderegistret ────────────────────────────────────────────────

def check_claims(claims: list | None, level: str, sources: list[dict] | None,
                 run_dir: Path | None, out: list[Finding], skipped: list[str]) -> None:
    """R17 varje 'belagt' har ett citat som finns i källtexten, R18 registrets källor och
    läsnivåer stämmer mot underlaget, R19 geografisk konvergens kräver två länder."""
    if claims is None:
        skipped.append("R17–R19 register: inget påståenderegister.")
        return
    if not isinstance(claims, list):
        out.append(Finding(MUST, "R18 register-format", "registret",
                           "Registret ska vara en lista med påståenden."))
        return
    if not claims and level != "snabb":
        out.append(Finding(MUST, "R18 register-format", "registret",
                           "Registret är tomt. Lämna en rad per centralt påstående."))
    by_n = {s.get("n"): s for s in sources or []}
    haystacks: dict[int, str] = {}
    for i, c in enumerate(claims, start=1):
        if not isinstance(c, dict):
            out.append(Finding(MUST, "R18 register-format", f"registrets rad {i}",
                               "Varje rad ska vara ett objekt."))
            continue
        cid = str(c.get("id") or f"rad {i}")
        place = f"register {cid}"
        status = c.get("status")
        nums = c.get("sources")
        problems = []
        if not (c.get("claim") or "").strip():
            problems.append("påståendet saknas")
        if status not in CLAIM_STATUSES:
            problems.append(f"status {status!r} är inte en av {', '.join(CLAIM_STATUSES)}")
        if c.get("read_level") not in READ_LEVELS:
            problems.append(f"läsnivå {c.get('read_level')!r} är okänd")
        if not isinstance(nums, list) or not nums or not all(isinstance(n, int) for n in nums):
            problems.append("källor ska vara en icke-tom lista med nummer")
            nums = []
        if problems:
            out.append(Finding(MUST, "R18 register-format", place, "; ".join(problems).capitalize() + "."))
        if sources is None:
            continue
        unknown = [n for n in nums if n not in by_n]
        if unknown:
            out.append(Finding(MUST, "R18 register-kallor", place,
                               f"Källorna {_numlist(unknown)} finns inte i underlaget."))
        known = [by_n[n] for n in nums if n in by_n]
        if known and c.get("read_level") in READ_RANK:
            best = max(READ_RANK.get(s.get("read_level"), 0) for s in known)
            if READ_RANK[c["read_level"]] > best:
                out.append(Finding(MUST, "R18 register-lasniva", place,
                                   f"Påståendet anger läsnivå {c['read_level']}, men källorna är bara "
                                   "lästa på lägre nivå. Ange den läsnivå som faktiskt lästs."))
        if status == "belagt":
            quote = (c.get("quote") or "").strip()
            if not quote:
                out.append(Finding(MUST, "R17 register-citat", place,
                                   "Påståendet är \"belagt\" men saknar citat. Lägg till ett ordagrant "
                                   "citat eller ändra status."))
            elif known:
                for s in known:
                    if s["n"] not in haystacks:
                        haystacks[s["n"]] = source_haystack(s, run_dir)
                if not any(quote_found(quote, haystacks[s["n"]]) for s in known):
                    out.append(Finding(MUST, "R17 register-citat", place,
                                       f"Citatet \"{quote[:60]}\" finns inte i källtexten eller "
                                       f"sammanfattningen för {_numlist([s['n'] for s in known])}. "
                                       "Kopiera citatet ordagrant eller ändra status."))
        if known and _CONVERGENCE_RE.search(c.get("claim") or ""):
            countries = {cc for s in known for cc in s.get("country_codes") or []}
            if len(countries) < 2:
                out.append(Finding(MUST, "R19 geografi", place,
                                   f"Påståendet anger geografisk konvergens, men källornas metadata visar "
                                   f"{len(countries)} land. Stryk konvergensen."))
    if sources is None:
        skipped.append("R17–R19: källtexter saknas, bara registrets format kontrollerat.")


# ── Main entry ────────────────────────────────────────────────────────────────

def lint_report(markdown: str, level: str = DEFAULT_LEVEL, sources: list[dict] | None = None,
                claims: list | None = None, run_dir: Path | None = None,
                response: dict | None = None, has_hypothesis: bool | None = None) -> LintResult:
    """Kör alla regler. `sources` är listan ur source_model.read_sources, `claims` listan
    under "claims" i 02_claims_v<k>.json, `response` svarsdata från anropet."""
    if level not in LEVELS:
        raise ValueError(f"Okänd nivå: {level!r}")
    result = LintResult(level)
    out, skipped = result.findings, result.skipped
    _, sections = parse_sections(markdown)
    body, refs, _appx = _split_regions(sections)

    check_headings(sections, out)
    check_sections(sections, out)
    check_response(response, out, skipped)
    check_references(body, refs, sources, out, skipped)
    check_required(sections, level, out)
    check_values(sections, refs, out)
    check_quotes(body, out)
    check_wording(sections, body, level, has_hypothesis, out, skipped)
    check_claims(claims, level, sources, run_dir, out, skipped)
    return result


def cited_numbers(markdown: str) -> list[int]:
    """Källnummer som brödtexten citerar (utan källförteckning och bilagor), sorterade."""
    _, sections = parse_sections(markdown)
    body, _, _ = _split_regions(sections)
    return sorted(_citations(body))


def write_lint(run_dir: Path, version: int, result: LintResult) -> Path:
    path = Path(run_dir) / f"03_lint_v{version}.md"
    path.write_text(result.to_markdown(version), encoding="utf-8")
    return path


def _numlist(nums) -> str:
    nums = list(nums)
    shown = ", ".join(str(n) for n in nums[:15])
    return shown + (f" och {len(nums) - 15} till" if len(nums) > 15 else "")
