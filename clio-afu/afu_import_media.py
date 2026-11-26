#!/usr/bin/env python3
"""
afu_import_media.py — Importerar AFU-poster → clio.media.article i uap-databasen.
Lägger även till afu.se RSS som clio.vigil.source för framtida bevakning.

Prioriterar afu_posts_full.jsonl (Playwright, med fulltext + fillänkar).
Faller tillbaka på afu_posts.jsonl om full-filen saknas.

Kör från ~/19.0/clio-tools/clio-afu/
Usage:
    python3 afu_import_media.py [--dry-run] [--max N]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import xmlrpc.client

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("VIGIL_ODOO_URL", "http://localhost:8069")
DB   = os.getenv("VIGIL_ODOO_DB", "uap")
USER = os.getenv("VIGIL_ODOO_USER", "")
PWD  = os.getenv("VIGIL_ODOO_PASSWORD", "")

FULL_FILE  = Path(__file__).parent / "data" / "afu_posts_full.jsonl"
BASIC_FILE = Path(__file__).parent / "data" / "afu_posts.jsonl"


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


def _build_body(post: dict) -> str:
    """Bygg body-text: brödtext + fillänkar som appendix."""
    text = post.get("text") or ""
    file_links = post.get("file_links") or []
    if not file_links:
        return text
    lines = [text, "", "--- Bifogade filer ---"]
    for fl in file_links:
        label = fl.get("label") or fl.get("url", "")
        ext   = fl.get("ext", "").upper()
        url   = fl.get("url", "")
        lines.append(f"[{ext}] {label}: {url}")
    return "\n".join(lines).strip()


def load_posts() -> tuple[list[dict], str]:
    input_file = FULL_FILE if FULL_FILE.exists() else BASIC_FILE
    posts = []
    with open(input_file, encoding="utf-8") as f:
        for line in f:
            try:
                p = json.loads(line)
                if not p.get("error") and p.get("url"):
                    posts.append(p)
            except Exception:
                pass
    return posts, input_file.name


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
        body  = _build_body(p)
        has_files = bool(p.get("file_links"))

        vals = {
            "url":          url,
            "title":        title,
            "source":       "afu.se",
            "media_type":   "article",
            "published":    _dt(p.get("date")),
            "first_seen":   _dt(p.get("scraped_at")) or _now(),
            "data_source":  "vigil_ufo",
            "body":         body,
            "body_snippet": body[:500] if body else False,
        }

        if dry_run:
            file_note = f" [{len(p.get('file_links',[]))} filer]" if has_files else ""
            print(f"  [DRY] {i}/{len(posts)} {title[:55]}{file_note}")
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
            if has_files:
                print(f"  📎 [{i}] {title[:50]} — {len(p['file_links'])} fil(er)")
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

    posts, source = load_posts()
    if not posts:
        sys.exit(f"FEL: varken {FULL_FILE.name} eller {BASIC_FILE.name} hittades")

    if args.max:
        posts = posts[:args.max]
    print(f"Läser {len(posts)} poster från {source}")
    has_fulltext = sum(1 for p in posts if p.get("text"))
    has_files    = sum(1 for p in posts if p.get("file_links"))
    print(f"  Poster med fulltext: {has_fulltext} | Med fillänkar: {has_files}")

    print(f"Ansluter till Odoo: {URL} db={DB} user={USER}")
    kw = odoo_connect()
    print("Ansluten!")

    if not args.dry_run:
        print("Lägger till vigil.source...")
        ensure_vigil_source(kw)

    print(f"Importerar {'(dry-run) ' if args.dry_run else ''}{len(posts)} artiklar...")
    created, updated, errors = import_posts(kw, posts, dry_run=args.dry_run)

    print(f"\nKlart! Skapade: {created} | Uppdaterade: {updated} | Fel: {errors}")


if __name__ == "__main__":
    main()
