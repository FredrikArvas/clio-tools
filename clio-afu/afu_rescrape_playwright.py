#!/usr/bin/env python3
"""
afu_rescrape_playwright.py — Hämtar brödtext + filänkar från afu.se med Playwright

Läser URL:er från data/afu_posts.jsonl och skriver fullständiga poster till
data/afu_posts_full.jsonl (resume-safe: hoppar poster som redan finns).

Extraherar:
  - text: brödtext via .fusion-text (Avada-temat)
  - file_links: direktlänkade filer (xlsx, xls, pdf, csv, docx, zip)
  - images: bildlänkar i artikeln

Usage:
    python3 afu_rescrape_playwright.py [--max N] [--delay FLOAT]
    python3 afu_rescrape_playwright.py --max 5    # testa
"""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

INPUT_FILE  = Path(__file__).parent / "data" / "afu_posts.jsonl"
OUTPUT_FILE = Path(__file__).parent / "data" / "afu_posts_full.jsonl"

FILE_EXTS = {".xlsx", ".xls", ".pdf", ".csv", ".docx", ".zip", ".ods"}

CONTENT_SELECTORS = [
    ".fusion-text",
    ".post-content",
    ".entry-content",
    ".fusion-builder-row",
]


def extract_content(page) -> dict:
    """Extrahera text och fillänkar från en laddad sida."""
    text = ""
    for sel in CONTENT_SELECTORS:
        els = page.query_selector_all(sel)
        if els:
            parts = [el.inner_text() for el in els]
            text = "\n".join(p.strip() for p in parts if p.strip())
            if len(text) > 50:
                break

    # Fillänkar
    file_links = []
    for a in page.query_selector_all("a[href]"):
        href = a.get_attribute("href") or ""
        ext = Path(href.split("?")[0]).suffix.lower()
        if ext in FILE_EXTS:
            label = a.inner_text().strip()
            full_url = urljoin(page.url, href)
            file_links.append({"url": full_url, "label": label, "ext": ext.lstrip(".")})

    # Bilder i artikel
    images = []
    for img in page.query_selector_all("article img, .fusion-text img, .post-content img"):
        src = img.get_attribute("src") or ""
        alt = img.get_attribute("alt") or ""
        if src and "wp-content" in src:
            images.append({"url": src, "alt": alt})

    return {"text": text, "file_links": file_links, "images": images}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=0, help="Max antal poster (0=alla)")
    parser.add_argument("--delay", type=float, default=2.5, help="Sekunder mellan requests")
    args = parser.parse_args()

    if not INPUT_FILE.exists():
        print(f"Input saknas: {INPUT_FILE}")
        return

    posts = [json.loads(l) for l in INPUT_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]

    # Redan klara
    done_urls: set = set()
    if OUTPUT_FILE.exists():
        for line in OUTPUT_FILE.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                done_urls.add(r["url"])
            except Exception:
                pass
    print(f"Totalt: {len(posts)} poster | Redan klara: {len(done_urls)}")

    todo = [p for p in posts if p.get("url") not in done_urls]
    if args.max:
        todo = todo[:args.max]
    print(f"Att hämta: {len(todo)}")

    out = OUTPUT_FILE.open("a", encoding="utf-8")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="sv-SE",
        )
        page = context.new_page()

        for i, post in enumerate(todo, 1):
            url = post["url"]
            print(f"[{i}/{len(todo)}] {post.get('title', url)[:70]}")
            try:
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                print(f"  TIMEOUT — sparar med tom text")
            except Exception as e:
                print(f"  FEL: {e}")

            content = extract_content(page)

            record = {**post, **content}
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()

            if content["file_links"]:
                for fl in content["file_links"]:
                    print(f"  📎 {fl['ext'].upper()}: {fl['label'][:50]} — {fl['url'][:70]}")

            if i < len(todo):
                time.sleep(args.delay)

        browser.close()

    out.close()
    total_done = sum(1 for _ in OUTPUT_FILE.read_text(encoding="utf-8").splitlines() if _.strip())
    print(f"\nKlart. {total_done} poster i {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
