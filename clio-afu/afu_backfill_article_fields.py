#!/usr/bin/env python3
"""
afu_backfill_article_fields.py — Fyller AFU-klassningsfälten på clio.media.article
ur checkpointen data/afu_docs_classified.jsonl.

Behövs för dokument som klassades innan afu_classify_docs.py började skriva
fälten själv (clio_afu_archives 19.0.3.0.0). Idempotent — kan köras om.
Senaste posten per filsökväg vinner; poster med "error" hoppas över.

Kör från ~/19.0/clio-tools/clio-afu/ på servern:
    python3 afu_backfill_article_fields.py [--dry-run]
"""

import argparse
import json
import logging
import sys

from afu_classify_docs import (
    OUTPUT_FILE, _filepath_to_url, article_classification_vals, odoo_connect,
)

logger = logging.getLogger(__name__)


def load_latest_records(path) -> dict[str, dict]:
    """Senaste lyckade post per filsökväg."""
    latest: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(f"Rad {line_no}: ogiltig JSON ({e}) — hoppar över")
                continue
            if "error" in record or "filepath" not in record:
                continue
            latest[record["filepath"]] = record
    return latest


def load_article_ids(kw) -> dict[str, int]:
    rows = kw("clio.media.article", "search_read",
              [[["is_afu_document", "=", True]]], {"fields": ["id", "url"]})
    return {row["url"]: row["id"] for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--dry-run", action="store_true", help="Skriv inte till Odoo")
    args = parser.parse_args()

    records = load_latest_records(OUTPUT_FILE)
    logger.info(f"{len(records)} klassade filer i {OUTPUT_FILE.name}")

    kw = odoo_connect()
    if not kw:
        sys.exit("FEL: kunde inte ansluta till Odoo")
    article_ids = load_article_ids(kw)
    logger.info(f"{len(article_ids)} AFU-artiklar i Odoo")

    written = missing = failed = 0
    for filepath, record in records.items():
        article_id = article_ids.get(_filepath_to_url(filepath))
        if not article_id:
            missing += 1
            continue
        if args.dry_run:
            written += 1
            continue
        try:
            kw("clio.media.article", "write",
               [[article_id], article_classification_vals(record)])
            written += 1
        except Exception as e:
            logger.warning(f"{filepath}: skrivning misslyckades — {e}")
            failed += 1
        if written % 1000 == 0 and written:
            logger.info(f"  {written} skrivna …")

    logger.info(f"Klart: skrivna={written} | utan artikel={missing} | fel={failed} | dry-run={args.dry_run}")


if __name__ == "__main__":
    main()
