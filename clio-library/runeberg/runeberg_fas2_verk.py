"""
Runeberg Fas 2 — Verksidor
Läser runeberg_catalog.csv, hämtar varje verks sida,
extraherar sammanfattning/intro, sparar löpande.

Prioritet: svenska böcker → norska → danska → finska → övriga
Takt: 1 anrop per minut (schemaläggning via Task Scheduler)

Kör manuellt:    python runeberg_fas2_verk.py
Kör ett pass:    python runeberg_fas2_verk.py --batch 50
Kör en vecka:    Schemalägg i Windows Task Scheduler (se nedan)

Windows Task Scheduler — snabbstart:
  Trigger: Dagligen, upprepa var 5:e minut i 24 timmar
  Action:  python runeberg_fas2_verk.py --batch 80
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import re
import sys
import os
from datetime import datetime

INPUT_FILE  = "runeberg_catalog.csv"
OUTPUT_FILE = "runeberg_catalog.csv"   # uppdaterar på plats
LOG_FILE    = "runeberg_fas2.log"

# Språkprioritet — lägre = högre prio
LANG_PRIORITY = {"se":1,"no":2,"dk":3,"fi":4,"is":5,"fo":6,"us":7,"de":8,"":9}

DELAY_SECONDS = 62   # lite mer än 1/min för säkerhets skull

HEADERS = {
    "User-Agent": "ArvasLibraryBot/1.0 (research project; contact: fredrik@arvas.international)"
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_catalog():
    with open(INPUT_FILE, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_catalog(rows):
    if not rows:
        return
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def sort_priority(row):
    """Svenska böcker först, sedan övriga nordiska, sedan typ."""
    typ_order = {"Book":1,"Periodical":2,"Music":3,"Images":4,"Administrative":9}
    return (
        LANG_PRIORITY.get(row["sprak"], 9),
        typ_order.get(row["typ"], 9),
        row["ar"] or "9999"
    )


def fetch_work_page(url):
    """Returnerar råbytes — låter BeautifulSoup läsa <meta charset> från HTML."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.content  # bytes, inte text
    except Exception as e:
        return None


def extract_summary(html, slug):
    """
    Försöker hitta sammanfattning i denna prioritetsordning:
    1. <meta name="description"> 
    2. Explicit intro-stycke/beskrivning på verksidan
    3. Första meningsfulla stycket ur texten
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # 1. Meta description
    meta = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    if meta and meta.get("content", "").strip():
        desc = meta["content"].strip()
        if len(desc) > 30:
            return desc[:500]

    # 2. Leta efter beskrivningsstycke — Runeberg har ibland en intro-div
    #    eller en tabell med "About this book" / "Om denna bok"
    for tag in soup.find_all(["p", "div"]):
        text = tag.get_text(" ", strip=True)
        # Hoppa över navigeringslänkar och korta stycken
        if len(text) < 80:
            continue
        # Hoppa över uppenbara nav-texter
        if any(skip in text.lower() for skip in ["next page", "previous", "index", "innehållsförteckning", "marc"]):
            continue
        # Första vettiga stycket
        return text[:500]

    return ""


def process_batch(rows, batch_size):
    """Bearbetar nästa batch av ej_hanterade poster."""
    pending = [r for r in rows if r["fas2_status"] == "ej_hanterad"]

    # Sortera efter prioritet
    pending.sort(key=sort_priority)

    to_process = pending[:batch_size]

    if not to_process:
        log("Inga fler poster att bearbeta — fas 2 klar!")
        return rows, 0

    done = sum(1 for r in rows if r["fas2_status"] in ["ok","fel"])
    total = len(rows)
    log(f"Batch start: {len(to_process)} poster | Klara: {done}/{total} | Kvar: {len(pending)}")

    # Bygg lookup för snabb uppdatering
    lookup = {r["slug"]: r for r in rows}

    processed = 0
    for i, row in enumerate(to_process):
        slug = row["slug"]
        url  = row["url"]

        log(f"  [{i+1}/{len(to_process)}] {row['sprak']} | {row['typ']} | {row['titel'][:50]}")

        html = fetch_work_page(url)

        if html:
            summary = extract_summary(html, slug)
            lookup[slug]["sammanfattning"] = summary
            if "ej hanterad" in html.decode("utf-8", errors="replace").lower():
                lookup[slug]["fas2_status"] = "ej_klar"
                log(f"    → EJ KLAR (sidan ej hanterad på Runeberg)")
            else:
                lookup[slug]["fas2_status"] = "ok"
                log(f"    → OK ({len(summary)} tecken)")
        else:
            lookup[slug]["fas2_status"] = "fel"
            log(f"    → FEL (kunde inte hämta)")

        processed += 1

        # Spara efter varje post — crash-säkert
        save_catalog(list(lookup.values()))

        # Vänta mellan anrop (sista posten behöver inte vänta)
        if i < len(to_process) - 1:
            time.sleep(DELAY_SECONDS)

    return list(lookup.values()), processed


def report(rows):
    ok      = sum(1 for r in rows if r["fas2_status"] == "ok")
    fel     = sum(1 for r in rows if r["fas2_status"] == "fel")
    ej_klar = sum(1 for r in rows if r["fas2_status"] == "ej_klar")
    ej      = sum(1 for r in rows if r["fas2_status"] == "ej_hanterad")
    sv_ok   = sum(1 for r in rows if r["fas2_status"] == "ok" and r["sprak"] == "se" and r["typ"] == "Book")
    log(f"Status: {ok} ok | {ej_klar} ej_klar | {fel} fel | {ej} kvar | Svenska böcker klara: {sv_ok}")


def main():
    batch_size = 80   # default ~80 min per körning
    if "--batch" in sys.argv:
        try:
            batch_size = int(sys.argv[sys.argv.index("--batch") + 1])
        except:
            pass

    if not os.path.exists(INPUT_FILE):
        print(f"Hittar inte {INPUT_FILE} — kör fas1 först.")
        sys.exit(1)

    rows = load_catalog()
    log(f"Fas 2 start | {len(rows):,} poster totalt | batch={batch_size}")

    rows, processed = process_batch(rows, batch_size)
    report(rows)

    log(f"Fas 2 pass klart — {processed} poster bearbetade.")


if __name__ == "__main__":
    main()
