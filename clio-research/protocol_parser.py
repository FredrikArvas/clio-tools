"""
protocol_parser.py
Läser ett protokoll till research-pipeline v2: den ifyllda mallen (.md enligt
PROMPT_TEMPLATE.md) eller det äldre JSON-protokollet. Båda blir samma struktur, som
collector.py (S1) och report_writer.py (S2) läser.

Usage:
    from protocol_parser import load_protocol, find_protocol, ProtocolError
    path = find_protocol("clio-research-021", inbox_dir)   # .md före .json
    protocol = load_protocol(path)

En ofullständig mall ger ProtocolError med en rad per fel (kvarlämnade platshållare,
saknad huvudfråga, inga delfrågor, inga söktermer, ogiltig nivå …). Det enda som får
ett standardvärde är det planen anger: `niva` standard och `spridning` intern.

Normaliserat protokoll (de fält som används i flödet):
    protocol_id, title, niva, spridning, max_revisions, format ("md" | "json")
    question: {natural_language, sub_questions, keywords_primary {språk: [termer]},
               keywords_adversarial, key_researchers}
    hypothesis, context, scope
    search_strategy: {phases: [...]}       faser 1–4 körs av search_runner
    primary_sources: [{source, where, priority}]
    web_targets:     [{database, term, purpose}]   databaser utan connector
    direct_urls:     [url, ...]
    review_criteria: [text, ...]
    output: {...}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "1.0.0"

LEVELS = ("snabb", "standard", "delbar")
SPREADS = ("intern", "delbar")
DEFAULT_LEVEL = "standard"
DEFAULT_SPREAD = "intern"
MAX_REVISIONS = 2
UNSPECIFIED_LANG = "ospecificerat"

# Databasnamn i mallens Del 2 → connector i search_runner. Övriga blir webbmål för insamlaren.
CONNECTOR_NAMES = {
    "openalex": "openalex",
    "crossref": "crossref",
    "core": "core",
    "semantic scholar": "semantic_scholar",
    "semanticscholar": "semantic_scholar",
    "cyberleninka": "cyberleninka",
    "j-stage": "jstage",
    "jstage": "jstage",
}
DEFAULT_INDEXES = ("openalex", "crossref", "core")

_PLACEHOLDER_RE = re.compile(r"\{\{[^}]*\}\}")
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_H3_RE = re.compile(r"^###\s+(.+?)\s*$")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_URL_RE = re.compile(r"https?://\S+")
_META_KEYS = {
    "run-id": "run_id", "run id": "run_id", "titel": "title", "datum": "date",
    "nivå": "niva", "niva": "niva", "spridning": "spridning", "profil": "profile",
    "max revisionsvarv": "max_revisions", "projekt": "project", "fråga": "question",
    "huvudfråga": "question", "version": "version", "författare": "author",
}


class ProtocolError(ValueError):
    """Protokollet går inte att köra. `problems` listar varje fel."""

    def __init__(self, problems: list[str], path: Path | str | None = None):
        self.problems = list(problems)
        where = f" ({Path(path).name})" if path else ""
        super().__init__(f"Protokollet är ofullständigt{where}:\n  - " + "\n  - ".join(self.problems))


# ── Hitta och läsa ────────────────────────────────────────────────────────────

def find_protocol(protocol_id: str, inbox_dir: Path) -> Path:
    """Hitta protokollfilen i inbox. Mallen (.md) går före JSON. Tar emot id, filnamn
    eller sökväg. Filnamn som börjar med id följt av `_` godtas (clio-research-021_kort.md)."""
    candidate = Path(protocol_id)
    if candidate.suffix in (".md", ".json") and candidate.exists():
        return candidate
    inbox_dir = Path(inbox_dir)
    for suffix in (".md", ".json"):
        exact = inbox_dir / f"{protocol_id}{suffix}"
        if exact.exists():
            return exact
        matches = sorted(p for p in inbox_dir.glob(f"{protocol_id}_*{suffix}") if not p.stem.endswith("-sources"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ProtocolError([f"flera filer matchar {protocol_id!r}: "
                                 + ", ".join(p.name for p in matches)])
    raise FileNotFoundError(f"Protokollfil saknas för {protocol_id!r} i {inbox_dir}")


def load_protocol(path: Path) -> dict:
    """Läs .md eller .json och returnera det normaliserade protokollet."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".json":
        return parse_json(json.loads(text), path)
    return parse_markdown(text, path)


# ── JSON (äldre format) ───────────────────────────────────────────────────────

def parse_json(data: dict, path: Path | str | None = None) -> dict:
    problems: list[str] = []
    if not isinstance(data, dict):
        raise ProtocolError(["JSON-protokollet är inte ett objekt"], path)
    for name in ("protocol_id", "question", "search_strategy", "output"):
        if name not in data:
            problems.append(f"fältet {name} saknas")
    q = data.get("question") if isinstance(data.get("question"), dict) else {}
    if not str(q.get("natural_language") or "").strip():
        problems.append("question.natural_language saknas")
    if not q.get("keywords_primary"):
        problems.append("question.keywords_primary saknas")
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    level, spread = _level_and_spread(data.get("niva", output.get("niva")),
                                      data.get("spridning", output.get("spridning")), problems)
    max_rev = _max_revisions(data.get("max_revisions", output.get("max_revisions")), problems)
    if problems:
        raise ProtocolError(problems, path)

    keywords = q.get("keywords_primary")
    if isinstance(keywords, list):
        keywords = {UNSPECIFIED_LANG: keywords}
    context = data.get("context") or ""
    if isinstance(context, dict):
        context = "\n".join(f"{k}: {v}" for k, v in context.items() if isinstance(v, str))
    hypothesis = data.get("hypothesis")
    if isinstance(hypothesis, dict):
        hypothesis = hypothesis.get("primary")
    phases = (data.get("search_strategy") or {}).get("phases") or []
    direct = [u for ph in phases for u in (ph.get("direct_fetches") or []) if isinstance(u, str)]
    primary = []
    for item in q.get("key_sources_to_fetch") or []:
        if isinstance(item, str):
            primary.append({"source": item, "where": "", "priority": ""})
        elif isinstance(item, dict):
            primary.append({"source": str(item.get("title") or item.get("source") or item),
                            "where": str(item.get("url") or item.get("where") or ""),
                            "priority": str(item.get("priority") or "")})
    return {
        "format": "json",
        "protocol_id": data["protocol_id"],
        "title": data.get("title") or data.get("topic_label") or "",
        "niva": level,
        "spridning": spread,
        "max_revisions": max_rev,
        "question": {
            "natural_language": q["natural_language"].strip(),
            "sub_questions": [str(s).strip() for s in (q.get("sub_questions") or []) if str(s).strip()],
            "keywords_primary": keywords,
            "keywords_adjacent": q.get("keywords_adjacent") or {},
            "keywords_adversarial": q.get("keywords_adversarial") or {},
            "key_researchers": q.get("key_researchers") or [],
        },
        "hypothesis": (hypothesis or "").strip() or None,
        "context": str(context).strip(),
        "scope": str(data.get("scope") or "").strip(),
        "search_strategy": {"phases": phases},
        "primary_sources": primary,
        "web_targets": [],
        "direct_urls": direct,
        "review_criteria": list(data.get("review_criteria") or []),
        "output": output,
    }


# ── Mallen (.md) ──────────────────────────────────────────────────────────────

def parse_markdown(text: str, path: Path | str | None = None) -> dict:
    lines = text.splitlines()
    problems: list[str] = []

    for no, line in enumerate(lines, 1):
        if line.lstrip().startswith(">"):
            continue                         # mallens egen instruktion om platshållare
        for match in _PLACEHOLDER_RE.findall(line):
            problems.append(f"platshållare kvar på rad {no}: {match}")

    sections = _split(lines)
    meta = _metadata(_sub(_section(sections, "metadata"), ""))
    if not _section(sections, "metadata"):
        problems.append("avsnittet METADATA saknas")

    protocol_id = meta.get("run_id", "").strip()
    if not protocol_id or "NNN" in protocol_id:
        problems.append("Run-ID saknas eller är inte ifyllt (clio-research-NNN)")
    title = meta.get("title", "").strip()
    if not title:
        problems.append("Titel saknas i METADATA")
    level, spread = _level_and_spread(meta.get("niva"), meta.get("spridning"), problems)
    max_rev = _max_revisions(meta.get("max_revisions"), problems)

    tasks = _section(sections, "forskningsuppgifter")
    question = meta.get("question", "").strip() or _prose(_sub(tasks, "huvudfråga"))
    if not question:
        problems.append("huvudfrågan saknas (### Huvudfråga under FORSKNINGSUPPGIFTER, eller Fråga: i METADATA)")

    subq = [m.group(1) for line in _sub(tasks, "del 3") for m in [_NUMBERED_RE.match(line)] if m]
    if not subq:
        problems.append("Del 3 har inga numrerade frågor")

    primary = [{"source": _strip_md(r[0]), "where": r[1] if len(r) > 1 else "",
                "priority": r[2] if len(r) > 2 else ""}
               for r in _table(_sub(tasks, "del 1"), skip_first_col=True)]
    searches = [{"database": r[0], "term": r[1] if len(r) > 1 else "", "purpose": r[2] if len(r) > 2 else ""}
                for r in _table(_sub(tasks, "del 2"))]
    searches = [s for s in searches if s["term"].strip()]
    if not primary and not searches:
        problems.append("inga söktermer: både Del 1 (primärkällor) och Del 2 (databassökning) är tomma")

    hyp = _prose(_sub(tasks, "hypotes")) or meta.get("hypothesis", "")
    if hyp.strip().lower().rstrip(".") in ("", "ingen", "ingen uttalad hypotes", "-"):
        hyp = ""

    if problems:
        raise ProtocolError(problems, path)

    background = _section(sections, "bakgrundskontext")
    context = "\n\n".join(p for p in (
        _prose(_sub(background, "projekt och syfte")),
        _prose(_sub(background, "centrala begrepp")),
        _prose(_sub(background, "vad är redan känt")),
    ) if p)
    scope = _prose(_sub(background, "avgränsning"))
    criteria = [m.group(1) for line in _all(_section(sections, "granskningskriterier"))
                for m in [_BULLET_RE.match(line) or _NUMBERED_RE.match(line)] if m]

    keywords: dict[str, list[str]] = {}
    connectors: list[str] = list(DEFAULT_INDEXES)
    web_targets = []
    for s in searches:
        lang = UNSPECIFIED_LANG
        keywords.setdefault(lang, [])
        if s["term"] not in keywords[lang]:
            keywords[lang].append(s["term"])
        name = _connector(s["database"])
        if name and name not in connectors:
            connectors.append(name)
        if not name:
            web_targets.append(s)
    urls = []
    for p in primary:
        urls += [u.rstrip(").,") for u in _URL_RE.findall(p["where"])]

    phases = []
    titles = [p["source"] for p in primary if p["source"]]
    if titles:
        phases.append({"phase": 1, "label": "Primärkällor", "databases": ["openalex", "crossref"],
                       "keywords": titles, "max_results": 3 * len(titles)})
    terms = keywords.get(UNSPECIFIED_LANG, [])
    if terms:
        phases.append({"phase": 2, "label": "Databassökning", "databases": connectors,
                       "keywords": terms, "max_results": 100})

    return {
        "format": "md",
        "protocol_id": protocol_id,
        "title": title,
        "niva": level,
        "spridning": spread,
        "max_revisions": max_rev,
        "question": {
            "natural_language": question,
            "sub_questions": subq,
            "keywords_primary": keywords,
            "keywords_adjacent": {},
            "keywords_adversarial": {},
            "key_researchers": [],
        },
        "hypothesis": hyp.strip() or None,
        "context": context,
        "scope": scope,
        "search_strategy": {"phases": phases},
        "primary_sources": primary,
        "web_targets": web_targets,
        "direct_urls": urls,
        "review_criteria": criteria,
        "output": {"profile": meta.get("profile") or "aiab"},
    }


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _level_and_spread(level, spread, problems: list[str]) -> tuple[str, str]:
    level = (str(level).strip().lower() if level not in (None, "") else DEFAULT_LEVEL)
    spread = (str(spread).strip().lower() if spread not in (None, "") else DEFAULT_SPREAD)
    if level not in LEVELS:
        problems.append(f"nivå {level!r} är inte en av {', '.join(LEVELS)}")
    if spread not in SPREADS:
        problems.append(f"spridning {spread!r} är inte en av {', '.join(SPREADS)}")
    return level, spread


def _max_revisions(value, problems: list[str]) -> int:
    if value in (None, ""):
        return MAX_REVISIONS
    try:
        n = int(str(value).strip())
    except ValueError:
        problems.append(f"Max revisionsvarv {value!r} är inte ett heltal")
        return MAX_REVISIONS
    if not 0 <= n <= MAX_REVISIONS:
        problems.append(f"Max revisionsvarv måste vara 0–{MAX_REVISIONS}, fick {n}")
    return n


def _key(heading: str) -> str:
    """Rubrik → nyckel: gemener, utan emoji och skiljetecken i början och slutet."""
    return re.sub(r"^[^\wåäö]+|[^\wåäö)]+$", "", heading.strip().lower())


def _split(lines: list[str]) -> dict[str, dict[str, list[str]]]:
    """{h2-nyckel: {h3-nyckel ("" före första h3): [rader]}}. Kodblock följer med som rader."""
    out: dict[str, dict[str, list[str]]] = {}
    h2, h3 = None, ""
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence:
            m2, m3 = _H2_RE.match(line), _H3_RE.match(line)
            if m2 and not line.startswith("###"):
                h2, h3 = _key(m2.group(1)), ""
                out.setdefault(h2, {"": []})
                continue
            if m3 and h2 is not None:
                h3 = _key(m3.group(1))
                out[h2].setdefault(h3, [])
                continue
        if h2 is not None:
            out[h2].setdefault(h3, []).append(line)
    return out


def _section(sections: dict, prefix: str) -> dict[str, list[str]]:
    for key, value in sections.items():
        if key.startswith(prefix):
            return value
    return {}


def _sub(section: dict[str, list[str]], prefix: str) -> list[str]:
    for key, lines in section.items():
        if key.startswith(prefix):
            return lines
    return []


def _all(section: dict[str, list[str]]) -> list[str]:
    return [line for lines in section.values() for line in lines]


def _metadata(lines: list[str]) -> dict[str, str]:
    """Nyckel: värde-rader inne i METADATA-avsnittets första kodblock (förklarande text
    utanför blocket läses inte)."""
    meta = {}
    fences = [i for i, l in enumerate(lines) if l.strip().startswith("```")]
    if len(fences) >= 2:
        lines = lines[fences[0] + 1:fences[1]]
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        name = _META_KEYS.get(key.strip().lower())
        if name:
            meta[name] = value.strip()
    return meta


def _prose(lines: list[str]) -> str:
    kept = [l.rstrip() for l in lines if l.strip() and l.strip() != "---" and not l.strip().startswith("```")]
    return "\n".join(kept).strip()


def _table(lines: list[str], skip_first_col: bool = False) -> list[list[str]]:
    rows = []
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    rows = rows[1:]                          # rubrikraden
    if skip_first_col:
        rows = [r[1:] for r in rows if len(r) > 1]
    return [r for r in rows if any(r)]


def _strip_md(text: str) -> str:
    return re.sub(r"[*_`]", "", text).strip()


def _connector(database: str) -> str | None:
    name = database.strip().lower()
    for key, connector in CONNECTOR_NAMES.items():
        if re.search(rf"\b{re.escape(key)}\b", name):
            return connector
    return None
