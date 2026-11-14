"""
build_final.py
Sammanställer scan_batch_*.json + deep_results.json → results/final_results.json

Logik:
  - Djupanalys-poster (från deep_results.json) har prioritet
  - Scan-poster med score ≥ 40 som SAKNAS i djupanalys flaggas med varning
  - Alla övriga kombinationer (score < 40 eller saknas) → match_score=0, signal_type="ingen"

Profiler: 2, 3, 4
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
ANALYSIS_DIR = BASE_DIR / "analysis"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

PROFILE_IDS = [2, 3, 4]
DEEP_THRESHOLD = 40  # Score ≥ detta bör finnas i deep_results


def load_scan_results() -> dict[str, dict[str, int]]:
    """Returnerar {article_id_prefix: {p2: score, p3: score, p4: score}}"""
    scores: dict[str, dict[str, int]] = {}
    for f in sorted(ANALYSIS_DIR.glob("scan_batch_*.json")):
        with open(f, encoding="utf-8") as fh:
            batch = json.load(fh)
        for row in batch:
            aid = row["article_id"]
            scores[aid] = {
                "p2": row.get("p2", 0),
                "p3": row.get("p3", 0),
                "p4": row.get("p4", 0),
            }
    return scores


def load_deep_results() -> dict[tuple[str, int], dict]:
    """Returnerar {(article_id_prefix, profile_id): result_dict}"""
    deep_file = ANALYSIS_DIR / "deep_results.json"
    if not deep_file.exists():
        return {}
    with open(deep_file, encoding="utf-8") as f:
        data = json.load(f)
    return {(r["article_id"], r["profile_id"]): r for r in data}


def main():
    # Ladda alla article_ids från articles_dump för att täcka hela korset
    # Sök artikeldump lokalt i analysis/ eller på servern
    local_dump = ANALYSIS_DIR / "articles_dump.json"
    server_dump = Path("/tmp/articles_dump.json")
    articles_dump = local_dump if local_dump.exists() else server_dump

    if not articles_dump.exists():
        # Fallback: använd scan-resultaten
        scan = load_scan_results()
        all_article_ids = list(set(aid[:12] for aid in scan))
    else:
        with open(articles_dump, encoding="utf-8") as f:
            articles = json.load(f)
        all_article_ids = [a["article_id"] for a in articles]

    scan = load_scan_results()
    deep = load_deep_results()

    final: list[dict] = []
    missing_deep: list[tuple] = []

    for article_id in all_article_ids:
        # Sök score via prefix-matchning (scan_list har 12-tecken-prefix)
        prefix = article_id[:12]
        scan_scores = scan.get(prefix, {"p2": 0, "p3": 0, "p4": 0})

        for pid in PROFILE_IDS:
            pkey = f"p{pid}"
            score = scan_scores.get(pkey, 0)

            # Finns djupanalys?
            deep_key = (prefix, pid)
            if deep_key in deep:
                final.append(deep[deep_key])
            elif score >= DEEP_THRESHOLD:
                missing_deep.append((prefix, pid, score))
                # Lägg ändå in scan-score som placeholder (kommer ersättas av djupanalys)
                final.append({
                    "article_id": article_id,
                    "profile_id": pid,
                    "signal_type": "okänd",
                    "signal_strength": "svag",
                    "match_score": score,
                    "match_reason": f"[SAKNAR DJUPANALYS — scan_score={score}]",
                    "potential_roles": [],
                    "recommended_action": "bevaka_3man",
                    "contact_hint": "",
                })
            else:
                # Nollpost
                final.append({
                    "article_id": article_id,
                    "profile_id": pid,
                    "signal_type": "ingen",
                    "signal_strength": "svag",
                    "match_score": 0,
                    "match_reason": "",
                    "potential_roles": [],
                    "recommended_action": "avsta",
                    "contact_hint": "",
                })

    out_file = RESULTS_DIR / "final_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f"final_results.json: {len(final)} poster")
    print(f"  varav djupanalys: {len(deep)}")
    print(f"  varav nollposter: {sum(1 for r in final if r['match_score'] == 0)}")

    if missing_deep:
        print(f"\nVARNING: {len(missing_deep)} poster har score >={DEEP_THRESHOLD} men saknar djupanalys:")
        for aid, pid, sc in missing_deep[:20]:
            print(f"  {aid} profil={pid} score={sc}")


if __name__ == "__main__":
    main()
