"""
Runeberg Fas 1 — Katalogskrapning
Hämtar hela titellistan från runeberg.org/katalog.html
och sparar som runeberg_catalog.csv

Kör: python runeberg_fas1_katalog.py
"""

import requests
from bs4 import BeautifulSoup
import csv
import re
from collections import Counter
from datetime import datetime

BASE_URL = "https://runeberg.org"
CATALOG_URL = f"{BASE_URL}/katalog.html"
OUTPUT_FILE = "runeberg_catalog.csv"

HEADERS = {
    "User-Agent": "ArvasLibraryBot/1.0 (research project; contact: fredrik@arvas.international)"
}


def fetch_catalog():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Hämtar katalog...")
    r = requests.get(CATALOG_URL, headers=HEADERS, timeout=90)
    r.raise_for_status()
    r.encoding = "utf-8"
    print(f"  → {len(r.text):,} tecken")
    return r.text


def parse_catalog(html):
    soup = BeautifulSoup(html, "html.parser")
    books = []
    rows = soup.find_all("tr")
    print(f"  → {len(rows):,} rader hittade")

    for row in rows:
        cells = row.find_all("td")
        # Varje datarad har 11 celler (varannan är &nbsp;-avdelare)
        if len(cells) < 11:
            continue

        # Cell 0: <img alt="Book"> → typ
        typ_img = cells[0].find("img")
        if not typ_img:
            continue
        typ = typ_img.get("alt", "").strip()
        if not typ:
            continue

        # Cell 4: titellänk
        title_cell = cells[4]
        link = title_cell.find("a")
        if not link:
            continue
        href = link.get("href", "")
        if not href.startswith("/"):
            continue
        title = link.get_text(strip=True)
        slug = href.strip("/").split("/")[0]
        url = f"{BASE_URL}/{slug}/"

        if not title or not slug:
            continue

        # Cell 6: författare (länktext eller ren text)
        author_cell = cells[6]
        author_link = author_cell.find("a")
        if author_link:
            author = author_link.get_text(strip=True)
        else:
            author = author_cell.get_text(strip=True)

        # Cell 8: år
        year = cells[8].get_text(strip=True)
        if not re.match(r"^\d{4}$", year):
            year = ""

        # Cell 10: <img alt="se"> → språk
        lang_img = cells[10].find("img")
        lang = lang_img.get("alt", "").strip() if lang_img else ""

        books.append({
            "typ": typ,
            "titel": title,
            "forfattare": author,
            "ar": year,
            "sprak": lang,
            "slug": slug,
            "url": url,
            "sammanfattning": "",
            "keywords": "",
            "fas2_status": "ej_hanterad"
        })

    return books


def save_and_report(books):
    fieldnames = ["typ","titel","forfattare","ar","sprak","slug","url",
                  "sammanfattning","keywords","fas2_status"]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(books)

    print(f"\n✓ Sparad: {OUTPUT_FILE}  ({len(books):,} poster)\n")

    print("Typer:")
    for t, n in Counter(b["typ"] for b in books).most_common():
        print(f"  {t:<15} {n:>5}")
    print("\nSpråk:")
    for s, n in Counter(b["sprak"] for b in books).most_common():
        print(f"  {s:<6} {n:>5}")

    sv = sum(1 for b in books if b["sprak"] == "se" and b["typ"] == "Book")
    print(f"\nSvenska böcker redo för Fas 2: {sv:,}")


def main():
    print("=" * 50)
    print("Runeberg Fas 1 — Katalogskrapning")
    print("=" * 50)
    html = fetch_catalog()
    books = parse_catalog(html)
    if not books:
        print("Inga poster. Sparar debug-HTML.")
        open("runeberg_debug.html","w",encoding="utf-8").write(html)
        return
    save_and_report(books)
    print("\nFas 1 klar → kör runeberg_fas2_verk.py")

if __name__ == "__main__":
    main()
