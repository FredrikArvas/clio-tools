"""
disclosure_wiki_compare.py — Wikipedia Disclosure Depth Analysis
=================================================================
Fråga: Vilka språkversioner av Wikipedia har djupast täckning av klassiska UAP-fall?

Metod:
  1. Wikidata-API: hämta alla språklänkar för varje fall (via Q-nummer)
  2. MediaWiki Action API per språk: byte-storlek, sektioner, refs, bilder,
     senast redigerad, antal externa länkar
  3. Depth-score = viktad summa (normaliserad 0-1 per metrik)
  4. Output: tabell per fall + aggregerat cross-case ranking

Kör: python3 disclosure_wiki_compare.py [--json] [--case Roswell] [--top N]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

CASES = [
    {"name": "Roswell",              "qid": "Q181032",   "year": 1947, "country": "US"},
    {"name": "Rendlesham Forest",    "qid": "Q2271637",  "year": 1980, "country": "GB"},
    {"name": "Varginha",             "qid": "Q3313678",  "year": 1996, "country": "BR"},
    {"name": "Phoenix Lights",       "qid": "Q129848",   "year": 1997, "country": "US"},
    {"name": "Nimitz UAP",           "qid": "Q48805044", "year": 2004, "country": "US"},
    {"name": "Belgian UFO wave",     "qid": "Q815525",   "year": 1989, "country": "BE"},
]

# Viktning for depth-score
WEIGHTS = {
    "byte_size":   0.30,
    "sections":    0.25,
    "references":  0.25,
    "images":      0.10,
    "ext_links":   0.10,
}

RATE_LIMIT_SEC = 0.35

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def fetch_json(url: str, params: dict | None = None, retries: int = 3) -> dict:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": "clio-uap/1.0 (fredrik@arvas.se) UAP research"}
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt + 1)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Max retries exceeded for {url}")


# ---------------------------------------------------------------------------
# Steg 1 — Wikidata: alla spraklankar for ett Q-nummer
# ---------------------------------------------------------------------------

SKIP_PREFIXES = (
    "commons", "species", "wikiquote", "wikibooks",
    "wikisource", "wikinews", "wikivoyage", "wikiversity",
    "wikidata", "mediawiki",
)


def get_sitelinks(qid: str) -> dict[str, str]:
    """Returnerar {lang: article_title} for alla Wikipedia-versioner."""
    data = fetch_json(
        "https://www.wikidata.org/wiki/Special:EntityData/" + qid + ".json"
    )
    entity = data["entities"][qid]
    result: dict[str, str] = {}
    for key, val in entity.get("sitelinks", {}).items():
        if not key.endswith("wiki"):
            continue
        if any(key.startswith(p) for p in SKIP_PREFIXES):
            continue
        lang = key[:-4]
        result[lang] = val["title"]
    return result


# ---------------------------------------------------------------------------
# Steg 2 — MediaWiki API: statistik for en artikel
# ---------------------------------------------------------------------------

def get_article_stats(lang: str, title: str) -> dict | None:
    base = f"https://{lang}.wikipedia.org/w/api.php"

    # Hämta parse-data
    try:
        data = fetch_json(base, {
            "action":    "parse",
            "page":      title,
            "prop":      "sections|externallinks|images|wikitext",
            "format":    "json",
            "redirects": "1",
        })
    except Exception:
        return None

    if "error" in data or "parse" not in data:
        return None

    p = data["parse"]
    wikitext = p.get("wikitext", {}).get("*", "")

    ref_count = (
        wikitext.count("<ref")
        + wikitext.lower().count("{{sfn")
        + wikitext.lower().count("{{harvnb")
        + wikitext.lower().count("{{cite")
    )

    stats: dict = {
        "byte_size":  len(wikitext.encode("utf-8")),
        "sections":   len(p.get("sections", [])),
        "references": ref_count,
        "images":     len(p.get("images", [])),
        "ext_links":  len(p.get("externallinks", [])),
    }

    # Sista redigering
    try:
        time.sleep(RATE_LIMIT_SEC)
        rev = fetch_json(base, {
            "action":  "query",
            "titles":  title,
            "prop":    "revisions",
            "rvprop":  "timestamp",
            "rvlimit": "1",
            "format":  "json",
        })
        page = next(iter(rev["query"]["pages"].values()))
        stats["last_edited"] = page["revisions"][0]["timestamp"][:10]
    except Exception:
        stats["last_edited"] = None

    return stats


# ---------------------------------------------------------------------------
# Steg 3 — Depth-score (normaliserat per fall)
# ---------------------------------------------------------------------------

def normalize_scores(rows: list[dict]) -> list[dict]:
    for metric in WEIGHTS:
        vals = [r[metric] for r in rows if r.get(metric) is not None]
        max_val = max(vals) if vals else 1
        if max_val == 0:
            max_val = 1
        for r in rows:
            r[f"norm_{metric}"] = (r.get(metric) or 0) / max_val

    for r in rows:
        r["depth_score"] = round(
            sum(WEIGHTS[m] * r.get(f"norm_{m}", 0) for m in WEIGHTS), 4
        )

    return sorted(rows, key=lambda x: x["depth_score"], reverse=True)


# ---------------------------------------------------------------------------
# Steg 4 — Analysera ett fall
# ---------------------------------------------------------------------------

def analyze_case(case: dict, top: int = 15, verbose: bool = True) -> list[dict]:
    name = case["name"]

    if verbose:
        print(f"\n{'='*65}")
        print(f"  {name} ({case['year']}, {case['country']})  [Wikidata {case['qid']}]")
        print(f"{'='*65}")

    sitelinks = get_sitelinks(case["qid"])
    if verbose:
        print(f"  Sprakversioner hittade: {len(sitelinks)}")

    rows: list[dict] = []
    for i, (lang, title) in enumerate(sitelinks.items(), 1):
        if verbose and i % 10 == 0:
            print(f"  ... {i}/{len(sitelinks)} behandlade")
        time.sleep(RATE_LIMIT_SEC)
        stats = get_article_stats(lang, title)
        if stats:
            stats.update({"lang": lang, "title": title, "case": name})
            rows.append(stats)

    rows = normalize_scores(rows)

    if verbose:
        hdr = f"  {'#':<4} {'Lang':<8} {'Score':>6}  {'Bytes':>8}  {'Sek':>4}  {'Refs':>5}  {'Bilder':>6}  {'Senast':<10}"
        print(f"\n{hdr}")
        print(f"  {'-'*70}")
        for i, s in enumerate(rows[:top], 1):
            print(
                f"  {i:<4} {s['lang']:<8} {s['depth_score']:>6.3f}  "
                f"{s['byte_size']:>8,}  {s['sections']:>4}  "
                f"{s['references']:>5}  {s['images']:>6}  "
                f"{s.get('last_edited') or '?':<10}"
            )

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json",  action="store_true")
    parser.add_argument("--case",  help="Kör bara ett fall (t.ex. Roswell)")
    parser.add_argument("--top",   type=int, default=15)
    args = parser.parse_args()

    cases = CASES
    if args.case:
        cases = [c for c in CASES if c["name"].lower() == args.case.lower()]
        if not cases:
            print(f"Okänt fall: {args.case}")
            print("Tillgängliga:", [c["name"] for c in CASES])
            return

    all_results: dict[str, list[dict]] = {}
    for case in cases:
        all_results[case["name"]] = analyze_case(
            case, top=args.top, verbose=not args.json
        )

    # Aggregat: median depth-score per sprak (minst 2 fall)
    if not args.json and len(all_results) > 1:
        print(f"\n{'='*65}")
        print("  AGGREGAT — Medel depth-score per sprak (alla fall)")
        print(f"{'='*65}")
        lang_scores: dict[str, list[float]] = {}
        for rows in all_results.values():
            for s in rows:
                lang_scores.setdefault(s["lang"], []).append(s["depth_score"])
        agg = [
            (lang, sum(v) / len(v), len(v))
            for lang, v in lang_scores.items()
            if len(v) >= 2
        ]
        agg.sort(key=lambda x: x[1], reverse=True)
        print(f"\n  {'Lang':<8}  {'Medel':>7}  {'Fall':>5}  Graf")
        print(f"  {'-'*50}")
        for lang, mean, count in agg[:20]:
            bar = "█" * max(1, int(mean * 30))
            print(f"  {lang:<8}  {mean:>7.3f}  {count:>5}  {bar}")

    if args.json:
        print(json.dumps(all_results, ensure_ascii=False, indent=2))
    else:
        out_path = Path(__file__).parent / "disclosure_wiki_results.json"
        out_path.write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n  Resultat sparat: {out_path}")


if __name__ == "__main__":
    main()
