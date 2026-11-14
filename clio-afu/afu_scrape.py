#!/usr/bin/env python3
"""
afu_scrape.py — Indexerar afu.se via sitemap (WordPress), politely
Kör från ~/19.0/clio-tools/clio-afu/

Usage:
    python3 afu_scrape.py --group posts   # ~500 poster (nyheter/donationer)
    python3 afu_scrape.py --group pages   # ~60 statiska sidor
    python3 afu_scrape.py --group all     # båda
    python3 afu_scrape.py --group posts --max 100  # testa med 100

Standardbeteende: slumpad fördröjning 3–7s, längre paus var 25:e request.
Kräver: pip install requests beautifulsoup4 lxml
Output: data/afu_posts.jsonl  (resume-safe)
"""

import argparse
import json
import random
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ─── Konfiguration ────────────────────────────────────────────────────────────

GROUPS = {
    "posts": ["https://www.afu.se/post-sitemap1.xml"],
    "pages": ["https://www.afu.se/page-sitemap1.xml"],
    # news-sidan är paginerad och finns EJ i sitemap — hämtas separat
    "news":  [],   # byggs dynamiskt via discover_news_urls()
}

OUTPUT_DIR  = Path(__file__).parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "afu_posts.jsonl"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ─── News-paginering ──────────────────────────────────────────────────────────

def discover_news_urls() -> list:
    """Hittar alla artikel-URL:er via paginerad news-lista."""
    found = []
    page = 1
    while True:
        if page == 1:
            url = "https://www.afu.se/news/"
        else:
            url = f"https://www.afu.se/news/page/{page}/"
        try:
            resp = SESSION.get(url, timeout=30)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
        except Exception:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        # WordPress article links — hämta alla a[href] inuti article-taggar
        links = []
        for article in soup.find_all("article"):
            a = article.find("a", href=True)
            if a and "afu.se" in a["href"]:
                links.append(a["href"])

        if not links:
            break
        found.extend(links)
        print(f"  news/page/{page}: {len(links)} artiklar")

        # Kolla om det finns en "next"-länk
        next_link = soup.find("a", class_=re.compile(r"next|nav-next"))
        if not next_link:
            break
        page += 1
        time.sleep(random.uniform(2, 4))

    # Avduplicera
    return list(dict.fromkeys(found))


# ─── Sitemap ──────────────────────────────────────────────────────────────────

def fetch_sitemap_urls(sitemap_url: str) -> list:
    resp = SESSION.get(sitemap_url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [loc.text.strip() for loc in root.findall(".//sm:loc", ns)]


def load_done_urls(output_file: Path) -> set:
    done = set()
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["url"])
                except Exception:
                    pass
    return done

# ─── Extrahering ──────────────────────────────────────────────────────────────

def extract_post(url: str) -> dict:
    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        return {"url": url, "error": str(e), "scraped_at": datetime.utcnow().isoformat()}

    soup = BeautifulSoup(resp.text, "html.parser")

    # Titel
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else (soup.title.string or "").strip()

    # Datum
    date = ""
    t = soup.find("time")
    if t:
        date = t.get("datetime", t.get_text(strip=True))
    if not date:
        m = soup.find("meta", {"property": "article:published_time"})
        if m:
            date = m.get("content", "")

    # Brödtext
    body = (
        soup.find("article")
        or soup.find(class_="entry-content")
        or soup.find(class_="post-content")
        or soup.find("main")
    )
    if body:
        for tag in body.find_all(["nav", "aside", "script", "style", "footer"]):
            tag.decompose()
        text = body.get_text(separator="\n", strip=True)
    else:
        text = soup.get_text(separator="\n", strip=True)

    cats   = [a.get_text(strip=True) for a in soup.select(".cat-links a, .entry-category a, .categories a")]
    tags   = [a.get_text(strip=True) for a in soup.select(".tags-links a, .entry-tags a")]
    images = [i.get("src", "") for i in (body or soup).find_all("img") if i.get("src")][:5]

    return {
        "url":        url,
        "title":      title,
        "date":       date,
        "text":       text[:8000],
        "categories": cats,
        "tags":       tags,
        "images":     images,
        "scraped_at": datetime.utcnow().isoformat(),
        "source":     "afu.se",
    }

# ─── Fördröjning ──────────────────────────────────────────────────────────────

def polite_sleep(i: int, min_s: float, max_s: float, burst: int, long_pause: float):
    """Slumpad fördröjning. Var <burst>:e request tas en längre paus."""
    if i > 0 and i % burst == 0:
        p = long_pause + random.uniform(-5, 10)
        print(f"  [paus {p:.0f}s efter {burst} requests]")
        time.sleep(max(p, 15))
    else:
        time.sleep(random.uniform(min_s, max_s))

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Polite scraper för afu.se")
    parser.add_argument("--group",      choices=["posts", "pages", "all"], default="posts")
    parser.add_argument("--max",        type=int,   default=0,   help="Max antal sidor (0 = alla)")
    parser.add_argument("--min-delay",  type=float, default=3.0, help="Min sekunder mellan requests")
    parser.add_argument("--max-delay",  type=float, default=7.0, help="Max sekunder mellan requests")
    parser.add_argument("--burst",      type=int,   default=25,  help="Längre paus var N:e request")
    parser.add_argument("--long-pause", type=float, default=45,  help="Längre pauslängd (sekunder)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Välj sitemaps / URL-källa
    if args.group == "all":
        sitemaps = GROUPS["posts"] + GROUPS["pages"]
    elif args.group == "news":
        sitemaps = []
    else:
        sitemaps = GROUPS[args.group]

    all_urls = []
    for sm in sitemaps:
        print(f"  Läser sitemap: {sm}")
        urls = fetch_sitemap_urls(sm)
        print(f"    → {len(urls)} URL:er")
        all_urls.extend(urls)

    if args.group in ("news", "all"):
        print("  Söker news-artiklar via paginering...")
        news_urls = discover_news_urls()
        print(f"    → {len(news_urls)} artiklar hittade")
        all_urls.extend(news_urls)

    # Avduplicera
    seen, unique_urls = set(), []
    for u in all_urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    print(f"\nGrupp: {args.group} | Totalt: {len(unique_urls)} unika URL:er")

    done = load_done_urls(OUTPUT_FILE)
    todo = [u for u in unique_urls if u not in done]
    if args.max:
        todo = todo[:args.max]

    print(f"Redan klara: {len(done)} | Kvar: {len(todo)}")
    print(f"Fördröjning: {args.min_delay}–{args.max_delay}s | Längre paus var {args.burst}:e req ({args.long_pause}s)")
    eta_min = len(todo) * (args.min_delay + args.max_delay) / 2 / 60
    print(f"Uppskattad tid: ~{eta_min:.0f} min\n")

    if not todo:
        print("Inget att göra.")
        return

    with open(OUTPUT_FILE, "a", encoding="utf-8") as out:
        for i, url in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {url}")
            record = extract_post(url)
            if record.get("error"):
                print(f"  FEL: {record['error']}")
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            polite_sleep(i, args.min_delay, args.max_delay, args.burst, args.long_pause)

    print(f"\nKlart! → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
