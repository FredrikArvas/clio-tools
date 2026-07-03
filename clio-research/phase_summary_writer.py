"""
phase_summary_writer.py — Sparar stegvisa .md-filer per fas för revision trail.
Anropas från main.py om output.phase_summaries = true i protokollet.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def write(run_id: str, phase_num: int, sources: list[dict],
          protocol: dict, done_dir: Path,
          relevant_sources: list[dict] | None = None) -> None:
    """Skriv fassammanfattning till done/<run_id>_<fas>.md."""
    writers = {
        1: _write_scoping,
        2: _write_raw_sources,
        3: _write_raw_sources,
        4: _write_adversarial,
        6: _write_credibility,
        65: _write_filtered,   # fas 6.5 -- kallas med phase_num=65
    }
    fn = writers.get(phase_num)
    if not fn:
        return

    if phase_num == 65:
        path = done_dir / f"{run_id}_05_filtered.md"
        fn(path, sources, relevant_sources or [], protocol)
    elif phase_num in (2, 3):
        path = done_dir / f"{run_id}_02_raw_sources.md"
        fn(path, sources, protocol, phase_num)
    else:
        labels = {1: "01_scoping", 4: "03_adversarial", 6: "04_credibility"}
        path = done_dir / f"{run_id}_{labels[phase_num]}.md"
        fn(path, sources, protocol)

    logger.info("[phase_summary] Sparade %s", path.name)


def _write_scoping(path: Path, sources: list[dict], protocol: dict) -> None:
    q = protocol.get("question", {})
    kw = q.get("keywords_primary", {})
    kw_adj = q.get("keywords_adjacent", {})
    kw_adv = q.get("keywords_adversarial", {})
    phases = protocol.get("search_strategy", {}).get("phases", [])
    scoping_phase = next((p for p in phases if p["phase"] == 1), {})

    lines = [
        "# Fas 1 -- Scoping\n\n",
        f"**Fragestallning:** {q.get('natural_language', '')}\n\n",
        f"**Databaser fas 1:** {', '.join(scoping_phase.get('databases', []))}\n\n",
        "## Primara soktermer\n\n",
    ]
    for lang, terms in kw.items():
        lines.append(f"**{lang}:** {', '.join(terms)}\n\n")
    if kw_adj:
        lines.append("## Angransande termer\n\n")
        for lang, terms in kw_adj.items():
            lines.append(f"**{lang}:** {', '.join(terms)}\n\n")
    if kw_adv:
        lines.append("## Adversariala termer\n\n")
        for lang, terms in kw_adv.items():
            lines.append(f"**{lang}:** {', '.join(terms)}\n\n")

    scoping_sources = [s for s in sources if s.get("phase_found") == 1]
    lines.append(f"## Traffar fas 1: {len(scoping_sources)} kallor\n\n")
    for s in scoping_sources[:20]:
        lines.append(f"- **{s.get('title', '(okand titel)')}** ({s.get('year', '?')}) -- {s.get('source_db', '?')}\n")
    if len(scoping_sources) > 20:
        lines.append(f"- *...och {len(scoping_sources) - 20} till*\n")

    path.write_text("".join(lines), encoding="utf-8")


def _write_raw_sources(path: Path, sources: list[dict], protocol: dict, phase_num: int) -> None:
    lines = [
        "# Fas 2-3 -- Rakallor (uppdateras per fas)\n\n",
        f"**Totalt insamlade:** {len(sources)} kallor (fas 1-{phase_num})\n\n",
        "## Alla insamlade kallor\n\n",
        "| # | Titel | Ar | Databas | Abstract (utdrag) |\n",
        "|---|-------|----|---------|-------------------|\n",
    ]
    for i, s in enumerate(sources, 1):
        title = (s.get("title") or "okand")[:60]
        year = s.get("year", "?")
        db = s.get("source_db", "?")
        abstract = (s.get("abstract") or "")[:80].replace("\n", " ").replace("|", "/")
        lines.append(f"| {i} | {title} | {year} | {db} | {abstract} |\n")

    path.write_text("".join(lines), encoding="utf-8")


def _write_adversarial(path: Path, sources: list[dict], protocol: dict) -> None:
    adv_sources = [s for s in sources if s.get("phase_found") == 4]

    lines = [
        "# Fas 4 -- Adversariala kallor\n\n",
        f"**Antal motbevis/falsifieringsförsök:** {len(adv_sources)}\n\n",
    ]
    if not adv_sources:
        lines.append("*Inga adversariala kallor hittades i fas 4.*\n")
    else:
        lines.append("## Funna kallor\n\n")
        for s in adv_sources:
            title = s.get("title", "okand")
            year = s.get("year", "?")
            db = s.get("source_db", "?")
            abstract = (s.get("abstract") or "")[:300].replace("\n", " ")
            doi = s.get("doi", "")
            lines.append(f"### {title} ({year})\n\n")
            lines.append(f"**Databas:** {db}  \n")
            if doi:
                lines.append(f"**DOI:** {doi}  \n")
            lines.append(f"\n{abstract}\n\n")

    path.write_text("".join(lines), encoding="utf-8")


def _write_credibility(path: Path, sources: list[dict], protocol: dict) -> None:
    scored = sorted(
        [s for s in sources if "credibility_score" in s],
        key=lambda s: s.get("credibility_score", 0),
        reverse=True,
    )
    unscored = [s for s in sources if "credibility_score" not in s]

    lines = [
        "# Fas 6 -- Trovardighetspoang\n\n",
        f"**Totalt poangsatta:** {len(scored)}  \n",
        f"**Ej poangsatta:** {len(unscored)}  \n\n",
        "## Poangsatta kallor (sorterat, hogt till lagt)\n\n",
        "| Titel | Ar | Poang (max 18) | Databas |\n",
        "|-------|----|-----------------|---------|\n",
    ]
    for s in scored:
        title = (s.get("title") or "okand")[:55]
        year = s.get("year", "?")
        score = s.get("credibility_score", 0)
        db = s.get("source_db", "?")
        lines.append(f"| {title} | {year} | {score} | {db} |\n")

    path.write_text("".join(lines), encoding="utf-8")


def _write_filtered(path: Path, all_sources: list[dict],
                    relevant_sources: list[dict], protocol: dict) -> None:
    relevant_ids = {id(s) for s in relevant_sources}
    filtered_out = [s for s in all_sources if id(s) not in relevant_ids]

    no_abstract = [s for s in filtered_out
                   if not s.get("abstract") or len(str(s.get("abstract", ""))) < 50]
    low_sim = [s for s in filtered_out if s not in no_abstract]

    lines = [
        "# Fas 6.5 -- Relevansfiltret\n\n",
        f"**Totalt in:** {len(all_sources)}  \n",
        f"**Passerade filtret:** {len(relevant_sources)}  \n",
        f"**Bortfiltrerade:** {len(filtered_out)}  \n",
        f"  -- varav utan abstract: {len(no_abstract)}  \n",
        f"  -- varav lag similaritetsscore: {len(low_sim)}  \n\n",
        "## Passerade (topp 30)\n\n",
        "| Titel | Ar | Relevansscore | Trovardighet |\n",
        "|-------|----|--------------|--------------|\n",
    ]
    for s in relevant_sources[:30]:
        title = (s.get("title") or "okand")[:55]
        year = s.get("year", "?")
        rel = s.get("relevance_score", 0)
        cred = s.get("credibility_score", "?")
        lines.append(f"| {title} | {year} | {rel:.3f} | {cred} |\n")

    lines.append("\n## Bortfiltrerade -- lag similaritet (topp 30)\n\n")
    lines.append("| Titel | Ar | Relevansscore | Orsak |\n")
    lines.append("|-------|----|--------------|---------|\n")
    for s in sorted(low_sim, key=lambda s: s.get("relevance_score", 0), reverse=True)[:30]:
        title = (s.get("title") or "okand")[:55]
        year = s.get("year", "?")
        rel = s.get("relevance_score", 0)
        lines.append(f"| {title} | {year} | {rel:.3f} | similaritet < 0.15 |\n")

    lines.append("\n## Bortfiltrerade -- inget abstract\n\n")
    for s in no_abstract[:20]:
        title = (s.get("title") or "okand")[:70]
        year = s.get("year", "?")
        lines.append(f"- {title} ({year})\n")

    path.write_text("".join(lines), encoding="utf-8")
