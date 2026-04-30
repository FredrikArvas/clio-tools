"""
parse_geni_activity.py
Parsar Genis aktivitetsdump (index.html + html/Revisions.html) och
producerar geni_relations.json med:
  - Geni-ID per person
  - Geni-URL per person
  - followed: True för personer i "Followed Pages"
  - relations: lista med {type, geni_id, name} (svenska etiketter)

Kör: python parse_geni_activity.py [--activity-dir PATH] [--output FILE]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

# ── Relationsöversättning ──────────────────────────────────────────────────────

# Engelska Geni-relationer → svenska etiketter för clio.partner.link
# Riktning: "A added as B's [rel]" → A:s relation TILL B
RELATION_TO_TARGET = {
    "wife":       "make/maka",
    "husband":    "make/maka",
    "spouse":     "make/maka",
    "partner":    "make/maka",
    "ex-wife":    "make/maka",
    "ex-husband": "make/maka",
    "brother":    "syskon",
    "sister":     "syskon",
    "sibling":    "syskon",
    "father":     "förälder",
    "mother":     "förälder",
    "parent":     "förälder",
    "son":        "barn",
    "daughter":   "barn",
    "child":      "barn",
}

# Spegelrelation: om A är B:s "son" → B är A:s "förälder"
MIRROR = {
    "make/maka": "make/maka",
    "syskon":    "syskon",
    "förälder":  "barn",
    "barn":      "förälder",
}


def _geni_id_from_url(url: str) -> str | None:
    """Extraherar numeriskt Geni-ID ur en geni.com/people/-URL."""
    m = re.search(r"/people/[^/]+/(\d+)", url)
    return m.group(1) if m else None


def _clean_name(name: str) -> str:
    return name.strip().replace("\xa0", " ")


# ── Parsning av index.html ────────────────────────────────────────────────────

def parse_followed(index_path: Path) -> dict[str, dict]:
    """
    Läser "Followed Pages" ur index.html.
    Returnerar {geni_id: {name, geni_url, followed: True}}.
    """
    persons: dict[str, dict] = {}
    with open(index_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    in_followed = False
    for row in soup.find_all("tr"):
        th = row.find("th")
        td = row.find("td")
        if not th or not td:
            h2 = row.find("h2")
            if h2:
                in_followed = "Followed Pages" in h2.get_text()
            continue

        if not in_followed:
            continue

        link = td.find("a", href=True)
        if not link:
            continue

        url = link["href"]
        geni_id = _geni_id_from_url(url)
        if not geni_id:
            continue

        name = _clean_name(th.get_text())
        persons[geni_id] = {
            "geni_id":  geni_id,
            "name":     name,
            "geni_url": url,
            "followed": True,
            "relations": [],
        }

    return persons


# ── Parsning av Revisions.html ────────────────────────────────────────────────

# Mönster 1: "A was added as B's [rel] by C"
_RE_ADDED = re.compile(r"was added as .+?'s ([\w-]+) by", re.IGNORECASE)
# Mönster 2: "A was connected to B as his/her [rel] by C"
_RE_CONNECTED = re.compile(r"was connected to .+ as (?:his|her) ([\w-]+) by", re.IGNORECASE)


def _extract_relation(text: str) -> str | None:
    m = _RE_ADDED.search(text) or _RE_CONNECTED.search(text)
    return m.group(1).lower() if m else None


def parse_revisions(revisions_path: Path) -> dict[str, dict]:
    """
    Läser "Profiles Added" ur Revisions.html.
    Returnerar {geni_id: {name, geni_url, relations: [...]}}.
    Bygger upp relationer i BÅDA riktningar.
    """
    persons: dict[str, dict] = {}

    def _ensure(geni_id: str, name: str, url: str = "") -> dict:
        if geni_id not in persons:
            persons[geni_id] = {
                "geni_id":  geni_id,
                "name":     _clean_name(name),
                "geni_url": url or f"https://www.geni.com/api/profile-{geni_id}",
                "followed": False,
                "relations": [],
            }
        return persons[geni_id]

    def _add_rel(from_id: str, to_id: str, rel_label: str, to_name: str):
        """Lägger till en relation om den inte redan finns."""
        p = persons[from_id]
        existing = {(r["geni_id"], r["type"]) for r in p["relations"]}
        if (to_id, rel_label) not in existing:
            p["relations"].append({
                "type":    rel_label,
                "geni_id": to_id,
                "name":    _clean_name(to_name),
            })

    with open(revisions_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    # Fredriks eget ID — den som lade till allt (tredje länken i varje rad)
    fredrik_id = "6000000010220784154"

    for row in soup.find_all("tr"):
        td = row.find("td")
        if not td:
            continue

        text = td.get_text(" ", strip=True)
        if "was added as" not in text and "was connected to" not in text:
            continue

        rel_en = _extract_relation(text)
        if not rel_en:
            continue

        rel_label = RELATION_TO_TARGET.get(rel_en)
        if not rel_label:
            continue  # okänd relationstyp

        links = td.find_all("a", attrs={"data-profile-id": True})
        if len(links) < 2:
            continue

        # Länk 0 = person A (tillagd), länk 1 = person B (ankaret)
        # Länk 2 = den som lade till (Fredrik) — hoppa över
        id_a = links[0]["data-profile-id"]
        id_b = links[1]["data-profile-id"]
        name_a = links[0].get_text(strip=True)
        name_b = links[1].get_text(strip=True)
        url_a = links[0].get("href", "")
        url_b = links[1].get("href", "")

        if id_a == fredrik_id or id_b == fredrik_id:
            # En av dem är Fredrik — ändå intressant, behåll
            pass

        _ensure(id_a, name_a, url_a)
        _ensure(id_b, name_b, url_b)

        # A → B: rel_label (t.ex. A är B:s "son" → A:s relation till B = "förälder")
        _add_rel(id_a, id_b, rel_label, name_b)
        # B → A: spegelrelation (B:s relation till A = "barn")
        mirror = MIRROR.get(rel_label, rel_label)
        _add_rel(id_b, id_a, mirror, name_a)

    return persons


# ── Sammanslagning ────────────────────────────────────────────────────────────

def merge(followed: dict, revisions: dict) -> dict:
    """
    Slår ihop followed + revisions.
    followed-flaggan prioriteras; namn från followed om tillgängligt.
    """
    merged = dict(revisions)
    for geni_id, data in followed.items():
        if geni_id in merged:
            merged[geni_id]["followed"] = True
            merged[geni_id]["geni_url"] = data["geni_url"]
            # Namn från followed är mer korrekt (Fredrik la in dem manuellt)
            merged[geni_id]["name"] = data["name"]
        else:
            merged[geni_id] = data
    return merged


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(description="Parsa Geni aktivitetsdump → geni_relations.json")
    p.add_argument(
        "--activity-dir",
        default=r"C:\Users\fredr\Dropbox\ulrika-fredrik\släktforskning\släkten Fredrik arvas\släktträdsfiler\geni_download_activity_Fredrik_Arvas_20260406022454",
        help="Sökväg till den uppackade aktivitetsdumpen",
    )
    p.add_argument(
        "--output",
        default="geni_relations.json",
        help="Utdatafil (default: geni_relations.json)",
    )
    args = p.parse_args(argv)

    base = Path(args.activity_dir)
    index_path = base / "index.html"
    revisions_path = base / "html" / "Revisions.html"

    if not index_path.exists():
        print(f"Hittar inte: {index_path}", file=sys.stderr)
        sys.exit(1)
    if not revisions_path.exists():
        print(f"Hittar inte: {revisions_path}", file=sys.stderr)
        sys.exit(1)

    print("Läser Followed Pages från index.html...")
    followed = parse_followed(index_path)
    print(f"  {len(followed)} följda personer")

    print("Läser relationer från Revisions.html...")
    revisions = parse_revisions(revisions_path)
    print(f"  {len(revisions)} unika personer, "
          f"{sum(len(p['relations']) for p in revisions.values())} relationer")

    merged = merge(followed, revisions)

    followed_count = sum(1 for p in merged.values() if p["followed"])
    rel_count = sum(len(p["relations"]) for p in merged.values())
    print(f"\nResultat: {len(merged)} personer, {followed_count} följda, {rel_count} relationer")

    out = Path(args.output)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"Sparat: {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
