"""
import_results.py
Läser results/final_results.json och skriver till clio.recruiter.article_analysis i Odoo.

Kör på servern:
  cd /home/clioadmin/19.0/clio-tools/clio-agent-job
  python3 /tmp/clio-recruit/import_results.py

Eller lokalt om clio_odoo är tillgänglig.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
RESULTS_FILE = BASE_DIR / "results" / "final_results.json"

# Lägg till sökvägar för clio_odoo
_ROOT = Path("/home/clioadmin/19.0/clio-tools")
for _p in [str(_ROOT), str(_ROOT / "clio_odoo"), str(_ROOT / "clio-agent-job")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")


def main():
    if not RESULTS_FILE.exists():
        print(f"FEL: {RESULTS_FILE} saknas")
        sys.exit(1)

    with open(RESULTS_FILE, encoding="utf-8") as f:
        results = json.load(f)

    print(f"Laddar {len(results)} poster från {RESULTS_FILE}")

    from clio_odoo import connect
    env = connect()

    from odoo_writer import write_analysis_cache, get_cached_analysis
    from analyzer import AnalysisResult

    created = skipped = failed = 0

    for i, r in enumerate(results):
        article_id = r["article_id"]
        profile_id = r["profile_id"]

        # Kolla cache-träff
        existing = get_cached_analysis(env, article_id, profile_id)
        if existing is not None:
            skipped += 1
            continue

        result = AnalysisResult(
            article_id=article_id,
            signal_type=r.get("signal_type", "ingen"),
            signal_strength=r.get("signal_strength", "svag"),
            match_score=int(r.get("match_score", 0)),
            match_reason=r.get("match_reason", ""),
            potential_roles=r.get("potential_roles", []),
            recommended_action=r.get("recommended_action", "avsta"),
            contact_hint=r.get("contact_hint", ""),
        )

        try:
            write_analysis_cache(env, article_id, profile_id, result)
            created += 1
        except Exception as exc:
            print(f"  FEL [{i}] {article_id[:12]}/profil {profile_id}: {exc}")
            failed += 1

        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(results)}] {created} skapade, {skipped} skip, {failed} fel")

    print(f"\nKLAR: {created} skapade, {skipped} redan i cache, {failed} fel")


if __name__ == "__main__":
    main()
