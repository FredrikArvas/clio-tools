#!/usr/bin/env python3
"""
import_afu_documents_media.py — Indexerar nedladdade AFU-dokument → clio.media.article i uap.

Går igenom data/downloads/ på servern, hoppar över Databases/,
och skapar en clio.media.article-post per fil med länk tillbaka till files.afu.se.

Kör från ~/19.0/clio-tools/clio-afu/ på servern
Usage:
    python3 import_afu_documents_media.py [--dry-run] [--max N] [--batch-size N]
"""

import argparse
import os
import sys
import urllib.parse
import xmlrpc.client
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("VIGIL_ODOO_URL", "http://localhost:8069")
DB   = os.getenv("VIGIL_ODOO_DB", "uap")
USER = os.getenv("VIGIL_ODOO_USER", "")
PWD  = os.getenv("VIGIL_ODOO_PASSWORD", "")

DOWNLOAD_BASE = Path(__file__).parent / "data" / "downloads"
AFU_FILES_URL = "https://files.afu.se/Downloads/"

SKIP_DIRS = {"databases"}

DATA_SOURCE_MAP = {
    ("documents", "0 - ufo researchers"):  "afu_researchers",
    ("documents", "usa - aaro"):            "afu_aaro",
    ("documents", "usa - cia"):             "afu_cia",
    ("documents", "usa - congress"):        "afu_congress",
    ("documents", "usa - fbi"):             "afu_fbi",
    ("ufo-reports", "scandinavia"):         "afu_reports_scand",
    ("ufo-reports", "united kingdom"):      "afu_reports_uk",
    ("topics",):                            "afu_topics",
    ("search",):                            "afu_search",
}

FORMAT_MAP = {
    ".pdf":  "pdf",  ".PDF":  "pdf",
    ".rtf":  "rtf",  ".RTF":  "rtf",
    ".docx": "docx", ".DOCX": "docx",
    ".doc":  "doc",  ".DOC":  "doc",
    ".jpg":  "jpg",  ".JPG":  "jpg",
    ".png":  "png",  ".PNG":  "png",
    ".zip":  "zip",  ".ZIP":  "zip",
    ".txt":  "txt",  ".TXT":  "txt",
    ".mp3":  "mp3",  ".wav":  "wav",
    ".xls":  "xls",  ".xlsx": "xlsx",
}


def odoo_connect():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = common.authenticate(DB, USER, PWD, {})
    if not uid:
        sys.exit("Odoo-autentisering misslyckades")
    M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    def kw(model, method, args, kwargs=None):
        return M.execute_kw(DB, uid, PWD, model, method, args, kwargs or {})
    return kw


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def file_to_url(rel_path: str) -> str:
    parts = Path(rel_path).parts
    encoded = "/".join(urllib.parse.quote(p, safe="") for p in parts)
    return AFU_FILES_URL + encoded


def get_data_source(rel_path: str) -> str | None:
    parts = tuple(p.lower() for p in Path(rel_path).parts)
    if not parts:
        return None
    if parts[0] in SKIP_DIRS:
        return None
    key2 = (parts[0], parts[1]) if len(parts) >= 2 else None
    key1 = (parts[0],)
    if key2 and key2 in DATA_SOURCE_MAP:
        return DATA_SOURCE_MAP[key2]
    if key1 in DATA_SOURCE_MAP:
        return DATA_SOURCE_MAP[key1]
    return f"afu_{parts[0]}"


def collect_files() -> list[dict]:
    entries = []
    for root, dirs, files in os.walk(DOWNLOAD_BASE):
        root_path = Path(root)
        rel_root = root_path.relative_to(DOWNLOAD_BASE)
        top = rel_root.parts[0].lower() if rel_root.parts else ""
        if top in SKIP_DIRS:
            dirs.clear()
            continue
        for name in files:
            file_path = root_path / name
            rel = str(rel_root / name) if rel_root.parts else name
            data_source = get_data_source(rel)
            if data_source is None:
                continue
            ext = Path(name).suffix
            entries.append({
                "rel_path": rel,
                "name": name,
                "url": file_to_url(rel),
                "data_source": data_source,
                "media_type": FORMAT_MAP.get(ext, "other"),
            })
    return entries


def build_vals(entry: dict) -> dict:
    stem = Path(entry["name"]).stem
    return {
        "url":         entry["url"],
        "title":       stem[:500],
        "source":      "files.afu.se",
        "media_type":  entry["media_type"],
        "data_source": entry["data_source"],
        "first_seen":  _now(),
    }


def import_files(kw, entries: list[dict], dry_run: bool, batch_size: int) -> tuple[int, int, int]:
    print("Hämtar befintliga URL:er från Odoo...")
    existing_urls: set[str] = set()
    offset = 0
    while True:
        chunk = kw("clio.media.article", "search_read",
                   [[["source", "=", "files.afu.se"]]],
                   {"fields": ["url"], "limit": 1000, "offset": offset})
        if not chunk:
            break
        existing_urls.update(r["url"] for r in chunk)
        offset += len(chunk)
    print(f"  {len(existing_urls)} poster finns redan")

    new_entries = [e for e in entries if e["url"] not in existing_urls]
    print(f"  {len(new_entries)} nya att skapa")

    if dry_run:
        for e in new_entries[:10]:
            print(f"  [DRY] {e['data_source']} | {e['media_type']} | {e['name'][:60]}")
        if len(new_entries) > 10:
            print(f"  ... och {len(new_entries) - 10} till")
        return len(new_entries), 0, 0

    created = errors = 0
    for i in range(0, len(new_entries), batch_size):
        batch = new_entries[i:i + batch_size]
        vals_list = [build_vals(e) for e in batch]
        try:
            kw("clio.media.article", "create", [vals_list])
            created += len(batch)
        except Exception as ex:
            for e in batch:
                try:
                    kw("clio.media.article", "create", [build_vals(e)])
                    created += 1
                except Exception as e2:
                    errors += 1
                    print(f"  FEL: {e['url'][:80]}: {e2}")
        done = min(i + batch_size, len(new_entries))
        if done % 500 == 0 or done == len(new_entries):
            print(f"  [{done}/{len(new_entries)}] +{created} skapade, {errors} fel")

    return created, len(existing_urls), errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    if not DOWNLOAD_BASE.exists():
        sys.exit(f"FEL: {DOWNLOAD_BASE} saknas")

    print(f"Scannar {DOWNLOAD_BASE}...")
    entries = collect_files()
    if args.max:
        entries = entries[:args.max]
    print(f"Hittade {len(entries)} filer att indexera")

    by_source: dict[str, int] = {}
    for e in entries:
        by_source[e["data_source"]] = by_source.get(e["data_source"], 0) + 1
    for src, cnt in sorted(by_source.items()):
        print(f"  {cnt:5d}  {src}")

    print(f"\nAnsluter till Odoo: {URL} db={DB} user={USER}")
    kw = odoo_connect()
    print("Ansluten!")

    print(f"\nImporterar {'(dry-run) ' if args.dry_run else ''}{len(entries)} filer...")
    created, existing, errors = import_files(kw, entries, args.dry_run, args.batch_size)

    print(f"\nKlart! Skapade: {created} | Redan fanns: {existing} | Fel: {errors}")


if __name__ == "__main__":
    main()
