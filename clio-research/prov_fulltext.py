"""
prov_fulltext.py
Provkör fulltextkedjan på riktigt mot källorna i spår 3:s mätning (rapport 021).

Läser `fetch_sample_021.csv` (vilka källor spår 3 prövade och hur det gick) och
`oa_status_021.csv` (DOI och OpenAlex-id per källa), hämtar metadata via
OpenAlex-connectorn, kör `fulltext_fetcher` och skriver utfallet till en egen mapp:

    <ut>/kallor/k<nn>.md     hämtade texter
    <ut>/prov_sources.json   källorna i källformatet (utan relevansbedömning)
    <ut>/resultat.csv        en rad per källa, spår 3 och spår 1 sida vid sida
    <ut>/jamforelse.md       sammanfattning

Sätter aldrig CLIO_CONTACT_EMAIL. Är den inte satt hoppas Unpaywall-steget över.

Usage:
    python clio-research/prov_fulltext.py --prov-dir "<…>\\_fulltext_prov" [--level standard]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import credibility_scorer  # noqa: E402
import fulltext_fetcher  # noqa: E402
import source_model  # noqa: E402
from connectors import openalex  # noqa: E402
from contact import contact_email  # noqa: E402

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "1.0.0"

SAMPLE_CSV = "fetch_sample_021.csv"
OA_CSV = "oa_status_021.csv"
OUT_DIR = "spar1"

log = logging.getLogger("prov_fulltext")


def load_sample(prov_dir: Path) -> list[dict]:
    """Slå ihop spår 3:s tio provkällor med DOI och OpenAlex-id."""
    with open(prov_dir / OA_CSV, encoding="utf-8", newline="") as f:
        oa = {row["nr"]: row for row in csv.DictReader(f)}
    with open(prov_dir / SAMPLE_CSV, encoding="utf-8", newline="") as f:
        sample = list(csv.DictReader(f))
    for row in sample:
        if row["nr"] not in oa:
            raise ValueError(f"Källa nr {row['nr']} finns inte i {OA_CSV}")
        row["doi"] = oa[row["nr"]]["doi"]
        row["openalex_id"] = oa[row["nr"]]["openalex_id"].rsplit("/", 1)[-1]
    return sample


def build_source(row: dict) -> dict:
    """Hämta metadata från OpenAlex och gör en källa i källformatet. Numret är rapportens."""
    work = openalex._get(f"{openalex.BASE_URL}/{row['openalex_id']}", {"select": openalex.SELECT_FIELDS})
    raw = openalex._normalize(work)
    if raw is None:
        raise ValueError(f"OpenAlex gav ingen titel för {row['openalex_id']}")
    source = source_model.from_raw_hit(raw)
    source["n"] = int(row["nr"])
    return credibility_scorer.assess(source)


def run(prov_dir: Path, level: str) -> Path:
    out = prov_dir / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    sample = load_sample(prov_dir)
    fetcher = fulltext_fetcher.FulltextFetcher(out, level=level)

    sources, rows = [], []
    for row in sample:
        source = build_source(row)
        fetcher.fetch(source)
        source_model.validate_source(source, complete=False)
        sources.append(source)
        fetch = source["fetch"]
        words = 0
        if source["text_path"]:
            text = (out / source["text_path"]).read_text(encoding="utf-8").split("\n---\n", 1)[-1]
            words = fulltext_fetcher.word_count(text)
        rows.append({
            "nr": row["nr"],
            "spar3_status": row["status"],
            "spar3_tecken": row["tecken"],
            "spar1_lasniva": source["read_level"],
            "spar1_vag": fetch["route"],
            "spar1_tecken": fetch["chars"],
            "spar1_ord": words,
            "spar1_licens": fetch["license"],
            "spar1_fel": fetch["error"] or "",
            "land": ",".join(source["country_codes"]),
            "kalltyp": source["source_type"] or "",
        })

    (out / "prov_sources.json").write_text(
        json.dumps({"schema": "clio-research/prov", "version": 1, "sources": sources}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with open(out / "resultat.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / "jamforelse.md").write_text(summary(rows, level), encoding="utf-8")
    return out


def summary(rows: list[dict], level: str) -> str:
    """Jämförelse mot spår 3 som Markdown."""
    spar3_ok = sum(1 for r in rows if r["spar3_status"] == "OK")
    fulltext = sum(1 for r in rows if r["spar1_lasniva"] == "fulltext")
    with_text = sum(1 for r in rows if r["spar1_vag"] != "none")
    lines = [
        f"# Provkörning av fulltextkedjan (spår 1), {date.today().isoformat()}",
        "",
        f"Nivå `{level}`, steg {', '.join(fulltext_fetcher.STEPS_BY_LEVEL[level])}. "
        f"Kontaktadress satt: {'ja' if contact_email() else 'nej, Unpaywall-steget prövades inte'}. "
        f"CORE-nyckel satt: {'ja' if fulltext_fetcher.os.environ.get('CORE_API_KEY') else 'nej'}.",
        "",
        f"- Spår 3 (direkthämtning av en URL per källa): {spar3_ok} av {len(rows)} gav text.",
        f"- Spår 1 (kedjan): {with_text} av {len(rows)} gav text, varav {fulltext} med läsnivå `fulltext`.",
        "",
        "| nr | Spår 3 | Tecken | Spår 1 läsnivå | Väg | Tecken | Ord | Fel |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['nr']} | {r['spar3_status']} | {r['spar3_tecken']} | {r['spar1_lasniva']} | {r['spar1_vag']} | "
            f"{r['spar1_tecken']} | {r['spar1_ord']} | {r['spar1_fel']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Provkör fulltextkedjan mot spår 3:s tio källor")
    parser.add_argument("--prov-dir", required=True, type=Path, help="Mappen _fulltext_prov")
    parser.add_argument("--level", default="standard", choices=list(fulltext_fetcher.STEPS_BY_LEVEL))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if not args.prov_dir.is_dir():
        log.error("Mappen finns inte: %s", args.prov_dir)
        return 1
    out = run(args.prov_dir, args.level)
    print((out / "jamforelse.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
