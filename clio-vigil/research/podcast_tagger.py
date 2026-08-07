#!/usr/bin/env python3
"""
podcast_tagger.py — Generisk podcast-metadata-taggare via Claude Haiku.
======================================================================

Taggar podcastavsnitt i tre faser:
  Fas 1 — Språkdetektering: lang (en / pt / other)
  Fas 2 — Full taggning:    format, topic, witness_score
  Fas 3 — Geo + bakgrund:   geo (lista), witness_background (lista)
  keep beräknas lokalt utifrån taggarna (deterministisk regel).

Återanvändbart: fungerar med valfri JSON-fil vars avsnitt har fälten
  title + description  (guid används som resume-nyckel; faller tillbaka på index).

Körning:
  python podcast_tagger.py --input metadata.json --output tagged.json
  python podcast_tagger.py --input metadata.json --output tagged.json --phase lang
  python podcast_tagger.py --input metadata.json --output tagged.json --phase full
  python podcast_tagger.py --input metadata.json --output tagged.json --phase geo
  python podcast_tagger.py --output tagged.json --stats-only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Env — ladda parent .env (ANTHROPIC_API_KEY), sedan lokal override om den finns
# ---------------------------------------------------------------------------
_here = Path(__file__).parent
load_dotenv(_here.parent.parent / ".env")       # ~/19.0/clio-tools/.env
load_dotenv(_here.parent / ".env", override=True)  # ~/19.0/clio-tools/clio-vigil/.env

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEFAULT_MODEL     = "claude-haiku-4-5-20251001"
DEFAULT_BATCH     = 20
MAX_DESC_CHARS    = 300   # tecken av description som skickas till Claude

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keep-kriterier (beräknas lokalt — deterministisk)
# ---------------------------------------------------------------------------

def compute_keep(tags: dict) -> bool:
    """Returnera True om avsnittet rekommenderas för vigil-pipelinen."""
    return (
        tags.get("lang") == "en"
        and (
            tags.get("format") == "testimony"
            or (tags.get("format") == "interview" and tags.get("witness_score", 0) >= 0.5)
        )
        and tags.get("topic") not in ("channeling_msg", "audiobook")
        and tags.get("witness_score", 0) >= 0.4
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_LANG_SYSTEM = """\
You are a language detector for podcast episodes.
For each episode provided, detect the primary spoken/written language.

Output ONLY a valid JSON array with exactly one object per episode, in the same order.
Each object must have exactly one key: "lang".
Allowed values: "en" (English), "pt" (Portuguese), "other".

Example output for 3 episodes:
[{"lang": "en"}, {"lang": "pt"}, {"lang": "other"}]

No explanation, no markdown, just the JSON array.
"""

_LANG_USER_TEMPLATE = """\
Detect the language for each of the following {n} podcast episodes.

{episodes}

Respond with a JSON array of {n} objects, one per episode.
"""

_FULL_SYSTEM = """\
You are a content classifier for a UAP/spirituality podcast archive.
For each episode, classify these three fields:

format (pick exactly one):
  "testimony"  — first-person account of contact, sighting, NDE, or anomalous experience
  "interview"  — host interviews a guest (may contain witness accounts)
  "channeling" — channeled messages from entities, guides, or higher beings
  "lecture"    — educational talk, historical overview, theoretical discussion
  "audiobook"  — narrated book or scripted story
  "other"      — does not fit above categories

topic (pick exactly one):
  "uap_sighting"       — UFO/UAP visual or radar sighting
  "contact_experience" — direct contact with non-human intelligence (ET, interdimensional)
  "nde"                — near-death experience or out-of-body experience
  "channeling_msg"     — message from guides, higher selves, or entities
  "ancient_history"    — ancient civilizations, lost technology, archaeology
  "consciousness"      — consciousness, reality, quantum mind, multidimensional self
  "spirituality"       — spiritual growth, healing, metaphysics (not UAP-specific)
  "other"              — none of the above

witness_score (0.0–1.0):
  Probability that the episode contains a real, personal first-hand witness account.
  1.0 = definitely contains a specific personal experience
  0.0 = purely theoretical, historical, or fictional

Output ONLY a valid JSON array with exactly one object per episode, in the same order.
Each object must have exactly the keys: format, topic, witness_score.

Example output for 2 episodes:
[
  {"format": "testimony", "topic": "contact_experience", "witness_score": 0.9},
  {"format": "lecture", "topic": "ancient_history", "witness_score": 0.1}
]

No explanation, no markdown, just the JSON array.
"""

_FULL_USER_TEMPLATE = """\
Classify the following {n} podcast episodes.

{episodes}

Respond with a JSON array of {n} objects.
"""

_GEO_SYSTEM = """\
You are a geographic and witness-background classifier for a UAP/spirituality podcast archive.
For each episode, extract two lists:

geo — list of locations mentioned or implied as the site of the experience/event.
  Use ONLY values from this set (include all that apply, empty list if unclear):
  "mars"           — planet Mars (as claimed location of experience or beings)
  "moon"           — Earth's Moon
  "space"          — outer space, orbit, aboard a spacecraft
  "other_planet"   — another named or unnamed planet/star system
  "north_america"  — USA, Canada, Mexico
  "south_america"  — Brazil, Argentina, Chile, etc.
  "europe"         — any European country
  "asia"           — any Asian country (incl. Middle East)
  "africa"         — any African country
  "australia"      — Australia, New Zealand, Oceania
  "antarctica"     — Antarctica or polar regions
  "ocean"          — at sea, ocean, Pacific/Atlantic etc.
  "underwater"     — underwater, submerged, USO context
  "underground"    — underground bases, tunnels, subterranean
  "unknown"        — location explicitly unknown or undisclosed

witness_background — list of the witness's/guest's background or context.
  Use ONLY values from this set (include all that apply, empty list if unclear):
  "military"           — active or veteran military service (any branch)
  "military_program"   — claims involvement in secret military programs (SSP, MILAB,
                         special access programs, black projects, MK-Ultra etc.)
  "intelligence"       — CIA, NSA, DIA, MI6, Mossad or similar agencies
  "government"         — other government employee, contractor, politician
  "aerospace"          — NASA, defense contractor, pilot, aviation
  "scientific"         — scientist, researcher, academic
  "medical"            — doctor, nurse, medical professional
  "law_enforcement"    — police, sheriff, customs, border patrol
  "civilian"           — ordinary civilian with no special background
  "experiencer"        — self-identified abductee, contactee, or repeat experiencer
  "religious"          — priest, shaman, spiritual practitioner
  "other"              — notable background not in above list

Output ONLY a valid JSON array with exactly one object per episode, in the same order.
Each object must have exactly the keys: geo (array), witness_background (array).

Example output for 2 episodes:
[
  {"geo": ["north_america", "space"], "witness_background": ["military", "military_program"]},
  {"geo": ["south_america"], "witness_background": ["civilian", "experiencer"]}
]

No explanation, no markdown, just the JSON array.
"""

_GEO_USER_TEMPLATE = """\
Classify the geographic location(s) and witness background for each of the following {n} podcast episodes.

{episodes}

Respond with a JSON array of {n} objects.
"""


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def episode_key(ep: dict, idx: int) -> str:
    """Unik nyckel per avsnitt — guid föredras, annars index."""
    return ep.get("guid") or ep.get("url") or str(idx)


def episode_snippet(ep: dict, include_lang: str | None = None) -> str:
    """Kort textrepresentation av ett avsnitt för Claude."""
    desc = (ep.get("description") or "")[:MAX_DESC_CHARS]
    lang_hint = f" [lang: {include_lang}]" if include_lang else ""
    return f'Title: {ep.get("title", "")}{lang_hint}\nDescription: {desc}'


def episode_snippet_geo(ep: dict, tags: dict) -> str:
    """Snippet för geo-fasen — inkluderar befintliga taggar som kontext."""
    desc  = (ep.get("description") or "")[:MAX_DESC_CHARS]
    topic = tags.get("topic", "")
    fmt   = tags.get("format", "")
    ctx   = f" [topic: {topic}, format: {fmt}]" if topic or fmt else ""
    return f'Title: {ep.get("title", "")}{ctx}\nDescription: {desc}'


def call_claude(system: str, user: str, model: str, retries: int = 3) -> str:
    """Anropa Claude API och returnera text-svaret. Försöker igen vid rate limit."""
    try:
        import anthropic
    except ImportError:
        log.error("anthropic saknas — kör: pip install anthropic")
        sys.exit(1)

    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY saknas i miljön")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    for attempt in range(retries):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "529" in err or "overloaded" in err.lower():
                wait = 30 * (attempt + 1)
                log.warning(f"Rate limit / overload — väntar {wait}s (försök {attempt+1}/{retries})")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Claude API misslyckades efter {retries} försök")


def parse_json_array(text: str, expected_n: int) -> list[dict]:
    """Parsa JSON-array från Claude-svar; kasta vid fel antal objekt."""
    # Hitta [ ... ] i svaret (Claude kan ibland lägga till text)
    start = text.find("[")
    end   = text.rfind("]") + 1
    if start == -1 or end == 0:
        raise ValueError(f"Inget JSON-array hittades i svaret:\n{text[:400]}")
    arr = json.loads(text[start:end])
    if len(arr) != expected_n:
        raise ValueError(
            f"Förväntade {expected_n} objekt, fick {len(arr)}.\nSvar: {text[:400]}"
        )
    return arr


# ---------------------------------------------------------------------------
# Progress-hantering (resume-säker)
# ---------------------------------------------------------------------------

def load_progress(progress_path: Path) -> dict:
    if progress_path.exists():
        with open(progress_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress_path: Path, progress: dict) -> None:
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Fas 1 — Språkdetektering
# ---------------------------------------------------------------------------

def run_lang_phase(
    episodes: list[dict],
    progress: dict,
    model: str,
    batch_size: int,
    progress_path: Path,
) -> None:
    """Tagga lang-fältet på alla avsnitt (in-place i progress)."""
    to_tag = [
        (idx, ep) for idx, ep in enumerate(episodes)
        if episode_key(ep, idx) not in progress
           or "lang" not in progress[episode_key(ep, idx)]
    ]
    if not to_tag:
        log.info("Fas 1: alla avsnitt redan språkdetekterade.")
        return

    log.info(f"Fas 1 — Språkdetektering: {len(to_tag)} avsnitt, batch {batch_size}")
    total_batches = (len(to_tag) + batch_size - 1) // batch_size

    for batch_num in range(total_batches):
        batch = to_tag[batch_num * batch_size : (batch_num + 1) * batch_size]
        snippets = "\n\n".join(
            f"Episode {i+1}:\n{episode_snippet(ep)}"
            for i, (_, ep) in enumerate(batch)
        )
        user_msg = _LANG_USER_TEMPLATE.format(n=len(batch), episodes=snippets)

        log.info(f"  Batch {batch_num+1}/{total_batches} ({len(batch)} avsnitt) …")
        try:
            raw = call_claude(_LANG_SYSTEM, user_msg, model)
            results = parse_json_array(raw, len(batch))
        except Exception as exc:
            log.error(f"  Batch {batch_num+1} misslyckades: {exc}")
            log.error(f"  Hoppar över denna batch och fortsätter.")
            continue

        for (idx, ep), res in zip(batch, results):
            key = episode_key(ep, idx)
            if key not in progress:
                progress[key] = {}
            progress[key]["lang"] = res.get("lang", "other")

        save_progress(progress_path, progress)
        log.info(f"  Batch {batch_num+1}/{total_batches} klar — progress sparad.")

        # Kort paus för att undvika rate limit
        if batch_num < total_batches - 1:
            time.sleep(0.5)

    log.info("Fas 1 — Språkdetektering klar.")


# ---------------------------------------------------------------------------
# Fas 2 — Full taggning
# ---------------------------------------------------------------------------

def run_full_phase(
    episodes: list[dict],
    progress: dict,
    model: str,
    batch_size: int,
    progress_path: Path,
) -> None:
    """Tagga format, topic, witness_score på alla avsnitt (in-place i progress)."""
    to_tag = [
        (idx, ep) for idx, ep in enumerate(episodes)
        if "format" not in progress.get(episode_key(ep, idx), {})
    ]
    if not to_tag:
        log.info("Fas 2: alla avsnitt redan fullt taggade.")
        return

    log.info(f"Fas 2 — Full taggning: {len(to_tag)} avsnitt, batch {batch_size}")
    total_batches = (len(to_tag) + batch_size - 1) // batch_size

    for batch_num in range(total_batches):
        batch = to_tag[batch_num * batch_size : (batch_num + 1) * batch_size]
        snippets = "\n\n".join(
            f"Episode {i+1}:\n{episode_snippet(ep, include_lang=progress.get(episode_key(ep, idx), {}).get('lang'))}"
            for i, (idx, ep) in enumerate(batch)
        )
        user_msg = _FULL_USER_TEMPLATE.format(n=len(batch), episodes=snippets)

        log.info(f"  Batch {batch_num+1}/{total_batches} ({len(batch)} avsnitt) …")
        try:
            raw = call_claude(_FULL_SYSTEM, user_msg, model)
            results = parse_json_array(raw, len(batch))
        except Exception as exc:
            log.error(f"  Batch {batch_num+1} misslyckades: {exc}")
            log.error(f"  Hoppar över denna batch och fortsätter.")
            continue

        for (idx, ep), res in zip(batch, results):
            key = episode_key(ep, idx)
            if key not in progress:
                progress[key] = {}
            progress[key]["format"]        = res.get("format", "other")
            progress[key]["topic"]         = res.get("topic", "other")
            progress[key]["witness_score"] = float(res.get("witness_score", 0.0))

        save_progress(progress_path, progress)
        log.info(f"  Batch {batch_num+1}/{total_batches} klar — progress sparad.")

        if batch_num < total_batches - 1:
            time.sleep(0.5)

    log.info("Fas 2 — Full taggning klar.")


# ---------------------------------------------------------------------------
# Fas 3 — Geografisk + vittnesbakgrund
# ---------------------------------------------------------------------------

_VALID_GEO = {
    "mars", "moon", "space", "other_planet",
    "north_america", "south_america", "europe", "asia",
    "africa", "australia", "antarctica", "ocean",
    "underwater", "underground", "unknown",
}
_VALID_BG = {
    "military", "military_program", "intelligence", "government",
    "aerospace", "scientific", "medical", "law_enforcement",
    "civilian", "experiencer", "religious", "other",
}


def _clean_list(values: list, valid: set) -> list:
    """Filtrera lista till tillåtna värden; returnera tom lista om inget giltigt."""
    return [v for v in (values or []) if isinstance(v, str) and v in valid]


def run_geo_phase(
    episodes: list[dict],
    progress: dict,
    model: str,
    batch_size: int,
    progress_path: Path,
) -> None:
    """Tagga geo och witness_background på alla avsnitt (in-place i progress)."""
    to_tag = [
        (idx, ep) for idx, ep in enumerate(episodes)
        if "geo" not in progress.get(episode_key(ep, idx), {})
    ]
    if not to_tag:
        log.info("Fas 3: alla avsnitt redan geo-taggade.")
        return

    log.info(f"Fas 3 — Geo + vittnesbakgrund: {len(to_tag)} avsnitt, batch {batch_size}")
    total_batches = (len(to_tag) + batch_size - 1) // batch_size

    for batch_num in range(total_batches):
        batch = to_tag[batch_num * batch_size : (batch_num + 1) * batch_size]
        snippets = "\n\n".join(
            f"Episode {i+1}:\n{episode_snippet_geo(ep, progress.get(episode_key(ep, idx), {}))}"
            for i, (idx, ep) in enumerate(batch)
        )
        user_msg = _GEO_USER_TEMPLATE.format(n=len(batch), episodes=snippets)

        log.info(f"  Batch {batch_num+1}/{total_batches} ({len(batch)} avsnitt) …")
        try:
            raw = call_claude(_GEO_SYSTEM, user_msg, model)
            results = parse_json_array(raw, len(batch))
        except Exception as exc:
            log.error(f"  Batch {batch_num+1} misslyckades: {exc}")
            log.error(f"  Hoppar över denna batch och fortsätter.")
            continue

        for (idx, ep), res in zip(batch, results):
            key = episode_key(ep, idx)
            if key not in progress:
                progress[key] = {}
            progress[key]["geo"]                = _clean_list(res.get("geo", []), _VALID_GEO)
            progress[key]["witness_background"] = _clean_list(res.get("witness_background", []), _VALID_BG)

        save_progress(progress_path, progress)
        log.info(f"  Batch {batch_num+1}/{total_batches} klar — progress sparad.")

        if batch_num < total_batches - 1:
            time.sleep(0.5)

    log.info("Fas 3 — Geo + vittnesbakgrund klar.")


# ---------------------------------------------------------------------------
# Sammanställning + statistik
# ---------------------------------------------------------------------------

def merge_and_save(episodes: list[dict], progress: dict, output_path: Path) -> list[dict]:
    """Slå ihop progress med originalepisoder och spara output-JSON."""
    result = []
    for idx, ep in enumerate(episodes):
        key  = episode_key(ep, idx)
        tags = progress.get(key, {})

        # Beräkna keep lokalt
        if all(k in tags for k in ("lang", "format", "topic", "witness_score")):
            tags["keep"] = compute_keep(tags)
        else:
            tags["keep"] = False

        merged = {**ep, "tags": tags}
        result.append(merged)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info(f"Output sparad: {output_path} ({len(result)} avsnitt)")
    return result


def print_stats(episodes_tagged: list[dict]) -> None:
    """Skriv ut sammanfattande statistik."""
    total    = len(episodes_tagged)
    has_tags = [e for e in episodes_tagged if e.get("tags")]

    if not has_tags:
        print("Inga taggade avsnitt hittades.")
        return

    # Språk
    from collections import Counter
    lang_counts = Counter(e["tags"].get("lang", "?") for e in has_tags)
    fmt_counts  = Counter(e["tags"].get("format", "?") for e in has_tags)
    topic_counts = Counter(e["tags"].get("topic", "?") for e in has_tags)
    keep_list   = [e for e in has_tags if e["tags"].get("keep")]

    print("\n" + "="*60)
    print(f"STATISTIK — {total} avsnitt totalt, {len(has_tags)} taggade")
    print("="*60)

    print("\n📍 SPRÅK:")
    for lang, count in lang_counts.most_common():
        pct = count / len(has_tags) * 100
        print(f"  {lang:8s}  {count:4d}  ({pct:.1f}%)")

    print("\n🎙️ FORMAT:")
    for fmt, count in fmt_counts.most_common():
        print(f"  {fmt:15s}  {count:4d}")

    print("\n🔭 TOPIC:")
    for topic, count in topic_counts.most_common():
        print(f"  {topic:25s}  {count:4d}")

    print(f"\n✅ KEEP=TRUE: {len(keep_list)} avsnitt")
    if keep_list:
        keep_topics = Counter(e["tags"].get("topic", "?") for e in keep_list)
        print("   Fördelning per topic:")
        for topic, count in keep_topics.most_common():
            print(f"     {topic:25s}  {count:4d}")

    # Witness score distribution
    scores = [e["tags"].get("witness_score", 0) for e in has_tags if "witness_score" in e["tags"]]
    if scores:
        avg_score = sum(scores) / len(scores)
        high = sum(1 for s in scores if s >= 0.7)
        med  = sum(1 for s in scores if 0.4 <= s < 0.7)
        low  = sum(1 for s in scores if s < 0.4)
        print(f"\n📊 WITNESS SCORE (snitt: {avg_score:.2f}):")
        print(f"   Hög (≥0.7):      {high:4d}")
        print(f"   Medium (0.4–0.7): {med:4d}")
        print(f"   Låg (<0.4):      {low:4d}")

    # Geo-fördelning (listfält — räkna varje förekomst)
    geo_tagged = [e for e in has_tags if "geo" in e["tags"]]
    if geo_tagged:
        geo_counts = Counter(
            loc for e in geo_tagged for loc in e["tags"].get("geo", [])
        )
        no_geo = sum(1 for e in geo_tagged if not e["tags"].get("geo"))
        print(f"\n🌍 GEO ({len(geo_tagged)} avsnitt taggade, {no_geo} utan geo):")
        for loc, count in geo_counts.most_common():
            print(f"  {loc:20s}  {count:4d}")

    # Vittnesbakgrund
    bg_tagged = [e for e in has_tags if "witness_background" in e["tags"]]
    if bg_tagged:
        bg_counts = Counter(
            bg for e in bg_tagged for bg in e["tags"].get("witness_background", [])
        )
        no_bg = sum(1 for e in bg_tagged if not e["tags"].get("witness_background"))
        print(f"\n🪖 VITTNESBAKGRUND ({len(bg_tagged)} avsnitt taggade, {no_bg} utan bakgrund):")
        for bg, count in bg_counts.most_common():
            print(f"  {bg:25s}  {count:4d}")

        # Militära avsnitt med keep=true
        mil_keep = [
            e for e in bg_tagged
            if e["tags"].get("keep")
            and any(b in ("military", "military_program", "intelligence")
                    for b in e["tags"].get("witness_background", []))
        ]
        if mil_keep:
            print(f"\n  ⭐ Militär/underrättelse + keep=true: {len(mil_keep)} avsnitt")
            for e in mil_keep[:10]:
                bg_str = ", ".join(e["tags"].get("witness_background", []))
                print(f"     [{bg_str}] {e.get('title', '')[:70]}")

    print("="*60 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tagga podcast-metadata med Claude Haiku."
    )
    parser.add_argument("--input",      help="Sökväg till input JSON-fil")
    parser.add_argument("--output",     required=True, help="Sökväg till output JSON-fil")
    parser.add_argument("--model",      default=DEFAULT_MODEL, help="Claude-modell")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH, help="Avsnitt per API-anrop")
    parser.add_argument(
        "--phase",
        choices=["lang", "full", "geo", "all"],
        default="all",
        help="Vilken fas att köra (default: all = fas 1 + fas 2 + fas 3)",
    )
    parser.add_argument("--stats-only", action="store_true", help="Skriv bara statistik från output-fil")
    args = parser.parse_args()

    output_path   = Path(args.output)
    progress_path = output_path.with_suffix("").with_name(output_path.stem + ".progress.json")

    # --stats-only: läs output-fil och skriv statistik
    if args.stats_only:
        if not output_path.exists():
            log.error(f"Output-fil saknas: {output_path}")
            sys.exit(1)
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        print_stats(data)
        return

    # Ladda input
    if not args.input:
        parser.error("--input krävs när --stats-only inte används")
    input_path = Path(args.input)
    if not input_path.exists():
        log.error(f"Input-fil saknas: {input_path}")
        sys.exit(1)
    with open(input_path, encoding="utf-8") as f:
        episodes: list[dict] = json.load(f)
    log.info(f"Laddade {len(episodes)} avsnitt från {input_path}")

    # Ladda progress
    progress = load_progress(progress_path)
    log.info(f"Progress: {len(progress)} avsnitt redan taggade")

    # Kör faserna
    if args.phase in ("lang", "all"):
        run_lang_phase(episodes, progress, args.model, args.batch_size, progress_path)

    if args.phase in ("full", "all"):
        run_full_phase(episodes, progress, args.model, args.batch_size, progress_path)

    if args.phase in ("geo", "all"):
        run_geo_phase(episodes, progress, args.model, args.batch_size, progress_path)

    # Slå ihop och spara
    tagged = merge_and_save(episodes, progress, output_path)
    print_stats(tagged)


if __name__ == "__main__":
    main()
