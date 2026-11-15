#!/usr/bin/env python3
"""
afu_analyze.py — Analyserar klassificerat AFU-material mot transmorf-taxonomin

Testar hypotesen: AFU undertrycker ETH-indikatorer i sina publicerade texter.

Usage:
    python3 afu_analyze.py [--min-eth 2]

Input:  data/afu_enriched.jsonl
Output: stdout + data/afu_analysis.json
"""

import argparse
import json
from collections import Counter
from pathlib import Path

INPUT_FILE = Path(__file__).parent / "data" / "afu_enriched.jsonl"


def pct(n, total):
    return f"{100*n/total:.1f}%" if total else "0%"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-eth", type=int, default=2, help="Visa fall med eth >= detta")
    args = parser.parse_args()

    records = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                if not r.get("error"):
                    records.append(r)
            except Exception:
                pass

    total = len(records)
    if not total:
        print("Inga klassificerade poster hittades.")
        return

    print(f"\n{'='*60}")
    print(f"  AFU TRANSMORF-ANALYS  ({total} poster)")
    print(f"{'='*60}")

    # Fallrapporter
    cases = [r for r in records if r.get("is_case_report")]
    print(f"\nFallrapporter (is_case_report=True): {len(cases)} / {total} ({pct(len(cases), total)})")
    non_cases = [r for r in records if not r.get("is_case_report")]
    print(f"Övriga (donation/nyheter etc.):       {len(non_cases)} / {total}")

    if not cases:
        print("\nInga fallrapporter — kör afu_enrich.py först.")
        return

    n_cases = len(cases)

    # ETH-distribution
    eth_dist = Counter(r.get("eth_origin", 0) for r in cases)
    print(f"\n── ETH-distribution (fallrapporter) ──────────────────")
    for k in range(6):
        n = eth_dist.get(k, 0)
        bar = "█" * min(n, 40)
        print(f"  eth={k}: {n:4d}  ({pct(n, n_cases)})  {bar}")

    # Suppression
    suppressed = [r for r in cases if r.get("suppression_indicator")]
    print(f"\n── Suppressionsindikator ─────────────────────────────")
    print(f"  Poster med suppression_indicator=True: {len(suppressed)} / {n_cases} ({pct(len(suppressed), n_cases)})")
    # Suppression koncentrerad till höga ETH?
    if suppressed:
        sup_eth = Counter(r.get("eth_origin", 0) for r in suppressed)
        print(f"  ETH-fördelning bland supprimerade: {dict(sup_eth)}")
        print(f"\n  Exempel (upp till 8):")
        for r in sorted(suppressed, key=lambda x: x.get("eth_origin", 0), reverse=True)[:8]:
            print(f"    [eth={r.get('eth_origin')}] {r.get('title', r['url'])[:55]}")
            if r.get("suppression_note"):
                print(f"    → {r['suppression_note']}")
            print(f"    {r['url']}")

    # Craft-klasser
    craft_dist = Counter(r.get("craft_class") for r in cases if r.get("craft_class"))
    if craft_dist:
        print(f"\n── Skywatcher-klasser ────────────────────────────────")
        for klass, count in craft_dist.most_common():
            print(f"  {klass:<20} {count:4d}  {pct(count, n_cases)}")

    # Entitetstyper
    entity_dist = Counter(r.get("entity_type") for r in cases if r.get("entity_type"))
    if entity_dist:
        print(f"\n── Entitetstyper (transmorf-taxonomi) ───────────────")
        for etype, count in entity_dist.most_common():
            print(f"  {etype:<20} {count:4d}  {pct(count, n_cases)}")

    # Intelligence indicators
    ii_dist = Counter(r.get("intelligence_indicator", 0) for r in cases)
    print(f"\n── Intelligence indicators ───────────────────────────")
    labels = {0: "Ingen indikation", 1: "Möjlig reaktiv rörelse", 2: "Tydlig intelligens", 3: "Direkt kontakt"}
    for k in range(4):
        n = ii_dist.get(k, 0)
        print(f"  ii={k} ({labels[k]:<25}) {n:4d}  {pct(n, n_cases)}")

    # Discourse level
    dl_dist = Counter(r.get("discourse_level", 1) for r in cases)
    print(f"\n── Discourse level ───────────────────────────────────")
    dl_labels = {1: "Fringe", 2: "Rapporterat", 3: "Dokumenterat", 4: "Officiellt erkänt", 5: "Bekräftat"}
    for k in range(1, 6):
        n = dl_dist.get(k, 0)
        print(f"  dl={k} ({dl_labels[k]:<22}) {n:4d}  {pct(n, n_cases)}")

    # Höga ETH-fall
    high_eth = [r for r in cases if r.get("eth_origin", 0) >= args.min_eth]
    high_eth.sort(key=lambda x: (x.get("eth_origin", 0), x.get("intelligence_indicator", 0)), reverse=True)
    print(f"\n── Fall med ETH >= {args.min_eth} ({len(high_eth)} st) ──────────────────────")
    for r in high_eth:
        sup_flag = " ⚠️SUPP" if r.get("suppression_indicator") else ""
        print(f"\n  [eth={r.get('eth_origin')} ii={r.get('intelligence_indicator',0)} dl={r.get('discourse_level',1)}]{sup_flag}")
        print(f"  {r.get('title', '')[:65]}")
        print(f"  {r['url']}")
        if r.get("entity_type"):   print(f"  Entitet: {r.get('entity_type')}")
        if r.get("craft_class"):   print(f"  Farkost: {r.get('craft_class')}")
        if r.get("case_date"):     print(f"  Datum:   {r.get('case_date')}")
        if r.get("location"):      print(f"  Plats:   {r.get('location')}")
        if r.get("summary_sv"):    print(f"  → {r.get('summary_sv')}")

    # Spara JSON
    analysis = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
        "total_posts": total,
        "case_reports": n_cases,
        "eth_distribution": {str(k): eth_dist.get(k, 0) for k in range(6)},
        "suppression_count": len(suppressed),
        "suppression_pct": round(100 * len(suppressed) / n_cases, 1) if n_cases else 0,
        "suppressed_cases": [
            {
                "url": r["url"],
                "title": r.get("title", ""),
                "eth": r.get("eth_origin"),
                "ii": r.get("intelligence_indicator"),
                "note": r.get("suppression_note"),
            }
            for r in suppressed
        ],
        "craft_classes": dict(craft_dist),
        "entity_types": dict(entity_dist),
        "high_eth_cases": [
            {
                "url": r["url"],
                "title": r.get("title", ""),
                "eth": r.get("eth_origin"),
                "ii": r.get("intelligence_indicator"),
                "entity_type": r.get("entity_type"),
                "craft_class": r.get("craft_class"),
                "suppression": r.get("suppression_indicator"),
                "summary_sv": r.get("summary_sv"),
            }
            for r in high_eth
        ],
    }
    out = Path(__file__).parent / "data" / "afu_analysis.json"
    out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"Fullständig analys sparad: {out}")


if __name__ == "__main__":
    main()
