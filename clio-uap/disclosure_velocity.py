"""
disclosure_velocity.py — UAP Disclosure Velocity Analysis
==========================================================
Forskningsfråga: "Vilken region/land har högst förändringstakt på disclosure av UAP?"

Algoritm:
  A. Odoo (uapdb) — strukturerade encounters:
       - official_response (A=0..E=4) + discourse_level (1..5) per encounter
       - Dela in i perioder: pre-2000 / 2000-2009 / 2010-2019 / 2020+
       - Velocity = slope via linjär regression (OLS) på period-medelvärden
  B. Qdrant (vigil_ufo) — medialt signalvärde:
       - Semantisk sökning på "official UAP disclosure government legislation"
       - Försök mappa chunks till region via payload-fält
       - Normaliserad täthet = proxy för pågående diskurs
  C. Composite score:
       velocity_composite = Δofficial×0.45 + Δdiscourse×0.30 + media_signal×0.25

Kör: cd ~/clio-tools/clio-uap && python3 disclosure_velocity.py [--json] [--top N]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_BASE_DIR = Path(__file__).parent
_ROOT_DIR = _BASE_DIR.parent
load_dotenv(_ROOT_DIR / ".env", override=True)

import xmlrpc.client

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

ODOO_URL  = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DB   = "uapdb"
ODOO_USER = os.getenv("ODOO_USER", "")
ODOO_PWD  = os.getenv("ODOO_PASSWORD", "")

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION  = "vigil_ufo"
EMBED_MODEL = "text-embedding-3-small"

OFFICIAL_MAP = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}

PERIODS = [
    ("pre-2000",  None, 2000),
    ("2000-2009", 2000, 2010),
    ("2010-2019", 2010, 2020),
    ("2020+",     2020, None),
]

DISCLOSURE_QUERIES = [
    "official UAP disclosure government acknowledgement declassified",
    "UAP legislation congress senate hearing official",
    "military UFO UAP confirmed government investigation",
    "UAP transparency government policy official statement",
]

# ---------------------------------------------------------------------------
# Odoo-hjälpfunktioner
# ---------------------------------------------------------------------------

def odoo_connect():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PWD, {})
    if not uid:
        sys.exit("[FEL] Odoo-autentisering misslyckades mot uapdb")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models


def fetch_encounters(uid, models) -> list[dict]:
    recs = models.execute_kw(
        ODOO_DB, uid, ODOO_PWD,
        "uap.encounter", "search_read",
        [[["record_type", "=", "incident"]]],
        {"fields": [
            "encounter_id", "title_en", "country_id", "region",
            "date_observed", "discourse_level", "official_response",
            "record_type",
        ], "limit": 2000},
    )
    return recs


# ---------------------------------------------------------------------------
# Beräkningshjälpare
# ---------------------------------------------------------------------------

import re as _re
_YEAR_RE = _re.compile(r'\b(1[5-9]\d{2}|20[0-2]\d)\b')

def year_of(date_str, title: str = "") -> int | None:
    """Returnerar år från date_observed om det är historiskt (< 2025).
    Annars försöker extrahera 4-siffrigt år ur title_en som fallback."""
    if date_str and date_str is not False:
        try:
            y = datetime.fromisoformat(str(date_str)).year
            if y < 2025:
                return y
        except Exception:
            pass
    # Fallback: hitta första historiska år i titeln
    if title:
        for m in _YEAR_RE.finditer(title):
            y = int(m.group(1))
            if y < 2025:
                return y
    return None


def period_of(year: int | None) -> str | None:
    if year is None:
        return None
    for label, start, end in PERIODS:
        if (start is None or year >= start) and (end is None or year < end):
            return label
    return None


def ols_slope(xs: list[float], ys: list[float]) -> float:
    """Enkel linjär regression — returnerar slope."""
    n = len(xs)
    if n < 2:
        return 0.0
    sx, sy = sum(xs), sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    denom = n * sx2 - sx * sx
    if abs(denom) < 1e-9:
        return 0.0
    return (n * sxy - sx * sy) / denom


def safe_mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


# ---------------------------------------------------------------------------
# Del A — Historisk velocity från Odoo
# ---------------------------------------------------------------------------

def analyze_odoo(encounters: list[dict]) -> dict[str, dict]:
    """
    Returnerar per region:
      period_data: {period_label: [official_score, ...], ...}
      all_official: [official_score, ...]
      all_discourse: [discourse_score, ...]
      country_breakdown: {country_name: {count, max_official, mean_discourse}}
      key_events: [str, ...]
    """
    PERIOD_ORDER = {label: i for i, (label, *_) in enumerate(PERIODS)}

    data: dict[str, dict] = defaultdict(lambda: {
        "period_official":  defaultdict(list),
        "period_discourse": defaultdict(list),
        "all_official":     [],
        "all_discourse":    [],
        "undated":          [],
        "country_breakdown": defaultdict(lambda: {"count": 0, "official": [], "discourse": []}),
        "key_events":       [],
    })

    for enc in encounters:
        region = enc.get("region") or "unknown"
        off_raw = enc.get("official_response") or ""
        disc_raw = enc.get("discourse_level") or ""
        year = year_of(enc.get("date_observed"), enc.get("title_en") or "")
        country = enc["country_id"][1] if enc.get("country_id") else "Unknown"

        off_score  = OFFICIAL_MAP.get(off_raw, -1)
        disc_score = int(disc_raw) if disc_raw and disc_raw.isdigit() else -1

        if off_score < 0 and disc_score < 0:
            continue

        r = data[region]

        # Landsstatistik
        cb = r["country_breakdown"][country]
        cb["count"] += 1
        if off_score >= 0:
            cb["official"].append(off_score)
        if disc_score >= 0:
            cb["discourse"].append(disc_score)

        period = period_of(year)

        if off_score >= 0:
            r["all_official"].append(off_score)
            if period:
                r["period_official"][period].append(off_score)

        if disc_score >= 0:
            r["all_discourse"].append(disc_score)
            if period:
                r["period_discourse"][period].append(disc_score)
            else:
                r["undated"].append(disc_score)

        # Markera högt-officiella events som nyckelexempel
        if off_score >= 3 and enc.get("title_en"):
            title = enc["title_en"][:70]
            year_str = str(year) if year else "?"
            r["key_events"].append(f"{year_str} | {title}")

    # Beräkna velocity per region
    results = {}
    for region, r in data.items():
        period_off_means = {}
        period_disc_means = {}
        for label, *_ in PERIODS:
            offs  = r["period_official"].get(label, [])
            discs = r["period_discourse"].get(label, [])
            if offs:
                period_off_means[label]  = safe_mean(offs)
            if discs:
                period_disc_means[label] = safe_mean(discs)

        # Slope: period-index → medelvärde
        p_labels = [label for label, *_ in PERIODS]

        def slope_from_periods(means: dict) -> float:
            pairs = [(PERIOD_ORDER[l], v) for l, v in means.items() if l in PERIOD_ORDER]
            if len(pairs) < 2:
                return 0.0
            xs, ys = zip(*sorted(pairs))
            return ols_slope(list(xs), list(ys))

        off_slope  = slope_from_periods(period_off_means)
        disc_slope = slope_from_periods(period_disc_means)

        # Delta senaste vs. äldsta period med data
        all_off_periods = [(PERIOD_ORDER[l], v) for l, v in period_off_means.items()]
        delta_off = 0.0
        if len(all_off_periods) >= 2:
            sorted_p = sorted(all_off_periods)
            delta_off = sorted_p[-1][1] - sorted_p[0][1]

        all_disc_periods = [(PERIOD_ORDER[l], v) for l, v in period_disc_means.items()]
        delta_disc = 0.0
        if len(all_disc_periods) >= 2:
            sorted_p = sorted(all_disc_periods)
            delta_disc = sorted_p[-1][1] - sorted_p[0][1]

        # Nuläge (2020+)
        current_off  = period_off_means.get("2020+",  safe_mean(r["all_official"]))
        current_disc = period_disc_means.get("2020+", safe_mean(r["all_discourse"]))

        # Landsnedbrytning
        cb_summary = {}
        for cname, cdata in r["country_breakdown"].items():
            cb_summary[cname] = {
                "count":         cdata["count"],
                "max_official":  max(cdata["official"]) if cdata["official"] else 0,
                "mean_official": round(safe_mean(cdata["official"]), 2),
                "mean_discourse": round(safe_mean(cdata["discourse"]), 2),
            }

        results[region] = {
            "encounter_count":    len(r["all_official"]) + len(r["undated"]),
            "period_off_means":   {k: round(v, 2) for k, v in period_off_means.items()},
            "period_disc_means":  {k: round(v, 2) for k, v in period_disc_means.items()},
            "off_slope":          round(off_slope, 4),
            "disc_slope":         round(disc_slope, 4),
            "delta_official":     round(delta_off, 2),
            "delta_discourse":    round(delta_disc, 2),
            "current_official":   round(current_off, 2),
            "current_discourse":  round(current_disc, 2),
            "country_breakdown":  cb_summary,
            "key_events":         sorted(set(r["key_events"]))[:5],
        }

    return results


# ---------------------------------------------------------------------------
# Del B — Media-signal från Qdrant
# ---------------------------------------------------------------------------

# Landkoder → region (för payload-matching)
_REGION_KEYWORDS = {
    "europe":        ["sweden", "france", "germany", "uk", "britain", "europe", "european",
                      "norway", "denmark", "finland", "italy", "spain", "russia", "polish",
                      "dutch", "belgian", "swiss", "austrian", "portuguese", "greek"],
    "north_america": ["usa", "united states", "american", "us ", "pentagon", "congress",
                      "senate", "white house", "canada", "canadian", "mexico", "mexican",
                      "nasa", "faa", "norad"],
    "south_america": ["brazil", "brazilian", "argentina", "argentina", "peru", "peru",
                      "chile", "colombia", "venezuela"],
    "asia":          ["japan", "japanese", "china", "chinese", "india", "indian", "korea",
                      "korean", "taiwan", "philippines", "indonesia"],
    "africa":        ["africa", "african", "south africa", "nigeria", "kenya", "egypt"],
    "oceania":       ["australia", "australian", "new zealand", "pacific"],
    "middle_east":   ["israel", "iran", "iraq", "saudi", "turkey", "turkish", "uae",
                      "dubai", "jordan", "lebanon"],
}


def guess_region_from_text(text: str) -> str | None:
    t = text.lower()
    scores = {}
    for region, keywords in _REGION_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in t)
        if hits:
            scores[region] = hits
    return max(scores, key=scores.get) if scores else None


def analyze_qdrant() -> dict[str, float]:
    """
    Returnerar {region: normalized_score} baserat på semantic search.
    Score = antal unika chunk-träffar med score > 0.45.
    """
    try:
        from openai import OpenAI
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue
    except ImportError as e:
        print(f"  [VARNING] Qdrant/OpenAI import-fel: {e}")
        return {}

    openai_client = OpenAI()
    qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    media_filter = Filter(must_not=[
        FieldCondition(key="source_name", match=MatchValue(value="UAP Tracking"))
    ])

    region_hits: dict[str, set] = defaultdict(set)

    for query in DISCLOSURE_QUERIES:
        try:
            resp = openai_client.embeddings.create(input=[query], model=EMBED_MODEL)
            vector = resp.data[0].embedding
            result = qdrant.query_points(
                collection_name=COLLECTION,
                query=vector,
                query_filter=media_filter,
                limit=25,
                score_threshold=0.45,
                with_payload=True,
            )
        except Exception as e:
            print(f"  [VARNING] Qdrant-sökning misslyckades: {e}")
            continue

        for hit in result.points:
            payload = hit.payload or {}
            url   = payload.get("url", "") or ""
            title = payload.get("title", "") or ""
            text  = payload.get("text", "") or payload.get("content", "") or ""

            # Försök bestämma region
            region = None
            # 1. Explicit country i payload
            country_field = payload.get("country") or payload.get("country_name") or ""
            if country_field:
                region = guess_region_from_text(country_field)
            # 2. Titel + text
            if not region:
                region = guess_region_from_text(f"{title} {text[:300]}")
            # 3. Källa (t.ex. svensk podcast = europa)
            source = payload.get("source_name", "") or ""
            if not region and source:
                region = guess_region_from_text(source)

            if region:
                chunk_key = url or title
                region_hits[region].add(chunk_key)

    # Normalisera
    totalt = sum(len(v) for v in region_hits.values()) or 1
    return {region: len(hits) / totalt for region, hits in region_hits.items()}


# ---------------------------------------------------------------------------
# Del C — Composite score
# ---------------------------------------------------------------------------

def compute_composite(
    odoo: dict[str, dict],
    qdrant: dict[str, float],
) -> list[dict]:
    """
    Kombinerar historisk velocity (Odoo) + media-signal (Qdrant).
    Returnerar sorterad lista med composite_score per region.
    """
    all_regions = set(odoo.keys()) | set(qdrant.keys())
    all_regions.discard("unknown")

    # Normalisera Odoo-signaler till [0, 1]
    def normalize(values: list[float]) -> list[float]:
        lo, hi = min(values), max(values)
        if abs(hi - lo) < 1e-9:
            return [0.5] * len(values)
        return [(v - lo) / (hi - lo) for v in values]

    delta_offs  = [odoo.get(r, {}).get("delta_official",  0.0) for r in all_regions]
    delta_discs = [odoo.get(r, {}).get("delta_discourse", 0.0) for r in all_regions]
    curr_offs   = [odoo.get(r, {}).get("current_official", 0.0) for r in all_regions]

    norm_delta_off  = normalize(delta_offs)  if any(v != 0 for v in delta_offs)  else [0.0]*len(all_regions)
    norm_delta_disc = normalize(delta_discs) if any(v != 0 for v in delta_discs) else [0.0]*len(all_regions)
    norm_curr_off   = normalize(curr_offs)   if any(v != 0 for v in curr_offs)   else [0.0]*len(all_regions)

    results = []
    for i, region in enumerate(all_regions):
        od = odoo.get(region, {})
        media = qdrant.get(region, 0.0)

        # Vikter: förändring viktigare än nuläge; media som tiebreaker
        score = (
            norm_delta_off[i]  * 0.35 +
            norm_delta_disc[i] * 0.25 +
            norm_curr_off[i]   * 0.20 +
            media              * 0.20
        )

        results.append({
            "region":           region,
            "composite_score":  round(score, 4),
            "delta_official":   od.get("delta_official",  0.0),
            "delta_discourse":  od.get("delta_discourse", 0.0),
            "current_official": od.get("current_official", 0.0),
            "current_discourse": od.get("current_discourse", 0.0),
            "media_signal":     round(media, 4),
            "encounter_count":  od.get("encounter_count", 0),
            "period_off_means": od.get("period_off_means", {}),
            "key_events":       od.get("key_events", []),
            "country_breakdown": od.get("country_breakdown", {}),
        })

    return sorted(results, key=lambda x: x["composite_score"], reverse=True)


# ---------------------------------------------------------------------------
# Utskrift
# ---------------------------------------------------------------------------

REGION_LABELS = {
    "north_america": "North America",
    "europe":        "Europe",
    "south_america": "South America",
    "asia":          "Asia",
    "africa":        "Africa",
    "oceania":       "Oceania",
    "middle_east":   "Middle East",
    "unknown":       "Unknown",
}

OFF_LABELS = {0: "A-No resp.", 1: "B-Denial", 2: "C-Ack.", 3: "D-Invest.", 4: "E-Confirm."}


def print_report(ranked: list[dict], top: int = 10) -> None:
    print("\n" + "=" * 70)
    print("  UAP DISCLOSURE VELOCITY RANKING")
    print("  Metod: Odoo uapdb (historisk trend) + vigil_ufo (media-signal)")
    print("=" * 70)

    header = f"{'#':<3} {'Region':<16} {'Score':>6} {'ΔOff':>6} {'ΔDisc':>6} {'CurrOff':>8} {'Media':>7} {'N':>5}"
    print(f"\n{header}")
    print("-" * 70)

    for rank, r in enumerate(ranked[:top], 1):
        label = REGION_LABELS.get(r["region"], r["region"])
        curr_label = OFF_LABELS.get(round(r["current_official"]), f"{r['current_official']:.1f}")
        print(
            f"{rank:<3} {label:<16} {r['composite_score']:>6.3f}"
            f" {r['delta_official']:>+6.2f} {r['delta_discourse']:>+6.2f}"
            f" {curr_label:>8} {r['media_signal']:>7.3f} {r['encounter_count']:>5}"
        )

    print("\n  ΔOff = förändring i official_response (0=A..4=E) från äldsta till senaste period")
    print("  ΔDisc = förändring i discourse_level (1..5)")
    print("  CurrOff = nuläge official_response (2020+)")
    print("  Media = normaliserad andel Qdrant-träffar om disclosure")

    # Detaljvy per region (top 3)
    for r in ranked[:3]:
        label = REGION_LABELS.get(r["region"], r["region"])
        print(f"\n{'─'*70}")
        print(f"  {rank_of(ranked, r)}. {label}  — Score {r['composite_score']:.3f}")
        print(f"{'─'*70}")

        # Perioddata
        if r["period_off_means"]:
            print("  Official response per period:")
            for period, mean in sorted(r["period_off_means"].items(),
                                       key=lambda x: ["pre-2000","2000-2009","2010-2019","2020+"].index(x[0])
                                       if x[0] in ["pre-2000","2000-2009","2010-2019","2020+"] else 99):
                bar = "█" * int(mean * 5)
                label_off = OFF_LABELS.get(round(mean), f"{mean:.2f}")
                print(f"    {period:<12} {mean:4.2f} {bar:<20} ({label_off})")

        # Länder
        if r["country_breakdown"]:
            top_countries = sorted(
                r["country_breakdown"].items(),
                key=lambda x: x[1]["max_official"],
                reverse=True,
            )[:5]
            print("  Toppländer (max official response):")
            for cname, cd in top_countries:
                off_label = OFF_LABELS.get(cd["max_official"], str(cd["max_official"]))
                print(f"    {cname:<22} max={off_label:<12} n={cd['count']}")

        # Nyckel-events
        if r["key_events"]:
            print("  Nyckelexempel (official_response D/E):")
            for ev in r["key_events"][:3]:
                print(f"    • {ev}")


def rank_of(ranked, target) -> int:
    for i, r in enumerate(ranked, 1):
        if r["region"] == target["region"]:
            return i
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="UAP Disclosure Velocity — ranking per region"
    )
    parser.add_argument("--top",  type=int, default=7, help="Antal regioner att visa (standard: 7)")
    parser.add_argument("--json", action="store_true", help="Exportera fullständig JSON till disclosure_velocity.json")
    parser.add_argument("--no-qdrant", action="store_true", help="Hoppa över Qdrant-steget")
    args = parser.parse_args(argv)

    print("[1/3] Hämtar encounters från Odoo uapdb...")
    uid, models = odoo_connect()
    encounters = fetch_encounters(uid, models)
    print(f"  {len(encounters)} encounters laddade")

    print("\n[2/3] Beräknar historisk velocity (Odoo)...")
    odoo_result = analyze_odoo(encounters)
    for region, data in sorted(odoo_result.items()):
        label = REGION_LABELS.get(region, region)
        print(f"  {label:<18} n={data['encounter_count']:>4} "
              f"ΔOff={data['delta_official']:>+.2f} "
              f"ΔDisc={data['delta_discourse']:>+.2f}")

    qdrant_result = {}
    if not args.no_qdrant:
        print("\n[3/3] Hämtar media-signal från Qdrant...")
        qdrant_result = analyze_qdrant()
        if qdrant_result:
            for region, score in sorted(qdrant_result.items(), key=lambda x: -x[1]):
                label = REGION_LABELS.get(region, region)
                print(f"  {label:<18} media={score:.3f}")
        else:
            print("  (inga Qdrant-träffar med region-signal)")
    else:
        print("\n[3/3] Qdrant-steg hoppat över (--no-qdrant)")

    print("\nBeräknar composite score...")
    ranked = compute_composite(odoo_result, qdrant_result)

    print_report(ranked, top=args.top)

    if args.json:
        out = _BASE_DIR / "disclosure_velocity.json"
        out.write_text(
            json.dumps({"ranked": ranked, "generated": str(datetime.now().date())},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON sparad: {out}")


if __name__ == "__main__":
    main()
