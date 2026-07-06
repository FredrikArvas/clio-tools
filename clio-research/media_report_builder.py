"""media_report_builder.py — Medieanalysrapport: volym, ton, aktörer och tematisk inramning."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

MODEL_SONNET = "claude-sonnet-4-6"
MAX_TOKENS_PER_SECTION = 600

logger = logging.getLogger(__name__)

_SECTION_PROMPTS = {
    "executive_summary": (
        "Skriv en sammanfattning (3–5 stycken) av hur nyhetsmedier i de inkluderade "
        "länderna rapporterat om UAP/UFO under studieperioden. Lyft fram de viktigaste "
        "fynden om volym, ton och tematisk inramning. Deskriptivt språk — inga kausala påståenden."
    ),
    "volume_analysis": (
        "Analysera rapporteringsvolymen över tid. Identifiera toppar, trender och "
        "skillnader mellan länderna. Koppla till de tidsmarkörer som gav störst utslag. "
        "Notera om GDELT-täckning troligtvis underskattar svenska medier."
    ),
    "tone_analysis": (
        "Analysera tonfördelningen per land. Jämför om medierna i de olika länderna "
        "skiljer sig i ton. Koppla till ländernas institutionella kontext "
        "(t.ex. AARO i USA, GEIPAN i Frankrike, avsaknad av organ i Sverige)."
    ),
    "thematic_framing": (
        "Analysera tematisk inramning. Hur vanlig är nationell_säkerhet-ram kontra "
        "vetenskap_astronomi eller folklig_kultur? Skiljer sig inramningen mellan länder?"
    ),
    "actor_citation": (
        "Analysera vilka aktörskategorier som citeras. Hur skiljer sig detta mellan "
        "länder? Är militär/myndighetskällor mer framträdande i USA vs. Sverige? "
        "Koppla till reaktiv/proaktiv-ratio."
    ),
    "white_spots": (
        "Identifiera vita fläckar: Saknas viktiga utlopp eller tidsperioder i materialet? "
        "Notera att GDELT ger titlar utan artikeltext, och att vigil_ufo är det primära "
        "källmaterialet för djupare kodning. Vilka slutsatser bör dras med försiktighet?"
    ),
}


def build(protocol: dict, coded_articles: list[dict], run_id: str, done_dir: Path) -> Path:
    """Bygg medieanalysrapport. Returnerar sökväg till .md-filen."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    stats = _compute_stats(coded_articles)
    narrative = _generate_narrative(client, protocol, stats)

    report_md = _format_report(protocol, coded_articles, stats, narrative, run_id)
    out_path = done_dir / f"{run_id}.md"
    out_path.write_text(report_md, encoding="utf-8")
    logger.info("[media_report_builder] Rapport sparad: %s", out_path)

    try:
        import pdf_builder
        pdf_builder.build_pdf(out_path)
    except Exception as e:
        logger.warning("[media_report_builder] PDF-generering misslyckades: %s", e)

    return out_path


def _compute_stats(articles: list[dict]) -> dict:
    volume: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    tone_by_country: dict[str, Counter] = defaultdict(Counter)
    actors: Counter = Counter()
    frame_by_country: dict[str, Counter] = defaultdict(Counter)
    atype_by_country: dict[str, Counter] = defaultdict(Counter)
    marker_hits: Counter = Counter()
    outlet_coverage: Counter = Counter()
    source_coverage: Counter = Counter()

    for a in articles:
        country = a.get("country") or "?"
        c = a.get("coding") or {}
        quarter = _to_quarter(a.get("date") or "")

        volume[quarter][country] += 1
        tone_by_country[country][c.get("tone", "oklar")] += 1
        for actor in c.get("cited_actors") or []:
            actors[actor] += 1
        frame_by_country[country][c.get("thematic_frame", "okategoriserad")] += 1
        atype_by_country[country][c.get("article_type", "oklar")] += 1
        outlet_coverage[a.get("outlet") or "?"] += 1
        source_coverage[a.get("source") or "?"] += 1
        if marker := c.get("temporal_marker_match"):
            marker_hits[marker] += 1

    countries = sorted({a.get("country") or "?" for a in articles})

    return {
        "total_articles": len(articles),
        "countries": countries,
        "volume_by_quarter": {q: dict(v) for q, v in sorted(volume.items())},
        "tone_by_country": {c: dict(t) for c, t in tone_by_country.items()},
        "actors_top20": dict(actors.most_common(20)),
        "frame_by_country": {c: dict(f) for c, f in frame_by_country.items()},
        "atype_by_country": {c: dict(t) for c, t in atype_by_country.items()},
        "marker_hits": dict(marker_hits.most_common()),
        "outlet_coverage": dict(outlet_coverage.most_common()),
        "source_coverage": dict(source_coverage),
    }


def _generate_narrative(client, protocol: dict, stats: dict) -> dict:
    question = protocol["question"]["natural_language"]
    stats_text = json.dumps(stats, ensure_ascii=False, indent=2)[:3000]
    sections = {}

    for key, prompt in _SECTION_PROMPTS.items():
        try:
            msg = client.messages.create(
                model=MODEL_SONNET,
                max_tokens=MAX_TOKENS_PER_SECTION,
                messages=[{
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        f"Frågeställning: {question}\n\n"
                        f"Statistik:\n{stats_text}"
                    ),
                }],
            )
            sections[key] = msg.content[0].text
        except Exception as e:
            logger.warning("[media_report_builder] Sektion %s misslyckades: %s", key, e)
            sections[key] = f"[Ej genererad: {e}]"

    return sections


def _format_report(
    protocol: dict,
    articles: list[dict],
    stats: dict,
    narrative: dict,
    run_id: str,
) -> str:
    date_str = datetime.now().strftime("%Y-%m-%d")
    question = protocol["question"]["natural_language"]
    countries = ", ".join(stats["countries"])

    header = (
        f"# Medierapport: {protocol.get('title', question)}\n\n"
        f"**Protocol ID:** {protocol['protocol_id']}  \n"
        f"**Run ID:** {run_id}  \n"
        f"**Datum:** {date_str}  \n"
        f"**Artiklar analyserade:** {stats['total_articles']}  \n"
        f"**Länder:** {countries}  \n"
        f"**Datakällor:** {', '.join(f'{k} ({v})' for k, v in stats['source_coverage'].items())}  \n\n"
        "---\n\n"
    )

    section_titles = {
        "executive_summary": "## Sammanfattning",
        "volume_analysis": "## 1. Rapporteringsvolym över tid",
        "tone_analysis": "## 2. Tonanalys per land",
        "thematic_framing": "## 3. Tematisk inramning",
        "actor_citation": "## 4. Citerade aktörskategorier",
        "white_spots": "## 5. Metodnoter och vita fläckar",
    }
    body = "".join(
        f"{title}\n\n{narrative.get(key, '')}\n\n---\n\n"
        for key, title in section_titles.items()
    )

    tables = _format_stat_tables(stats)

    copyright = (
        f"\n\n---\n\n"
        f"*© {date_str[:4]} Arvas International AB. "
        "Rapporten är framtagen med AI-stöd (clio-research, media_research-spår) "
        "och är avsedd för internt bruk. "
        "Rapporten får ej vidaredistribueras utan skriftligt tillstånd.*\n"
    )

    return header + body + tables + copyright


def _format_stat_tables(stats: dict) -> str:
    out = "## 6. Statistikbilagor\n\n"

    out += "### Ton per land\n\n"
    out += "| Land | Neutral/faktabaserad | Skeptisk | Sensationalistisk | Oklar |\n"
    out += "|------|----------------------|----------|-------------------|-------|\n"
    for country in stats["countries"]:
        t = stats["tone_by_country"].get(country, {})
        out += (
            f"| {country} | {t.get('neutral_faktabaserad', 0)} | "
            f"{t.get('skeptisk', 0)} | {t.get('sensationalistisk', 0)} | "
            f"{t.get('oklar', 0)} |\n"
        )
    out += "\n"

    out += "### Aktörscitationer (topp 10)\n\n"
    for actor, count in list(stats["actors_top20"].items())[:10]:
        out += f"- {actor}: {count}\n"
    out += "\n"

    out += "### Reaktiv/proaktiv per land\n\n"
    for country in stats["countries"]:
        t = stats["atype_by_country"].get(country, {})
        reaktiv = t.get("reaktiv", 0)
        proaktiv = t.get("proaktiv", 0)
        total = reaktiv + proaktiv
        ratio = f"{reaktiv}/{proaktiv}" if total else "–"
        out += f"- {country}: reaktiv/proaktiv = {ratio}\n"
    out += "\n"

    out += "### Källtäckning per outlet\n\n"
    for outlet, count in stats["outlet_coverage"].items():
        out += f"- {outlet}: {count} artiklar\n"
    out += "\n"

    out += "### Tidsmarkörpeaks\n\n"
    if stats["marker_hits"]:
        for marker, count in stats["marker_hits"].items():
            out += f"- {marker}: {count} artiklar inom ±30 dagar\n"
    else:
        out += "_Inga tidsmarkörträffar identifierade._\n"
    out += "\n"

    return out


def _to_quarter(date_str: str) -> str:
    if not date_str or len(date_str) < 7:
        return "Okänt"
    try:
        year = int(date_str[:4])
        month = int(date_str[5:7])
        return f"{year}-Q{(month - 1) // 3 + 1}"
    except (ValueError, IndexError):
        return "Okänt"
