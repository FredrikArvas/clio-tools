"""
sync_fis_from_results.py -- Bootstrappar ssf.fis.competitor från befintliga ssf.result-poster.

Ingen FIS API-åtkomst krävs. Data hämtas från Odoo (ssf.result) som i sin tur är synkad
från SSFTA. FIS-koden är join-nyckeln när FIS API:et blir tillgängligt i fas 2.

Logik:
  - Hämtar alla ssf.result med fis_code != 0, nation = SWE (eller annan --nation)
    och person_id satt
  - Härleder discipline_id via result_list_id -> ssf.result.list -> ccd_id ->
    ssf.comp.ccd -> discipline_id
  - Grupperar per (fis_code, discipline_id) och tar fis_points från det senaste resultatet
    (baserat på competition.date via competition_id på ccd)
  - Upsert till ssf.fis.competitor med nyckel (fis_code, discipline_id)
  - source = 'ssfta_derived', fis_rank lämnas tomt (0)

Körning:
    python3 sync_fis_from_results.py --db ssf [--dry-run] [--nation SWE]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

BATCH = 500


def _upsert(Model, rows: list[dict], key1: str, key2: str, dry_run: bool) -> tuple[int, int]:
    """Upsert med sammansatt nyckel (key1, key2)."""
    created = updated = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        pairs = [(r[key1], r[key2]) for r in batch]

        # Sök befintliga via key1-värden (sedan filtrera i Python på key2)
        key1_vals = list({r[key1] for r in batch})
        existing_recs = Model.search_read([[key1, "in", key1_vals]], [key1, key2, "id"])
        existing = {(r[key1], r[key2] if r[key2] else False): r["id"] for r in existing_recs}

        to_create = [r for r in batch if (r[key1], r[key2]) not in existing]
        to_update = [(existing[(r[key1], r[key2])], r) for r in batch if (r[key1], r[key2]) in existing]

        if to_create and not dry_run:
            Model.create(to_create)
        created += len(to_create)

        for odoo_id, row in to_update:
            if not dry_run:
                Model.browse(odoo_id).write(row)
        updated += len(to_update)

    return created, updated


def build_fis_competitors(env, nation: str, dry_run: bool):
    print(f"  Hämtar ssf.result för nation={nation} med fis_code ...")
    results = env["ssf.result"].search_read(
        [
            ("fis_code", "!=", 0),
            ("nation", "=", nation),
        ],
        ["person_id", "fis_code", "fis_points", "nation", "result_list_id"],
        limit=0,
    )
    print(f"  Hittade {len(results)} result-rader")
    if not results:
        return

    # ── Bygg result_list_id → discipline_id via ccd ──────────────────────────
    rl_ids = list({r["result_list_id"][0] for r in results if r["result_list_id"]})
    print(f"  Slår upp {len(rl_ids)} result-listor ...")
    rl_recs = env["ssf.result.list"].search_read(
        [("id", "in", rl_ids)], ["id", "ccd_id"]
    )
    rl_to_ccd = {r["id"]: (r["ccd_id"][0] if r["ccd_id"] else None) for r in rl_recs}

    ccd_ids = list({ccd for ccd in rl_to_ccd.values() if ccd})
    print(f"  Slår upp {len(ccd_ids)} CCD-poster ...")
    ccd_recs = env["ssf.comp.ccd"].search_read(
        [("id", "in", ccd_ids)], ["id", "discipline_id", "competition_id"]
    )
    ccd_to_disc = {r["id"]: (r["discipline_id"][0] if r["discipline_id"] else None) for r in ccd_recs}
    ccd_to_comp = {r["id"]: (r["competition_id"][0] if r["competition_id"] else None) for r in ccd_recs}

    comp_ids = list({c for c in ccd_to_comp.values() if c})
    print(f"  Slår upp {len(comp_ids)} tävlingsdatum ...")
    comp_recs = env["ssf.competition"].search_read(
        [("id", "in", comp_ids)], ["id", "date"]
    )
    comp_to_date = {r["id"]: r["date"] for r in comp_recs}

    # ── Härledd RL → (discipline_id, comp_date) ──────────────────────────────
    rl_to_disc = {}
    rl_to_date = {}
    for rl_id, ccd_id in rl_to_ccd.items():
        if not ccd_id:
            continue
        rl_to_disc[rl_id] = ccd_to_disc.get(ccd_id)
        comp_id = ccd_to_comp.get(ccd_id)
        rl_to_date[rl_id] = comp_to_date.get(comp_id) if comp_id else None

    # ── Gruppera per (fis_code, discipline_id) ────────────────────────────────
    # best = {(fis_code, disc_id): {"fis_points": float, "person_id": int, "nation": str, "date": str}}
    best: dict[tuple, dict] = {}
    skipped = 0

    for r in results:
        fis_code = str(r["fis_code"]) if r["fis_code"] else None
        if not fis_code:
            skipped += 1
            continue
        rl_id = r["result_list_id"][0] if r["result_list_id"] else None
        disc_id = rl_to_disc.get(rl_id) if rl_id else None
        date_str = rl_to_date.get(rl_id) if rl_id else None

        key = (fis_code, disc_id)
        try:
            pts = float(r["fis_points"]) if r["fis_points"] else 0.0
        except (ValueError, TypeError):
            pts = 0.0

        if key not in best or (date_str and date_str > (best[key]["date"] or "")):
            entry = {
                "fis_code": fis_code,
                "discipline_id": disc_id,
                "nation": r["nation"] or nation,
                "fis_points": pts,
                "date": date_str,
            }
            if r["person_id"]:
                entry["person_id"] = r["person_id"][0]
            best[key] = entry

    print(f"  Unika (fis_code, disciplin)-kombinationer: {len(best)}  (hoppade {skipped})")

    rows = []
    for data in best.values():
        row = {
            "fis_code": data["fis_code"],
            "person_id": data["person_id"],
            "nation": data["nation"],
            "fis_points": data["fis_points"],
            "source": "ssfta_derived",
        }
        if data["discipline_id"]:
            row["discipline_id"] = data["discipline_id"]
        if data["date"]:
            row["list_date"] = data["date"]
        rows.append(row)

    print(f"  Upsert {len(rows)} poster till ssf.fis.competitor ...")
    c, u = _upsert(env["ssf.fis.competitor"], rows, "fis_code", "discipline_id", dry_run)
    print(f"  Resultat: {c} skapade, {u} uppdaterade")


def main():
    parser = argparse.ArgumentParser(description="Bootstrap ssf.fis.competitor fran ssf.result")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None)
    parser.add_argument("--nation", default="SWE", help="Filtrera pa nation (default: SWE)")
    args = parser.parse_args()

    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"{mode}Bootstrap FIS-akare fran ssf.result -> ssf.fis.competitor ({env.db})")
    print(f"  Nation: {args.nation}")

    build_fis_competitors(env, args.nation, args.dry_run)

    print("Klar.")


if __name__ == "__main__":
    main()
