#!/usr/bin/env python3
"""
afu_import_media.py — Importerar afu_posts.jsonl → clio.media.article i uap-databasen.
Lägger även till afu.se RSS som clio.vigil.source för framtida bevakning.

Kör från ~/19.0/clio-tools/clio-afu/
Usage:
    python3 afu_import_media.py [--dry-run] [--max N]
"""

import argparse
import json
import os
import sys
import xmlrpc.client
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("VIGIL_ODOO_URL", "http://localhost:8069")
DB   = os.getenv("VIGIL_ODOO_DB", "uap")
USER = os.getenv("VIGIL_ODOO_USER", "")
PWD  = os.getenv("VIGIL_ODOO_PASSWORD", "")

INPUT_FILE = Path(__file__).parent / "data" / "afu_posts.jsonl"


def odoo_connect():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = common.authenticate(DB, USER, PWD, {})
    if not uid:
        sys.exit("Odoo-autentisering misslyckades")
    M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    def kw(model, method, args, kwargs=None):
        return M.execute_kw(DB, uid, PWD, model, method, args, kwargs or {})
    return kw


def _dt(s: str):
    if not s:
        return False
    return str(s)[:19].replace("T", " ")


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def load_posts() -> list[dict]:
    posts = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                p = json.loads(line)
                if not p.get("error") and p.get("url"):
                    posts.append(p)
            except Exception:
                pass
    return posts


def ensure_vigil_source(kw):
    existing = kw("clio.vigil.source", "search_read",
                  [[["domain", "=", "ufo"], ["name", "=", "AFU — Archives for the Unexplained"]]],
                  {"fields": ["id"], "limit": 1})
    if existing:
        print(f"  vigil.source: finns redan (id={existing[0]['id']})")
        return
    kw("clio.vigil.source", "create", [{
        "name":                    "AFU — Archives for the Unexplained",
        "domain":                  "ufo",
        "source_type":             "rss",
        "url":                     "https://www.afu.se/feed/",
        "maturity":                "etablerad",
        "weight":                  1.5,
        "active":                  True,
        "language":                "en",
        "notes":                   "AFU:s WordPress-blogg. Tillagd 2026-09-26 via afu_import_media.py.",
        "archive_enabled":         False,
        "auth_env":                "",
        "transcription_threshold": 0.0,
    }])
    print("  vigil.source: afu.se skapad")


def import_posts(kw, posts: list[dict], dry_run: bool = False) -> tuple[int, int, int]:
    created = updated = errors = 0

    for i, p in enumerate(posts, 1):
        url   = p["url"]
        title = (p.get("title") or "")[:500]
        text  = p.get("text", "")
        vals  = {
            "url":          url,
            "title":        title,
            "source":       "afu.se",
            "media_type":   "article",
            "published":    _dt(p.get("date")),
            "first_seen":   _dt(p.get("scraped_at")) or _now(),
            "data_source":  "vigil_ufo",
            "body":         text,
            "body_snippet": text[:500] if text else False,
        }

        if dry_run:
            print(f"  [DRY] {i}/{len(posts)} {title[:60]}")
            created += 1
            continue

        try:
            existing = kw("clio.media.article", "search_read",
                          [[["url", "=", url]]], {"fields": ["id"], "limit": 1})
            if existing:
                kw("clio.media.article", "write", [[existing[0]["id"]], vals])
                updated += 1
            else:
                kw("clio.media.article", "create", [vals])
                created += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(posts)}] +{created} ny, ~{updated} upd")
        except Exception as e:
            errors += 1
            print(f"  FEL [{i}] {url[:60]}: {e}")

    return created, updated, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max", type=int, default=0)
    args = parser.parse_args()

    if not INPUT_FILE.exists():
        sys.exit(f"FEL: {INPUT_FILE} saknas — kör afu_scrape.py --group posts först")

    posts = load_posts()
    if args.max:
        posts = posts[:args.max]
    print(f"Läser {len(posts)} poster från {INPUT_FILE.name}")

    print(f"Ansluter till Odoo: {URL} db={DB} user={USER}")
    kw = odoo_connect()
    print("Ansluten!")

    print("Lägger till vigil.source...")
    if not args.dry_run:
        ensure_vigil_source(kw)

    print(f"Importerar {'(dry-run) ' if args.dry_run else ''}{len(posts)} artiklar...")
    created, updated, errors = import_posts(kw, posts, dry_run=args.dry_run)

    print(f"\nKlart! Skapade: {created} | Uppdaterade: {updated} | Fel: {errors}")


if __name__ == "__main__":
    main()
