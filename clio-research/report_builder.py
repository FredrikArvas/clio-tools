"""report_builder.py — Narrativ rapport via Claude API (Sonnet). Läser promptar från prompts.yaml."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

import yaml

logger = logging.getLogger(__name__)

PROMPTS_PATH = Path(__file__).parent / "config" / "prompts.yaml"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192


def build(protocol: dict, sources: list[dict], run_id: str, done_dir: Path) -> Path:
    """
    Bygg narrativ rapport och spara i done/[run_id].md.
    Returnerar sökväg till rapporten.
    """
    import anthropic

    prompts = _load_prompts()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    context = _build_context(protocol, sources)
    sections = {}

    section_keys = [
        "question_summary", "core_claim", "evidence_clusters",
        "weak_links", "adversarial_landscape", "white_spots",
        "epistemological_assessment",
    ]

    for key in section_keys:
        prompt_text = prompts.get("sections", {}).get(key, f"Skriv sektionen '{key}'.")
        logger.info("[report_builder] Genererar sektion: %s", key)
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS // len(section_keys),
                system=prompts.get("system", "Du är en vetenskaplig analytiker."),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"{prompt_text}\n\n"
                            f"Frågeställning: {protocol['question']['natural_language']}\n\n"
                            f"Källor och metadata:\n{context}\n\n"
                            f"Tidigare sektioner:\n{json.dumps(sections, ensure_ascii=False, indent=2)}"
                        ),
                    }
                ],
            )
            sections[key] = msg.content[0].text
        except Exception as e:
            logger.warning("[report_builder] Sektion %s misslyckades: %s", key, e)
            sections[key] = f"[Ej genererad: {e}]"

    report_md = _format_report(protocol, sources, sections, run_id)
    out_path = done_dir / f"{run_id}.md"
    out_path.write_text(report_md, encoding="utf-8")
    logger.info("[report_builder] Rapport sparad: %s", out_path)

    return out_path


def _build_context(protocol: dict, sources: list[dict]) -> str:
    """Bygg en komprimerad kontexttext av källorna för Claude."""
    lines = []
    sorted_sources = sorted(sources, key=lambda s: s.get("credibility_score", 0), reverse=True)

    for i, src in enumerate(sorted_sources[:40], 1):
        authors = ", ".join(src.get("authors", [])[:3])
        year = src.get("year", "?")
        region = src.get("region", "?")
        db = src.get("database", "?")
        score = src.get("credibility_score", "?")
        abstract = (src.get("abstract") or "")[:200]

        lines.append(
            f"[{i}] {src.get('title', 'Okänd titel')} "
            f"({authors or 'okänd'}, {year}) "
            f"Region: {region} | DB: {db} | Poäng: {score}/18\n"
            f"    {abstract}"
        )

    return "\n\n".join(lines)


def _format_report(protocol: dict, sources: list[dict], sections: dict, run_id: str) -> str:
    """Formatera slutrapporten som Markdown."""
    q = protocol["question"]
    date = datetime.now().strftime("%Y-%m-%d")
    num_sources = len(sources)
    regions = sorted(set(s.get("region") for s in sources if s.get("region")))

    header = f"""# Evidensrapport: {q['natural_language']}

**Protocol ID:** {protocol['protocol_id']}
**Run ID:** {run_id}
**Datum:** {date}
**Källor analyserade:** {num_sources}
**Regioner representerade:** {', '.join(regions) if regions else 'Ej kategoriserade'}

---

"""

    section_titles = {
        "question_summary": "## 1. Frågeställning",
        "core_claim": "## 2. Kärnanspråket",
        "evidence_clusters": "## 3. Starkaste evidenskluster",
        "weak_links": "## 4. Svagaste länkarna",
        "adversarial_landscape": "## 5. Motbevislandskapet",
        "white_spots": "## 6. Vita fläckar i forskningen",
        "epistemological_assessment": "## 7. Epistemologisk bedömning",
    }

    body = ""
    for key, title in section_titles.items():
        body += f"{title}\n\n{sections.get(key, '')}\n\n---\n\n"

    sources_section = "## 8. Källförteckning\n\n"
    sorted_sources = sorted(sources, key=lambda s: s.get("credibility_score", 0), reverse=True)
    for i, src in enumerate(sorted_sources[:50], 1):
        authors = ", ".join(src.get("authors", [])[:3]) or "Okänd"
        year = src.get("year", "?")
        region = src.get("region", "?")
        db = src.get("database", "?")
        score = src.get("credibility_score", "?")
        doi = src.get("doi", "")
        doi_str = f" DOI: {doi}" if doi else ""

        sources_section += (
            f"{i}. **{src.get('title', 'Okänd titel')}**  \n"
            f"   {authors} ({year}) | Region: {region} | DB: {db} | "
            f"Poäng: {score}/18{doi_str}\n\n"
        )

    return header + body + sources_section


def _load_prompts() -> dict:
    try:
        with open(PROMPTS_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warning("Kunde inte läsa prompts.yaml: %s", e)
        return {}
