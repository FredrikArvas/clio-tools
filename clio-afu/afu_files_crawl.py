#!/usr/bin/env python3
"""
afu_files_crawl.py — Kartlägger och laddar ner filer från files.afu.se

Steg 1 (--mode map):   Rekursivt crawler katalogträdet, sparar manifest.
Steg 2 (--mode fetch): Laddar ner filer som matchar prioritetsregler.

Usage:
    python3 afu_files_crawl.py --mode map            # kartlägg hela trädet
    python3 afu_files_crawl.py --mode fetch           # ladda ner prioriterade filer
    python3 afu_files_crawl.py --mode map --max-depth 5  # begränsa djup

Kräver: pip install requests beautifulsoup4 lxml
Output:
    data/afu_files_manifest.jsonl  — ett JSON-objekt per fil
    data/downloads/                — nedladdade filer
"""

import argparse
import json
import re
import time
import random
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, unquote

import requests
from bs4 import BeautifulSoup

# ─── Konfiguration ────────────────────────────────────────────────────────────

BASE_URL    = "https://files.afu.se/Downloads/"
ROOT_DIR    = "./"

OUTPUT_DIR  = Path(__file__).parent / "data"
MANIFEST    = OUTPUT_DIR / "afu_files_manifest.jsonl"
DOWNLOAD_DIR = OUTPUT_DIR / "downloads"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ─── Prioritetsregler — vad som laddas ner automatiskt ───────────────────────
# path-fragment (lowercase) → True = ladda ner
PRIORITY_PATTERNS = [
    "larry hatch",
    "databases/",
    "ufo-reports/scandinavia",
    "ufo-reports/united kingdom",
    "documents/usa - aaro",
    "documents/usa - cia",
    "documents/usa - fbi",
    "documents/usa - congress",
    "documents/usa - aatip",
    "documents/0 - ufo researchers",
    "topics/",
]

# Max filstorlek att ladda ner automatiskt (bytes)
MAX_AUTO_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

# ─── Hjälpfunktioner ──────────────────────────────────────────────────────────

def polite_sleep(min_s=2.0, max_s=5.0):
    time.sleep(random.uniform(min_s, max_s))


def is_priority(path: str) -> bool:
    p = path.lower()
    return any(pat in p for pat in PRIORITY_PATTERNS)


def parse_size(size_str: str) -> int:
    """Konverterar '2.54 MB' → bytes. Kräver explicit enhet för att undvika false matches."""
    size_str = size_str.strip()
    m = re.match(r"^([\d.]+)\s*(B|KB|MB|GB)$", size_str, re.I)
    if not m:
        return 0
    try:
        val = float(m.group(1))
    except ValueError:
        return 0
    unit = m.group(2).upper()
    return int(val * {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}[unit])

# ─── Steg 1: Kartläggning ─────────────────────────────────────────────────────

def crawl_directory(dir_path: str, depth: int, max_depth: int,
                    visited: set, manifest_fh, stats: dict):
    """Rekursivt crawlar en katalog på files.afu.se."""
    if depth > max_depth:
        return
    if dir_path in visited:
        return
    visited.add(dir_path)

    url = BASE_URL + "?dir=" + dir_path
    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"{'  '*depth}FEL {dir_path}: {e}")
        return

    soup = BeautifulSoup(resp.text, "html.parser")

    # Hitta alla table-rader med filer och kataloger
    for a in soup.find_all("a", href=True):
        href = a["href"]

        # Subdirectory-länk (exkludera sorteringslänkar som har &order= i href)
        if "/Downloads/?dir=" in href and "&order=" not in href:
            raw = href.split("?dir=")[-1]
            sub_path = unquote(raw).lstrip("./")
            full_path = "./" + sub_path if not sub_path.startswith("./") else sub_path
            if full_path != dir_path and full_path not in visited:
                name = a.get_text(strip=True)
                print(f"{'  '*depth}📁 {name}")
                polite_sleep(1.5, 3.5)
                crawl_directory(full_path, depth + 1, max_depth, visited, manifest_fh, stats)

        # Fil-länk
        elif href.startswith("/Downloads/./"):
            file_path = unquote(href[len("/Downloads/./"):])
            file_url  = "https://files.afu.se/Downloads/./" + requests.utils.quote(file_path, safe="/")
            name      = a.get_text(strip=True)

            # Hämta storlek från nästa cell (syskonelement i table)
            parent = a.find_parent("tr") or a.find_parent("td")
            size_str = ""
            if parent:
                cells = parent.find_all(["td", "generic"])
                # Storleken brukar vara det andra elementet efter filen
                texts = [c.get_text(strip=True) for c in cells]
                for t in texts:
                    if re.match(r"[\d.]+\s*(B|KB|MB|GB)", t, re.I):
                        size_str = t
                        break

            size_bytes = parse_size(size_str) if size_str else 0
            priority   = is_priority(dir_path)

            record = {
                "path":       dir_path,
                "name":       name,
                "url":        file_url,
                "size_str":   size_str,
                "size_bytes": size_bytes,
                "priority":   priority,
                "discovered": datetime.utcnow().isoformat(),
            }
            manifest_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            manifest_fh.flush()

            flag = "★" if priority else " "
            print(f"{'  '*depth}{flag} {name}  ({size_str})")
            stats["files"] += 1
            if priority:
                stats["priority"] += 1

# ─── Steg 2: Nedladdning ──────────────────────────────────────────────────────

def fetch_files(max_bytes: int = MAX_AUTO_DOWNLOAD_BYTES):
    """Läser manifestet och laddar ner prioriterade filer."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    records = []
    with open(MANIFEST, encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except Exception:
                pass

    priority = [r for r in records if r.get("priority") and r.get("size_bytes", 0) <= max_bytes]
    print(f"Prioriterade filer: {len(priority)} (av {len(records)} totalt, max {max_bytes//1024//1024} MB)")

    for i, r in enumerate(priority, 1):
        # Bygg lokal sökväg speglande katalogstrukturen
        rel = r["path"].lstrip("./").rstrip("/")
        local_dir = DOWNLOAD_DIR / rel
        local_dir.mkdir(parents=True, exist_ok=True)
        local_file = local_dir / r["name"]

        if local_file.exists():
            print(f"[{i}/{len(priority)}] HOPPAR (finns): {r['name']}")
            continue

        print(f"[{i}/{len(priority)}] Laddar ner: {r['name']}  ({r.get('size_str', '?')})")
        try:
            resp = SESSION.get(r["url"], timeout=120, stream=True)
            resp.raise_for_status()
            with open(local_file, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    fh.write(chunk)
            print(f"  → {local_file}")
        except Exception as e:
            print(f"  FEL: {e}")
        polite_sleep(3, 8)

    print(f"\nNedladdning klar → {DOWNLOAD_DIR}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Kartlägg och ladda ner filer från files.afu.se")
    parser.add_argument("--mode",      choices=["map", "fetch", "both"], default="map")
    parser.add_argument("--max-depth", type=int, default=8, help="Max rekursionsdjup (default 8)")
    parser.add_argument("--max-mb",    type=int, default=20, help="Max filstorlek att ladda ner (MB)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.mode in ("map", "both"):
        print(f"Kartlägger files.afu.se (max djup: {args.max_depth})\n")
        visited = set()
        stats = {"files": 0, "priority": 0}

        # Ladda redan-besökta sökvägar för resume
        if MANIFEST.exists():
            with open(MANIFEST, encoding="utf-8") as f:
                for line in f:
                    try:
                        visited.add(json.loads(line).get("path", ""))
                    except Exception:
                        pass

        with open(MANIFEST, "a", encoding="utf-8") as manifest_fh:
            crawl_directory(ROOT_DIR, depth=0, max_depth=args.max_depth,
                            visited=visited, manifest_fh=manifest_fh, stats=stats)

        print(f"\nKlart! {stats['files']} filer hittade ({stats['priority']} prioriterade) → {MANIFEST}")

    if args.mode in ("fetch", "both"):
        print(f"\nLaddar ner prioriterade filer (max {args.max_mb} MB)...")
        fetch_files(max_bytes=args.max_mb * 1024 * 1024)


if __name__ == "__main__":
    main()
