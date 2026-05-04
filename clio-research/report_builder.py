"""report_builder.py — Narrativ rapport via Claude API (Sonnet). Läser promptar från prompts.yaml."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from datetime import datetime

import yaml

logger = logging.getLogger(__name__)

PROMPTS_PATH = Path(__file__).parent / "config" / "prompts.yaml"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192
VERDICT_MAX_TOKENS = 4096


def build(protocol: dict, sources: list[dict], run_id: str, done_dir: Path) -> Path:
    """
    Bygg narrativ rapport och spara i done/[run_id].md.
    sources ska redan vara relevansfiltrerade innan detta anropas.
    Returnerar sökväg till rapporten.
    """
    import anthropic

    prompts = _load_prompts()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    context = _build_context(sources)
    question = protocol["question"]["natural_language"]
    system_prompt = prompts.get("system", "Du är en vetenskaplig analytiker.")

    if not sources:
        logger.warning("[report_builder] Inga relevanta källor — rapporten blir tunn")

    sections = _generate_sections(client, prompts, system_prompt, question, context, sources)
    verdicts = _generate_verdicts(client, system_prompt, question, sources[:30])

    report_md = _format_report(protocol, sources, sections, verdicts, run_id)
    out_path = done_dir / f"{run_id}.md"
    out_path.write_text(report_md, encoding="utf-8")
    logger.info("[report_builder] Rapport sparad: %s", out_path)

    return out_path


def _generate_sections(client, prompts: dict, system: str, question: str,
                       context: str, sources: list[dict]) -> dict:
    section_keys = [
        "question_summary", "core_claim", "evidence_clusters",
        "weak_links", "adversarial_landscape", "white_spots",
        "epistemological_assessment",
    ]
    sections = {}

    for key in section_keys:
        prompt_text = prompts.get("sections", {}).get(key, f"Skriv sektionen '{key}'.")
        logger.info("[report_builder] Genererar sektion: %s", key)
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS // len(section_keys),
                system=system,
                messages=[{
                    "role": "user",
                    "content": (
                        f"{prompt_text}\n\n"
                        f"Frågeställning: {question}\n\n"
                        f"Relevanta källor ({len(sources)} st):\n{context}\n\n"
                        f"Tidigare sektioner:\n"
                        f"{json.dumps(sections, ensure_ascii=False, indent=2)}"
                    ),
                }],
            )
            sections[key] = msg.content[0].text
        except Exception as e:
            logger.warning("[report_builder] Sektion %s misslyckades: %s", key, e)
            sections[key] = f"[Ej genererad: {e}]"

    return sections


def _generate_verdicts(client, system: str, question: str,
                       sources: list[dict]) -> list[dict]:
    """
    Be Claude klassificera varje källa som stödjer / neutral / avvisar.
    Returnerar lista av {index, title, verdict, reason}.
    """
    if not sources:
        return []

    source_list = "\n".join(
        f"[{i+1}] {s.get('title','?')} ({s.get('year','?')}, {s.get('region','?')}): "
        f"{(s.get('abstract') or '')[:150]}"
        for i, s in enumerate(sources)
    )

    prompt = (
        f"Frågeställning: {question}\n\n"
        f"För varje källa nedan, ange om den STÖDJER, är NEUTRAL/OKLAR eller AVVISAR "
        f"påståendet. Svara ENBART med ett JSON-objekt:\n"
        f"{{\"verdicts\": ["
        f"{{\"index\": 1, \"verdict\": \"stöd|neutral|avvisar\", \"reason\": \"en mening\"}}, ..."
        f"]}}\n\n"
        f"Källor:\n{source_list}"
    )

    logger.info("[report_builder] Genererar verdict-tabell för %d källor", len(sources))
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=VERDICT_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            return data.get("verdicts", [])
    except Exception as e:
        logger.warning("[report_builder] Verdict-generering misslyckades: %s", e)

    return []


def _build_context(sources: list[dict]) -> str:
    """Bygg kontexttext av de relevansfiltrerade källorna för Claude."""
    lines = []
    for i, src in enumerate(sources, 1):
        authors = ", ".join(src.get("authors", [])[:2]) or "okänd"
        year = src.get("year", "?")
        region = src.get("region", "?")
        rel = src.get("relevance_score", "?")
        cred = src.get("credibility_score", "?")
        abstract = (src.get("abstract") or "")[:250]
        lines.append(
            f"[{i}] {src.get('title', 'Okänd titel')} "
            f"({authors}, {year}) "
            f"Region: {region} | Relevans: {rel} | Trovärd: {cred}/18\n"
            f"    {abstract}"
        )
    return "\n\n".join(lines)


def _format_report(protocol: dict, sources: list[dict], sections: dict,
                   verdicts: list[dict], run_id: str) -> str:
    q = protocol["question"]
    date = datetime.now().strftime("%Y-%m-%d")
    regions = sorted(set(s.get("region") for s in sources if s.get("region")))

    # Räkna verdicts
    stod = sum(1 for v in verdicts if v.get("verdict") == "stöd")
    avvisar = sum(1 for v in verdicts if v.get("verdict") == "avvisar")
    neutral = sum(1 for v in verdicts if v.get("verdict") == "neutral")

    header = (
        f"# Evidensrapport: {q['natural_language']}\n\n"
        f"**Protocol ID:** {protocol['protocol_id']}  \n"
        f"**Run ID:** {run_id}  \n"
        f"**Datum:** {date}  \n"
        f"**Relevanta källor:** {len(sources)}  \n"
        f"**Regioner:** {', '.join(regions) if regions else 'Ej kategoriserade'}  \n"
        f"**Ställningstaganden:** 🟢 {stod} stödjer · 🟡 {neutral} neutral · 🔴 {avvisar} avvisar\n\n"
        f"---\n\n"
    )

    section_titles = {
        "question_summary":       "## 1. Frågeställning",
        "core_claim":             "## 2. Kärnanspråket",
        "evidence_clusters":      "## 3. Starkaste evidenskluster",
        "weak_links":             "## 4. Svagaste länkarna",
        "adversarial_landscape":  "## 5. Motbevislandskapet",
        "white_spots":            "## 6. Vita fläckar i forskningen",
        "epistemological_assessment": "## 7. Epistemologisk bedömning",
    }

    body = ""
    for key, title in section_titles.items():
        body += f"{title}\n\n{sections.get(key, '')}\n\n---\n\n"

    # Verdict-tabell
    verdict_section = "## 8. Källernas ställningstaganden\n\n"
    if verdicts:
        verdict_map = {v["index"]: v for v in verdicts}
        verdict_section += (
            "| # | Källa | År | Region | Ställningstagande | Motivering |\n"
            "|---|-------|----|--------|-------------------|------------|\n"
        )
        for i, src in enumerate(sources[:30], 1):
            v = verdict_map.get(i, {})
            raw_v = v.get("verdict", "?")
            emoji = {"stöd": "🟢", "neutral": "🟡", "avvisar": "🔴"}.get(raw_v, "⚪")
            title_short = (src.get("title") or "?")[:55]
            year = src.get("year", "?")
            region = src.get("region", "?")
            reason = (v.get("reason") or "").replace("|", "/")[:80]
            verdict_section += (
                f"| {i} | {title_short} | {year} | {region} | "
                f"{emoji} {raw_v} | {reason} |\n"
            )
    else:
        verdict_section += "_Verdict-klassificering ej tillgänglig._\n"
    verdict_section += "\n---\n\n"

    # Källförteckning
    sources_section = "## 9. Källförteckning\n\n"
    for i, src in enumerate(sources, 1):
        authors = ", ".join(src.get("authors", [])[:3]) or "Okänd"
        year = src.get("year", "?")
        region = src.get("region", "?")
        db = src.get("database", "?")
        cred = src.get("credibility_score", "?")
        rel = src.get("relevance_score", "?")
        doi = src.get("doi", "")
        doi_str = f" DOI: {doi}" if doi else ""
        cached = " *(cache)*" if src.get("from_cache") else ""
        sources_section += (
            f"{i}. **{src.get('title', 'Okänd titel')}**{cached}  \n"
            f"   {authors} ({year}) | {region} | {db} | "
            f"Trovärd: {cred}/18 | Relevans: {rel}{doi_str}\n\n"
        )

    return header + body + verdict_section + sources_section


def _load_prompts() -> dict:
    try:
        with open(PROMPTS_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warning("Kunde inte läsa prompts.yaml: %s", e)
        return {}
