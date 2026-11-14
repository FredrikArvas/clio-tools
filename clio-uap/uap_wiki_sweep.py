"""
uap_wiki_sweep.py — Systematisk genomsökning av ALLA aktiva Wikipedia-utgåvor

Fas 0: Discovery
  - Hämtar alla 345 aktiva Wikipedia-utgåvor via Wikimedia sitematrix API
  - Söker kategorinamnsrymden (ns=14) på varje utgåva efter UAP-termer
  - Sparar resultat i wiki_discovered_cats.json

Fas 1 (efter discovery): Import
  - Läser wiki_discovered_cats.json
  - Importerar fall från alla funna kategorier (dedup via source_ref)

Syfte: Skapa ett dokumenterbart, reproducerbart golv av Wikipedia UAP-data
       Varje utgåva, varje land, transparent metod för publicering.

Kör:
  python3 uap_wiki_sweep.py --discover          # Hitta kategorier (skriv ej till Odoo)
  python3 uap_wiki_sweep.py --import-all        # Importera från funna kategorier
  python3 uap_wiki_sweep.py --import-all --dry-run
  python3 uap_wiki_sweep.py --status            # Visa discovery-resultat
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.request, urllib.parse
from pathlib import Path

UA = "clio-uap-research/1.0 (contact: research@arvas.international)"
DISCOVERED_FILE = Path(__file__).parent / "wiki_discovered_cats.json"

# UAP-söktermer per språkgrupp (fallback: "UFO")
SEARCH_TERMS: dict[str, list[str]] = {
    "ar": ["مشاهدات الأجسام الطائرة المجهولة", "UFO"],
    "az": ["UNO", "UFO"],
    "bg": ["НЛО"],
    "bs": ["NLO", "UFO"],
    "ca": ["OVNI"],
    "cs": ["UFO"],
    "da": ["ufo", "UFO"],
    "de": ["UFO-Sichtung", "UFO"],
    "el": ["UFO", "ΑΤΙΑ"],
    "es": ["OVNI"],
    "et": ["UFO"],
    "eu": ["OEZ", "UFO"],
    "fa": ["UFO", "جسم پرنده ناشناس"],
    "fi": ["UFO", "ufo"],
    "fr": ["OVNI", "ovni"],
    "gl": ["OVNI", "UFO"],
    "he": ["עב\"ם", "UFO"],
    "hr": ["NLO", "UFO"],
    "hu": ["UFO"],
    "hy": ["ԱԹՕ", "UFO"],
    "id": ["UFO"],
    "it": ["UFO"],
    "ja": ["UFO", "未確認飛行物体"],
    "ka": ["UFO", "ნნო"],
    "ko": ["UFO", "미확인비행물체"],
    "lt": ["NSO", "UFO"],
    "lv": ["NFO", "UFO"],
    "mk": ["НЛО", "UFO"],
    "ms": ["UFO"],
    "nl": ["UFO"],
    "nn": ["UFO"],
    "no": ["UFO"],
    "pl": ["UFO"],
    "pt": ["OVNI", "UFO"],
    "ro": ["OZN", "UFO"],
    "ru": ["НЛО", "UFO"],
    "sk": ["UFO", "NLO"],
    "sl": ["NLP", "UFO"],
    "sq": ["UFO"],
    "sr": ["НЛО", "NLO"],
    "sv": ["UFO"],
    "th": ["UFO", "ยูเอฟโอ"],
    "tr": ["UFO"],
    "uk": ["НЛО", "UFO"],
    "vi": ["UFO"],
    "zh": ["UFO", "不明飞行物"],
}

# Kategorier som bevisligen handlar om BANDET UFO eller urelaterat
BLOCKLIST_KEYWORDS = [
    "album", "members", "discography", "songs", "music", "band",
    "film", "manga", "anime", "novel", "game", "fiction",
    "mitglied",  # de: member
    "musikgruppe",  # de
    "musikband",
    "록밴드",  # ko: rock band
    "δισκογραφ",  # el: discography
    "kategorio:ufa",  # eo: UFA city/film studio
    "kategori:ufa",   # similar
]


def http_get(url: str, delay: float = 1.0) -> bytes | None:
    if delay:
        time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404):
                return None
            if attempt == 0:
                time.sleep(5)
                continue
            return None
        except Exception:
            if attempt == 0:
                time.sleep(3)
                continue
            return None
    return None


def get_all_wikis() -> list[dict]:
    """Hämtar alla aktiva Wikipedia-utgåvor via Wikimedia sitematrix."""
    url = "https://meta.wikimedia.org/w/api.php?action=sitematrix&smtype=language&format=json"
    raw = http_get(url, delay=0)
    if not raw:
        sys.exit("Kunde inte hämta sitematrix")
    data = json.loads(raw)
    matrix = data["sitematrix"]
    wikis = []
    for key, val in matrix.items():
        if not isinstance(val, dict) or "code" not in val:
            continue
        code = val["code"]
        name = val.get("localname", val.get("name", code))
        for s in val.get("site", []):
            if s.get("code") == "wiki" and "closed" not in s:
                wikis.append({"lang": code, "name": name,
                               "url": s.get("url", f"https://{code}.wikipedia.org")})
                break
    return wikis


def is_blocked(title: str) -> bool:
    tl = title.lower()
    return any(kw in tl for kw in BLOCKLIST_KEYWORDS)


def search_uap_category(lang: str, delay: float = 1.0) -> str | None:
    """
    Söker kategorinamnsrymden (ns=14) på given Wikipedia-utgåva.
    Returnerar bästa matchande kategorititeln, eller None.
    """
    terms = SEARCH_TERMS.get(lang, ["UFO"])
    for term in terms:
        url = (f"https://{lang}.wikipedia.org/w/api.php"
               f"?action=query&list=search&srsearch={urllib.parse.quote(term)}"
               f"&srnamespace=14&srlimit=5&format=json")
        raw = http_get(url, delay=delay)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        hits = data.get("query", {}).get("search", [])
        for h in hits:
            title = h["title"]
            if not is_blocked(title):
                # Snabbkoll: har kategorin faktiska artiklar?
                members = get_cat_page_count(lang, title, delay=0.5)
                if members > 0:
                    return title
    return None


def get_cat_page_count(lang: str, cat_title: str, delay: float = 0.5) -> int:
    """Antal direkta artiklar i kategorin (ns=0)."""
    url = (f"https://{lang}.wikipedia.org/w/api.php"
           f"?action=query&list=categorymembers"
           f"&cmtitle={urllib.parse.quote(cat_title)}&cmtype=page&cmlimit=10&format=json")
    raw = http_get(url, delay=delay)
    if not raw:
        return 0
    data = json.loads(raw)
    return len(data.get("query", {}).get("categorymembers", []))


def run_discover(delay: float = 1.5) -> dict:
    """
    Genomsöker alla aktiva Wikipedia-utgåvor.
    Returnerar och sparar {lang: cat_title} för alla med träff.
    """
    # Ladda befintliga resultat om de finns
    existing: dict = {}
    if DISCOVERED_FILE.exists():
        existing = json.loads(DISCOVERED_FILE.read_text())
        print(f"  Laddar befintliga resultat: {len(existing)} språk klara")

    wikis = get_all_wikis()
    print(f"  Aktiva Wikipedia-utgåvor: {len(wikis)}")
    print(f"  Ej undersökta: {len([w for w in wikis if w['lang'] not in existing])}")
    print()

    found = dict(existing)
    checked = 0

    for wiki in wikis:
        lang = wiki["lang"]
        if lang in existing:
            continue  # Redan undersökt
        if lang == "en":
            found["en"] = "Category:UFO sightings"
            continue

        checked += 1
        cat = search_uap_category(lang, delay=delay)
        if cat:
            print(f"  [{checked}] {lang} ({wiki['name']}): HITTAD — {cat}")
            found[lang] = cat
        else:
            print(f"  [{checked}] {lang} ({wiki['name']}): —")
            found[lang] = None  # Markera som undersökt, ingen träff

        # Spara efter varje 10:e språk för att kunna återuppta
        if checked % 10 == 0:
            DISCOVERED_FILE.write_text(
                json.dumps(found, indent=2, ensure_ascii=False))
            hits = sum(1 for v in found.values() if v)
            print(f"  --- Sparar ({hits} funna av {len(found)} undersökta) ---")

        time.sleep(delay * 0.2)  # Lite extra paus mellan utgåvor

    DISCOVERED_FILE.write_text(json.dumps(found, indent=2, ensure_ascii=False))
    hits = {k: v for k, v in found.items() if v}
    print(f"\n  Discovery klar: {len(hits)} kategorier funna av {len(found)} undersökta")
    return found


def show_status():
    if not DISCOVERED_FILE.exists():
        print("Ingen discovery-fil hittad. Kör --discover först.")
        return
    data = json.loads(DISCOVERED_FILE.read_text())
    found = {k: v for k, v in data.items() if v}
    missing = [k for k, v in data.items() if v is None]
    unchecked = [k for k, v in data.items() if k not in data]

    print(f"Wikipedia UAP Discovery-status")
    print(f"  Kategorier hittade:  {len(found)}")
    print(f"  Undersökta, tomma:   {len(missing)}")
    print(f"  Ej undersökta:       {len(unchecked)}")
    print()
    print("Hittade kategorier:")
    for lang, cat in sorted(found.items()):
        print(f"  {lang:6s}  {cat}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true",
                    help="Genomsök alla Wikipedia-utgåvor efter UAP-kategorier")
    ap.add_argument("--status", action="store_true",
                    help="Visa discovery-resultat")
    ap.add_argument("--delay", type=float, default=1.5,
                    help="Sekunder mellan API-anrop (default 1.5)")
    args = ap.parse_args()

    if args.status:
        show_status()
    elif args.discover:
        print("=" * 60)
        print("  Wikipedia UAP Discovery — alla utgåvor")
        print("=" * 60)
        run_discover(delay=args.delay)
    else:
        ap.print_help()
