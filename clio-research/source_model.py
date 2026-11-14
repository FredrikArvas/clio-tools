"""
source_model.py
Källformatet för research-pipeline v2: en källa i `01_sources.json`.

Kontraktet står i PLAN_research_pipeline_v2.md avsnitt 12 och är bindande mellan
insamlingen (spår 1) och rapportskrivningen (spår 2). Fältnamnen får inte ändras.

    {
      "n": 3,
      "source_id": "openalex:W123",
      "title": "…", "authors": ["…"], "year": 2014,
      "doi": "10.…", "url": "https://…",
      "database": "openalex",
      "source_type": "peer-reviewed | konferens | rapport | bok | preprint | webb",
      "country_codes": ["FR"], "institutions": ["CNES"],
      "read_level": "fulltext | sammanfattning | bara titel | ej åtkomlig",
      "read_note": "varför, om inte fulltext",
      "text_path": "kallor/k03.md",
      "abstract": "…",
      "quotes": [{"text": "ordagrant", "where": "s. 4 / avsnitt 2.1"}],
      "relevance": {"role": "direkt | analogi | bakgrund | felträff", "why": "…", "similarity": 0.43},
      "quality": {"citations": 12, "age_years": 12, "assessment": null},
      "fetch": {"route": "…", "license": "…", "chars": 70094, "excerpt": "…", "error": "HTTP 403"}
    }

Regler som modulen upprätthåller:
    - `n` sätts en gång och ändras aldrig. Felträffar tar med sig sitt nummer till
      `01_filtered.json`, så numren i `01_sources.json` kan ha luckor.
    - `country_codes` och `institutions` kommer ur metadata. Tom lista betyder okänt.
    - `source_type` är `null` när API:et inte ger något entydigt (utvidgning av kontraktet).
    - Validering ger fel med fältnamn. Inga standardvärden fylls i tyst.

Filer:
    01_sources.json   {"schema": "clio-research/sources", "version": 1, "sources": [...]}
    01_filtered.json  {"schema": "clio-research/filtered", "version": 1, "sources": [...]}
                      där varje källa har `filtered: {"stage": "likhet | relevans", "reason": "…"}`
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "1.0.0"

SCHEMA_VERSION = 1
SOURCES_FILE = "01_sources.json"
FILTERED_FILE = "01_filtered.json"
TEXT_DIR = "kallor"
EXCERPT_MAX_CHARS = 8000

SOURCE_TYPES = ("peer-reviewed", "konferens", "rapport", "bok", "preprint", "webb")
READ_LEVELS = ("fulltext", "sammanfattning", "bara titel", "ej åtkomlig")
ASSESSABLE_READ_LEVELS = ("fulltext", "sammanfattning")
ROLES = ("direkt", "analogi", "bakgrund", "felträff")
ROLE_MISMATCH = "felträff"
FETCH_ROUTES = (
    "openalex_pdf", "unpaywall", "core", "direct_url",
    "wayback", "semantic_scholar", "model_pdf", "none",
)
FILTER_STAGES = ("likhet", "relevans")
ASSESSMENT_SCORES = ("method", "independence", "falsification")

REQUIRED_FIELDS = (
    "n", "source_id", "title", "authors", "year", "doi", "url", "database",
    "source_type", "country_codes", "institutions", "read_level", "read_note",
    "text_path", "abstract", "quotes", "relevance", "quality",
)
OPTIONAL_FIELDS = ("fetch", "filtered", "language", "journal", "phase_found")
RELEVANCE_FIELDS = ("role", "why", "similarity")
QUALITY_FIELDS = ("citations", "age_years", "assessment")
FETCH_FIELDS = ("route", "license", "chars", "excerpt", "error")

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_TEXT_PATH_RE = re.compile(rf"^{TEXT_DIR}/k\d{{2,}}\.md$")


class SourceError(ValueError):
    """En källa eller en källfil bryter mot kontraktet. `problems` listar varje fel."""

    def __init__(self, problems: list[str], label: str = "källa"):
        self.problems = list(problems)
        super().__init__(f"Ogiltig {label}: " + "; ".join(self.problems))


# ── Råträff → källa ───────────────────────────────────────────────────────────

def from_raw_hit(raw: dict) -> dict:
    """Gör om en rå connectorträff till en källa enligt kontraktet.

    Källan får inget `n` (sätts av `assign_numbers`) och ingen relevansroll (sätts
    efter insamlarmodellens bedömning). Läsnivån speglar vad träffen faktiskt
    innehåller: en sammanfattning eller bara en titel.

    Raises:
        SourceError: om träffen saknar titel eller databas.
    """
    problems = []
    title = _clean(raw.get("title"))
    database = _clean(raw.get("database"))
    if not title:
        problems.append("title saknas i råträffen")
    if not database:
        problems.append("database saknas i råträffen")
    if problems:
        raise SourceError(problems, "råträff")

    doi = normalize_doi(raw.get("doi"))
    abstract = _clean(raw.get("abstract"))
    external_id = _clean(raw.get("external_id")) or doi or _clean(raw.get("source_id"))
    if not external_id:
        raise SourceError(["varken external_id, doi eller source_id finns i råträffen"], "råträff")

    return {
        "n": None,
        "source_id": f"{database}:{external_id}",
        "title": title,
        "authors": [a for a in (raw.get("authors") or []) if isinstance(a, str) and a.strip()],
        "year": raw.get("year") if isinstance(raw.get("year"), int) else None,
        "doi": doi,
        "url": _clean(raw.get("url")) or _clean(raw.get("fulltext_url")) or (f"https://doi.org/{doi}" if doi else None),
        "database": database,
        "source_type": raw.get("source_type"),
        "country_codes": list(raw.get("country_codes") or []),
        "institutions": list(raw.get("institutions") or []),
        "read_level": "sammanfattning" if abstract else "bara titel",
        "read_note": "Fulltext inte hämtad än." if abstract else "Fulltext inte hämtad än; träffen saknar sammanfattning.",
        "text_path": None,
        "abstract": abstract,
        "quotes": [],
        "relevance": {"role": None, "why": None, "similarity": None},
        "quality": {
            "citations": raw.get("citation_count") if isinstance(raw.get("citation_count"), int) else None,
            "age_years": None,
            "assessment": None,
        },
        "language": raw.get("language"),
        "journal": raw.get("journal"),
        "phase_found": raw.get("phase_found"),
    }


def normalize_doi(doi: str | None) -> str | None:
    """Ta bort resolver-prefix och gör DOI:n gemen. Returnerar None om den är tom."""
    value = _clean(doi)
    if not value:
        return None
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", value, flags=re.IGNORECASE)
    return value.lower() or None


def text_path_for(n: int) -> str:
    """Relativ sökväg (från körkatalogen) till källans sparade fulltext."""
    if not _is_int(n) or n < 1:
        raise SourceError([f"n måste vara ett positivt heltal för att ge en textfil, fick {n!r}"])
    return f"{TEXT_DIR}/k{n:02d}.md"


# ── Numrering ─────────────────────────────────────────────────────────────────

def assign_numbers(sources: list[dict], taken: set[int] | None = None) -> list[dict]:
    """Ge varje källa utan `n` nästa lediga nummer. Redan satta nummer rörs aldrig.

    Args:
        sources: Källorna i den ordning de ska numreras.
        taken:   Nummer som redan är upptagna någon annanstans (t.ex. i 01_filtered.json).

    Raises:
        SourceError: om två källor redan delar nummer, eller ett nummer krockar med `taken`.
    """
    used = set(taken or ())
    problems = []
    for src in sources:
        n = src.get("n")
        if n is None:
            continue
        if not _is_int(n) or n < 1:
            problems.append(f"n={n!r} är inte ett positivt heltal ({src.get('source_id')})")
        elif n in used:
            problems.append(f"n={n} används av flera källor")
        else:
            used.add(n)
    if problems:
        raise SourceError(problems, "numrering")

    next_n = max(used, default=0) + 1
    for src in sources:
        if src.get("n") is None:
            src["n"] = next_n
            next_n += 1
    return sources


# ── Validering ────────────────────────────────────────────────────────────────

def validate_source(source: dict, complete: bool = True) -> None:
    """Kontrollera en källa mot kontraktet.

    Args:
        source:   Källan.
        complete: True kräver att `n` och `relevance.role` är satta (det som gäller i
                  01_sources.json). False tillåter att de är None, för källor som är
                  på väg genom insamlingen.

    Raises:
        SourceError: med en rad per fel.
    """
    problems = _source_problems(source, complete)
    if problems:
        label = f"källa n={source.get('n')!r}" if isinstance(source, dict) else "källa"
        raise SourceError(problems, label)


def _source_problems(src: dict, complete: bool) -> list[str]:
    if not isinstance(src, dict):
        return [f"källan är inte ett objekt utan {type(src).__name__}"]

    p: list[str] = []
    for name in REQUIRED_FIELDS:
        if name not in src:
            p.append(f"{name} saknas")
    for name in src:
        if name not in REQUIRED_FIELDS and name not in OPTIONAL_FIELDS:
            p.append(f"okänt fält: {name}")
    if p:
        return p

    n = src["n"]
    if n is None:
        if complete:
            p.append("n är inte satt")
    elif not _is_int(n) or n < 1:
        p.append(f"n måste vara ett positivt heltal, fick {n!r}")

    for name in ("source_id", "title", "database"):
        if not _is_text(src[name]):
            p.append(f"{name} måste vara en icke-tom sträng")

    if not _is_str_list(src["authors"]):
        p.append("authors måste vara en lista med strängar")
    if src["year"] is not None and not _is_int(src["year"]):
        p.append(f"year måste vara heltal eller null, fick {src['year']!r}")
    for name in ("doi", "url", "abstract"):
        if src[name] is not None and not _is_text(src[name]):
            p.append(f"{name} måste vara en icke-tom sträng eller null")

    if src["source_type"] is not None and src["source_type"] not in SOURCE_TYPES:
        p.append(f"source_type {src['source_type']!r} är inte en av {', '.join(SOURCE_TYPES)} eller null")

    codes = src["country_codes"]
    if not isinstance(codes, list) or not all(isinstance(c, str) and _COUNTRY_RE.match(c) for c in codes):
        p.append(f"country_codes måste vara en lista med tvåställiga landskoder (versaler), fick {codes!r}")
    if not _is_str_list(src["institutions"]):
        p.append("institutions måste vara en lista med strängar")

    level = src["read_level"]
    if level not in READ_LEVELS:
        p.append(f"read_level {level!r} är inte en av {', '.join(READ_LEVELS)}")
    if src["read_note"] is not None and not isinstance(src["read_note"], str):
        p.append("read_note måste vara en sträng eller null")
    if level in READ_LEVELS and level != "fulltext" and not _is_text(src["read_note"]):
        p.append(f"read_note måste förklara varför läsnivån är {level!r}")

    path = src["text_path"]
    if path is not None and not (isinstance(path, str) and _TEXT_PATH_RE.match(path)):
        p.append(f"text_path måste ha formen {TEXT_DIR}/k<nn>.md eller vara null, fick {path!r}")
    if level == "fulltext" and path is None:
        p.append("read_level fulltext kräver text_path")
    if level == "sammanfattning" and path is None and not _is_text(src["abstract"]):
        p.append("read_level sammanfattning kräver abstract eller text_path")

    p.extend(_quote_problems(src["quotes"]))
    p.extend(_relevance_problems(src["relevance"], complete))
    p.extend(_quality_problems(src["quality"], level))
    if src.get("fetch") is not None:
        p.extend(_fetch_problems(src["fetch"]))
    if src.get("filtered") is not None:
        p.extend(_filtered_problems(src["filtered"]))
    return p


def _quote_problems(quotes) -> list[str]:
    if not isinstance(quotes, list):
        return ["quotes måste vara en lista"]
    p = []
    for i, q in enumerate(quotes):
        if not isinstance(q, dict) or set(q) != {"text", "where"}:
            p.append(f"quotes[{i}] måste ha exakt fälten text och where")
        elif not _is_text(q["text"]) or not _is_text(q["where"]):
            p.append(f"quotes[{i}] har tom text eller tomt where")
    return p


def _relevance_problems(rel, complete: bool) -> list[str]:
    if not isinstance(rel, dict) or set(rel) != set(RELEVANCE_FIELDS):
        return [f"relevance måste ha exakt fälten {', '.join(RELEVANCE_FIELDS)}"]
    p = []
    role, why, sim = rel["role"], rel["why"], rel["similarity"]
    if role is None:
        if complete:
            p.append("relevance.role är inte satt")
        if why is not None:
            p.append("relevance.why är satt men role saknas")
    elif role not in ROLES:
        p.append(f"relevance.role {role!r} är inte en av {', '.join(ROLES)}")
    elif not _is_text(why):
        p.append("relevance.why måste vara en mening när role är satt")
    if sim is not None and (isinstance(sim, bool) or not isinstance(sim, (int, float)) or not -1.0 <= sim <= 1.0):
        p.append(f"relevance.similarity måste vara ett tal mellan -1 och 1 eller null, fick {sim!r}")
    return p


def _quality_problems(quality, read_level) -> list[str]:
    if not isinstance(quality, dict) or set(quality) != set(QUALITY_FIELDS):
        return [f"quality måste ha exakt fälten {', '.join(QUALITY_FIELDS)}"]
    p = []
    for name in ("citations", "age_years"):
        value = quality[name]
        if value is not None and (not _is_int(value) or value < 0):
            p.append(f"quality.{name} måste vara ett icke-negativt heltal eller null, fick {value!r}")
    assessment = quality["assessment"]
    if assessment is not None:
        if read_level not in ASSESSABLE_READ_LEVELS:
            p.append(f"quality.assessment får bara finnas för läsnivå {' eller '.join(ASSESSABLE_READ_LEVELS)}")
        if not isinstance(assessment, dict) or set(assessment) != {*ASSESSMENT_SCORES, "why"}:
            p.append(f"quality.assessment måste ha exakt fälten {', '.join(ASSESSMENT_SCORES)}, why")
        else:
            for name in ASSESSMENT_SCORES:
                if not _is_int(assessment[name]) or not 0 <= assessment[name] <= 3:
                    p.append(f"quality.assessment.{name} måste vara 0–3, fick {assessment[name]!r}")
            if not _is_text(assessment["why"]):
                p.append("quality.assessment.why måste vara en motivering")
    return p


def _fetch_problems(fetch) -> list[str]:
    if not isinstance(fetch, dict) or set(fetch) != set(FETCH_FIELDS):
        return [f"fetch måste ha exakt fälten {', '.join(FETCH_FIELDS)}"]
    p = []
    if fetch["route"] not in FETCH_ROUTES:
        p.append(f"fetch.route {fetch['route']!r} är inte en av {', '.join(FETCH_ROUTES)}")
    if not _is_text(fetch["license"]):
        p.append("fetch.license måste vara en sträng (unknown när den inte är känd)")
    if not _is_int(fetch["chars"]) or fetch["chars"] < 0:
        p.append(f"fetch.chars måste vara ett icke-negativt heltal, fick {fetch['chars']!r}")
    if not isinstance(fetch["excerpt"], str):
        p.append("fetch.excerpt måste vara en sträng")
    elif len(fetch["excerpt"]) > EXCERPT_MAX_CHARS:
        p.append(f"fetch.excerpt är {len(fetch['excerpt'])} tecken, högst {EXCERPT_MAX_CHARS}")
    if fetch["error"] is not None and not _is_text(fetch["error"]):
        p.append("fetch.error måste vara en icke-tom sträng eller null")
    if fetch["route"] == "none" and isinstance(fetch["chars"], int) and fetch["chars"] > 0:
        p.append("fetch.route none kan inte ha hämtad text (chars > 0)")
    return p


def _filtered_problems(filtered) -> list[str]:
    if not isinstance(filtered, dict) or set(filtered) != {"stage", "reason"}:
        return ["filtered måste ha exakt fälten stage och reason"]
    p = []
    if filtered["stage"] not in FILTER_STAGES:
        p.append(f"filtered.stage {filtered['stage']!r} är inte en av {', '.join(FILTER_STAGES)}")
    if not _is_text(filtered["reason"]):
        p.append("filtered.reason måste ange skälet")
    return p


def validate_sources(sources: list[dict]) -> None:
    """Kontrollera listan som ska bli 01_sources.json: fullständiga källor, unika `n`, inga felträffar."""
    problems = _list_problems(sources, complete=True)
    for src in sources if isinstance(sources, list) else []:
        if not isinstance(src, dict):
            continue
        if (src.get("relevance") or {}).get("role") == ROLE_MISMATCH:
            problems.append(f"n={src.get('n')}: felträff hör hemma i {FILTERED_FILE}")
        if src.get("filtered") is not None:
            problems.append(f"n={src.get('n')}: källan är märkt som bortfiltrerad")
    if problems:
        raise SourceError(problems, SOURCES_FILE)


def validate_filtered(sources: list[dict]) -> None:
    """Kontrollera listan som ska bli 01_filtered.json: varje källa har ett skäl."""
    problems = _list_problems(sources, complete=False)
    for src in sources if isinstance(sources, list) else []:
        if isinstance(src, dict) and src.get("filtered") is None:
            problems.append(f"n={src.get('n')} ({src.get('source_id')}): filtered med stage och reason saknas")
    if problems:
        raise SourceError(problems, FILTERED_FILE)


def _list_problems(sources, complete: bool) -> list[str]:
    if not isinstance(sources, list):
        return [f"källorna måste vara en lista, fick {type(sources).__name__}"]
    problems = []
    seen: dict[int, int] = {}
    for index, src in enumerate(sources):
        for problem in _source_problems(src, complete):
            n = src.get("n") if isinstance(src, dict) else None
            problems.append(f"[{index}] n={n!r}: {problem}")
        n = src.get("n") if isinstance(src, dict) else None
        if _is_int(n):
            if n in seen:
                problems.append(f"n={n} förekommer på plats {seen[n]} och {index}")
            seen[n] = index
    return problems


# ── Läsa och skriva ───────────────────────────────────────────────────────────

def write_sources(run_dir: Path, sources: list[dict]) -> Path:
    """Validera och skriv 01_sources.json (atomiskt). Returnerar sökvägen."""
    validate_sources(sources)
    return _write(Path(run_dir) / SOURCES_FILE, "clio-research/sources", sources)


def write_filtered(run_dir: Path, sources: list[dict]) -> Path:
    """Validera och skriv 01_filtered.json (atomiskt). Returnerar sökvägen."""
    validate_filtered(sources)
    return _write(Path(run_dir) / FILTERED_FILE, "clio-research/filtered", sources)


def read_sources(run_dir: Path) -> list[dict]:
    """Läs och validera 01_sources.json. Returnerar källorna sorterade som i filen."""
    sources = _read(Path(run_dir) / SOURCES_FILE, "clio-research/sources")
    validate_sources(sources)
    return sources


def read_filtered(run_dir: Path) -> list[dict]:
    """Läs och validera 01_filtered.json. En saknad fil betyder att inget filtrerats bort."""
    path = Path(run_dir) / FILTERED_FILE
    if not path.exists():
        return []
    sources = _read(path, "clio-research/filtered")
    validate_filtered(sources)
    return sources


def _write(path: Path, schema: str, sources: list[dict]) -> Path:
    payload = {"schema": schema, "version": SCHEMA_VERSION, "sources": sources}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _read(path: Path, schema: str) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Källfilen saknas: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SourceError([f"filen är inte giltig JSON: {e}"], path.name) from e
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise SourceError([f"filen saknar schema {schema!r}"], path.name)
    if payload.get("version") != SCHEMA_VERSION:
        raise SourceError([f"version {payload.get('version')!r} stöds inte (väntade {SCHEMA_VERSION})"], path.name)
    if not isinstance(payload.get("sources"), list):
        raise SourceError(["fältet sources saknas eller är inte en lista"], path.name)
    return payload["sources"]


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(_is_text(v) for v in value)
