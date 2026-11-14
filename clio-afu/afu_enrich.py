#!/usr/bin/env python3
"""
afu_enrich.py — Klassificerar afu.se-poster mot transmorf-taxonomin via Ollama
Kör från ~/19.0/clio-tools/clio-afu/

Usage:
    python3 afu_enrich.py [--model qwen2.5:3b] [--max N]

Input:  data/afu_posts.jsonl
Output: data/afu_enriched.jsonl  (resume-safe)
"""

import argparse
import json
import time
from pathlib import Path
from datetime import datetime

import requests

# ─── Konfiguration ────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/generate"
INPUT_FILE  = Path(__file__).parent / "data" / "afu_posts.jsonl"
OUTPUT_FILE = Path(__file__).parent / "data" / "afu_enriched.jsonl"

SYSTEM_PROMPT = """Du är en analytiker för UAP/UFO-forskning. Klassificera texter enligt transmorf-taxonomin.
Svara ALLTID med ett JSON-objekt och INGENTING annat — ingen inledning, ingen förklaring.

Definitioner:
- is_case_report: true om texten beskriver ett faktiskt observationstillfälle/möte med UAP/fenomen
- craft_class: Skywatcher-klass för observerat objekt (I=Tetra II=Tic-Tac III=Blob IV=Beam
  V=Manta-Ray VI=Bright-Star VII=Jellyfish VIII=Hornet IX=Egg X=Teardrop) eller "Unknown" eller null
- entity_type: Nordic | TallGray | ShortGray | LongGray | Reptilian | Mantid | Hybrid | Energy | Unknown | null
- eth_origin: 0-5
    0 = förklarat/mänskligt ursprung
    1 = troligen mänskligt, men oklart
    2 = okänt ursprung — varken bekräftat mänskligt eller icke-mänskligt
    3 = stark icke-mänsklig indikation — KRÄVER fysisk evidens ELLER radar ELLER flera oberoende vittnen
    4 = starkt icke-mänskligt med officiell korroboration (militär/myndighet erkänt)
    5 = bekräftat icke-mänskligt av officiella declassificerade dokument
- intelligence_indicator: 0-3
    0 = inga tecken på intelligens
    1 = möjlig reaktiv/avsiktlig rörelse
    2 = tydlig intelligens — syftesfullt beteende, undvikande, kommunikationsförsök
    3 = direkt kontakt eller kommunikation med vittne
- discourse_level: 1-5
    1 = fringe/spekulativt, ingen källkritik
    2 = rapporterat men ej dokumenterat
    3 = dokumenterat, utredning gjord, men ej officiellt bekräftat
    4 = officiellt erkänt/undersökt av myndighet
    5 = bekräftat/declassifierat av officiell källa
- suppression_indicator: true om texten aktivt frames bort, tonar ned eller undviker ETH-implikationer
  för ett fall som annars matchar eth>=3 — t.ex. nämner omöjlig rörelseprestanda men drar slutsatsen
  "naturlig förklaring trolig" utan evidens
- suppression_note: kort notering (max 80 tecken) om varför suppression=true, annars null
- case_date: datum för händelsen (ISO 8601 eller YYYY-MM), ej publikationsdatum, null om okänt
- location: land/region om nämnt, null annars
- summary_sv: 1 mening på svenska som sammanfattar vad texten handlar om
"""

CLASSIFY_PROMPT = """Klassificera följande text från AFU:s webbplats.

TITEL: {title}
PUBLICERAT: {date}
URL: {url}

TEXT (max 4000 tecken):
{text}

Returnera exakt detta JSON (inga extra fält):
{{
  "is_case_report": false,
  "craft_class": null,
  "entity_type": null,
  "eth_origin": 0,
  "intelligence_indicator": 0,
  "discourse_level": 1,
  "suppression_indicator": false,
  "suppression_note": null,
  "case_date": null,
  "location": null,
  "summary_sv": ""
}}"""


# ─── Ollama ───────────────────────────────────────────────────────────────────

def classify_post(post: dict, model: str) -> dict:
    prompt = CLASSIFY_PROMPT.format(
        title=post.get("title", ""),
        date=post.get("date", ""),
        url=post.get("url", ""),
        text=post.get("text", "")[:4000],
    )
    payload = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
    resp.raise_for_status()
    raw = resp.json().get("response", "{}")
    return json.loads(raw)


def load_done_urls(output_file: Path) -> set:
    done = set()
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["url"])
                except Exception:
                    pass
    return done


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Transmorf-klassificering av AFU-poster via Ollama")
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--max", type=int, default=0)
    args = parser.parse_args()

    posts = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                p = json.loads(line)
                if not p.get("error"):
                    posts.append(p)
            except Exception:
                pass

    done = load_done_urls(OUTPUT_FILE)
    todo = [p for p in posts if p.get("url") not in done]
    if args.max:
        todo = todo[:args.max]

    print(f"Totalt: {len(posts)} | Klara: {len(done)} | Kvar: {len(todo)} | Modell: {args.model}")

    errors = 0
    with open(OUTPUT_FILE, "a", encoding="utf-8") as out:
        for i, post in enumerate(todo, 1):
            label = post.get("title", post["url"])[:70]
            print(f"[{i}/{len(todo)}] {label}")
            try:
                classification = classify_post(post, args.model)
                record = {
                    "url": post["url"],
                    "title": post.get("title", ""),
                    "date": post.get("date", ""),
                    "source": "afu.se",
                    "enriched_at": datetime.utcnow().isoformat(),
                    **classification,
                }
                # Kort logg för intressanta fynd
                eth = record.get("eth_origin", 0)
                sup = record.get("suppression_indicator", False)
                if eth >= 2 or sup:
                    print(f"  ★ eth={eth} | suppress={sup} | {record.get('entity_type')} | {record.get('craft_class')}")
            except Exception as e:
                errors += 1
                print(f"  FEL: {e}")
                record = {
                    "url": post["url"],
                    "title": post.get("title", ""),
                    "error": str(e),
                    "enriched_at": datetime.utcnow().isoformat(),
                }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()

    print(f"\nKlart! {len(todo)-errors} lyckade, {errors} fel → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
