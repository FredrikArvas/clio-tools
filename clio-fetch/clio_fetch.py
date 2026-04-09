"""
clio_fetch.py  –  Clio Tools | Steg 1: Webbhämtning
=====================================================
Hämtar en eller flera webbsidor och sparar rengjord
text + metadata till JSON.

Användning
----------
  # Enstaka live URL
  python clio_fetch.py --url https://gtff.se

  # Rekursiv live-crawl (samma domän)
  python clio_fetch.py --url https://gtff.se --recursive

  # Enstaka lokal HTML-fil (HTTrack)
  python clio_fetch.py --file /sökväg/till/index.html

  # Hela HTTrack-mapp rekursivt
  python clio_fetch.py --dir C:/www/gtff.se

  # Valfri output-mapp (standard: ./output)
  python clio_fetch.py --dir C:/www/gtff.se --out ./clio_data

  # Playwright-motor (JS-renderade sidor)
  python clio_fetch.py --url https://example.com --engine playwright
  python clio_fetch.py --url https://example.com --engine playwright --recursive

  # Städa en HTTrack-mapp (flytta skräp till papperskorgen)
  python clio_fetch.py --clean C:/www/gtff.se
  python clio_fetch.py --clean C:/www/gtff.se --dry-run

Namnstandard för JSON-filer
---------------------------
  Live URL:   gtff.se_om-oss_index_20260402_120000.json
  Lokal fil:  gtff.se_om-oss_index_20260402_120000.json
  (domän + relativ sökväg, / ersätts med _)

Beroenden
---------
  pip install requests beautifulsoup4 lxml
  pip install send2trash   # krävs för --clean
  pip install playwright && playwright install chromium  # krävs för --engine playwright
"""

import argparse
import json
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse


# ── Försöker importera beroenden med tydliga felmeddelanden ──────────────────

try:
    import requests
except ImportError:
    sys.exit("Saknar 'requests'. Kör: pip install requests")

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Saknar 'beautifulsoup4'. Kör: pip install beautifulsoup4 lxml")

try:
    import chardet
    _HAVE_CHARDET = True
except ImportError:
    _HAVE_CHARDET = False

try:
    import send2trash
    _HAVE_SEND2TRASH = True
except ImportError:
    _HAVE_SEND2TRASH = False

try:
    from playwright.sync_api import sync_playwright
    _HAVE_PLAYWRIGHT = True
except ImportError:
    _HAVE_PLAYWRIGHT = False


# ── Konstanter ───────────────────────────────────────────────────────────────

__version__ = "1.1.0"

# Tröskel för vad som räknas som en "tom" HTML-fil (bytes)
EMPTY_HTML_THRESHOLD = 500


# HTML-element som oftast innehåller navigation/reklam/skript – tas bort
NOISE_TAGS = [
    "script", "style", "noscript",
    "nav", "header", "footer",
    "aside", "form", "button",
    "iframe", "svg", "img",
]

REQUEST_TIMEOUT = 15  # sekunder
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ClioTools/1.0; "
        "+https://arvas.international)"
    )
}
CRAWL_DELAY = 1.0   # sekunder mellan requests vid rekursiv crawl
HTML_EXTS   = {".html", ".htm"}


# ── Namngivning och filtrering ────────────────────────────────────────────────

# Segment i sökvägen som aldrig innehåller användbart innehåll
_SKIP_SEGMENTS = {"feed", "wp-json", "wp-content", "comments"}
_HEX_FILE_RE   = re.compile(r"^index[0-9a-f]{4}\.html?$", re.I)
_PAGE_RE        = re.compile(r"/page/\d+")


def should_skip(rel_path: str) -> tuple[bool, str]:
    """
    Returnerar (True, anledning) om filen ska hoppas över,
    annars (False, "").
    """
    parts    = Path(rel_path).parts
    path_str = "/".join(parts)

    # HTTracks redirect-filer med hexkod i root
    if len(parts) == 1 and _HEX_FILE_RE.match(parts[0]):
        return True, "redirect-hex"

    # E-postadress har smugit sig in som filnamn
    if "@" in path_str:
        return True, "e-post"

    # Kända skräp-segment
    for seg in parts:
        if seg in _SKIP_SEGMENTS:
            return True, f"segment:{seg}"

    # Paginering: /page/N var som helst i sökvägen
    if _PAGE_RE.search("/" + path_str):
        return True, "paginering"

    return False, ""


def make_slug(source: str, base_url: str = "", base_dir: Path = None) -> str:
    """
    Bygger ett läsbart filnamn-slug som speglar originalstrukturen.
    WordPress-medveten: tar bort 'index.php'-segmentet och
    slår ihop datum-segment YYYY/MM/DD → YYYY-MM-DD.

    Exempel (lokal, base_dir = .../gtff.se/gtff.se):
      index.php/om-gtff/stadgar/index.html      → gtff.se_om-gtff_stadgar
      index.php/2017/01/04/nya-hemsidan/index.html → gtff.se_2017-01-04_nya-hemsidan
      index.html                                → gtff.se
    """
    if source.startswith("http"):
        parsed = urlparse(source)
        domain = parsed.netloc
        path   = parsed.path.strip("/")
        segs   = [s for s in path.split("/") if s]
        # Ta bort index.php om det är första segmentet
        if segs and segs[0].lower() == "index.php":
            segs = segs[1:]
        path = "/".join(segs)
    else:
        p  = Path(source)
        bd = Path(base_dir) if base_dir else p.parent
        domain = bd.name                          # mappnamnet = domänen
        try:
            rel = p.relative_to(bd)
        except ValueError:
            rel = p
        segs = list(rel.parts)
        if segs and segs[0].lower() == "index.php":
            segs = segs[1:]
        path = "/".join(segs)

    # Filändelse
    path = re.sub(r"\.html?$", "", path)
    # Datum YYYY/MM/DD → YYYY-MM-DD_
    path = re.sub(r"(\d{4})/(\d{2})/(\d{2})/", r"\1-\2-\3_", path)
    # Avslutande /index (redundant)
    path = re.sub(r"(/index)+$", "", path)
    path = re.sub(r"^index$", "", path)

    segments = [s for s in path.split("/") if s]
    parts    = ([domain] + segments) if domain else segments
    return "_".join(parts) or domain


# ── Källhantering ─────────────────────────────────────────────────────────────

def fetch_url(url: str) -> tuple[str, str]:
    """Hämtar HTML från en live URL. Returnerar (html, url)."""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return resp.text, url
    except requests.exceptions.Timeout:
        print(f"  [varning] Timeout: {url} – hoppas över")
        return "", url
    except requests.exceptions.HTTPError as e:
        print(f"  [varning] HTTP-fel {e}: {url} – hoppas över")
        return "", url
    except requests.exceptions.RequestException as e:
        print(f"  [varning] Nätverksfel {e}: {url} – hoppas över")
        return "", url


def fetch_url_playwright(url: str) -> tuple[str, str]:
    """Hämtar fullt renderad HTML via Playwright (Chromium headless)."""
    if not _HAVE_PLAYWRIGHT:
        sys.exit(
            "Saknar 'playwright'. Kör: pip install playwright && playwright install chromium"
        )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=REQUEST_HEADERS["User-Agent"])
        try:
            page.goto(url, timeout=REQUEST_TIMEOUT * 1000, wait_until="networkidle")
            html = page.content()
        except Exception as e:
            print(f"  [varning] Playwright-fel: {e} – hoppas över")
            html = ""
        finally:
            browser.close()
    return html, url


def crawl_url(start_url: str, fetch_fn=None) -> list[tuple[str, str]]:
    """
    Rekursiv BFS-crawl inom samma domän som start_url.
    Returnerar lista av (html, url) för varje unik sida.
    Respekterar CRAWL_DELAY mellan requests.
    """
    if fetch_fn is None:
        fetch_fn = fetch_url

    domain  = urlparse(start_url).netloc
    visited = set()
    queue   = deque([start_url])
    results = []

    print(f"[clio] Rekursiv crawl: {start_url}")
    while queue:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        print(f"  → {url}")
        html, src = fetch_fn(url)
        if not html:
            continue

        results.append((html, src))

        # Hitta länkar på samma domän
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full = urljoin(url, href)
            parsed = urlparse(full)
            # Bara samma domän, bara http/https, inga ankare/parametrar
            if (parsed.netloc == domain
                    and parsed.scheme in {"http", "https"}
                    and full not in visited
                    and parsed.fragment == ""
                    and not re.search(r"\.(pdf|jpg|png|gif|zip|doc|docx)$",
                                      parsed.path, re.I)):
                queue.append(full._replace(query="", fragment="").geturl()
                             if hasattr(full, "_replace") else
                             parsed._replace(query="", fragment="").geturl())

        time.sleep(CRAWL_DELAY)

    print(f"[clio] Crawl klar – {len(results)} sidor hämtade")
    return results


def _read_file(path: Path) -> str:
    """
    Läser en HTML-fil med korrekt encoding.
    Prioritet: meta charset i HTML > chardet > latin-1 fallback.
    Hanterar filer som deklarerar utf-8 men är sparade som latin-1 (HTTrack-quirk).
    """
    raw = path.read_bytes()

    # Kolla meta charset i de första 2 KB
    snippet = raw[:2048].decode("ascii", errors="replace")
    m = re.search(r'charset=["\']?([\w-]+)', snippet, re.I)
    if m:
        declared = m.group(1).lower()
        if declared in {"utf-8", "utf8"}:
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                pass  # filen ljuger om sin encoding
        else:
            try:
                return raw.decode(declared, errors="replace")
            except (LookupError, UnicodeDecodeError):
                pass

    # chardet som andra försök
    if _HAVE_CHARDET:
        detected = chardet.detect(raw[:50000])
        enc = detected.get("encoding") or "latin-1"
        try:
            return raw.decode(enc, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass

    return raw.decode("latin-1", errors="replace")


def load_html(path: str) -> tuple[str, str]:
    """Läser en lokal HTML-fil. Returnerar (html, absolut sökväg)."""
    p = Path(path).resolve()
    if not p.exists():
        sys.exit(f"[fel] Filen hittades inte: {p}")
    if p.suffix.lower() not in HTML_EXTS:
        print(f"[varning] Oväntat filformat: {p.suffix} – fortsätter ändå.")
    return _read_file(p), str(p)


def load_dir(directory: str) -> tuple[list[tuple[str, str]], Path]:
    """
    Läser alla relevanta HTML-filer rekursivt i en HTTrack-mapp.
    Filtrerar bort redirects, paginering, wp-content m.m.
    Returnerar (lista av (html, absolut sökväg), base_dir).
    base_dir = mappen du pekar på (t.ex. .../gtff.se/gtff.se).
    """
    base = Path(directory).resolve()
    if not base.exists():
        sys.exit(f"[fel] Mappen hittades inte: {base}")

    all_files = sorted(
        p for ext in HTML_EXTS for p in base.rglob(f"*{ext}")
    )

    kept    = []
    skipped = 0
    skip_reasons: dict[str, int] = {}

    for f in all_files:
        try:
            rel = str(f.relative_to(base))
        except ValueError:
            rel = f.name

        skip, reason = should_skip(rel)
        if skip:
            skipped += 1
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue

        if f.name.lower().startswith("hts-"):
            skipped += 1
            continue

        html = _read_file(f)

        if 'http-equiv="refresh"' in html.lower() or "http-equiv='refresh'" in html.lower():
            skipped += 1
            skip_reasons["meta-refresh"] = skip_reasons.get("meta-refresh", 0) + 1
            continue

        kept.append((html, str(f)))

    print(f"[clio] Läser mapp  : {base}")
    print(f"       Hittade     : {len(all_files)} HTML-filer")
    reasons_str = ", ".join(f"{v}× {k}" for k, v in sorted(skip_reasons.items()))
    print(f"       Filtrerade  : {skipped} ({reasons_str})")
    print(f"       Bearbetar   : {len(kept)} filer")

    return kept, base


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse(html: str, source: str) -> dict:
    """
    Rensar HTML och extraherar:
      - title      : sidans <title>
      - description: meta description om den finns
      - text       : rengjord löptext
      - word_count : antal ord i texten
      - source     : URL eller filsökväg
      - fetched_at : ISO 8601-tidsstämpel (UTC)
    """
    soup = BeautifulSoup(html, "lxml")

    # Titel
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Meta description
    desc_tag = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
    description = ""
    if desc_tag and desc_tag.get("content"):
        description = desc_tag["content"].strip()

    # Ta bort brus
    for tag in soup(NOISE_TAGS):
        tag.decompose()

    # Extrahera text från <main> om det finns, annars <body>
    container = soup.find("main") or soup.find("body") or soup
    raw_text = container.get_text(separator="\n")

    # Normalisera whitespace
    lines = [line.strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]          # ta bort tomrader
    text = "\n".join(lines)

    # Rensa upprepade blankrader som kan ha smugit sig in
    text = re.sub(r"\n{3,}", "\n\n", text)

    word_count = len(text.split())

    return {
        "title": title,
        "description": description,
        "text": text,
        "word_count": word_count,
        "source": source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Spara ─────────────────────────────────────────────────────────────────────

def save(data: dict, out_dir: str, slug: str) -> Path:
    """
    Sparar data som JSON.
    Filnamn: <slug>_<YYYYMMDD_HHMMSS>.json
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanera slug – ta bort tecken som är ogiltiga i filnamn
    safe_slug = re.sub(r'[<>:"/\\|?*]', "_", slug)
    filename  = f"{safe_slug}_{timestamp}.json"
    full_path = out_path / filename

    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return full_path


def process_one(html: str, source: str, out_dir: str,
                base_url: str = "", base_dir: Path = None) -> dict | None:
    """Parsar en HTML-sida och sparar JSON. Returnerar data eller None."""
    if not html:
        return None
    data  = parse(html, source)
    slug  = make_slug(source, base_url=base_url, base_dir=base_dir)
    saved = save(data, out_dir, slug)
    return {"data": data, "saved": saved}


# ── Städning av HTTrack-kataloger ────────────────────────────────────────────

# Filnamn som alltid är HTTrack-metadata (case-insensitivt)
_HTTRACK_FILES = {"hts-log.txt", "cookies.txt", "backblue.gif", "fade.gif"}
# Kataloger som alltid är HTTrack-metadata
_HTTRACK_DIRS = {"hts-cache"}
# Sökvägssegment vars innehåll alltid är WordPress API-skräp
_WP_JUNK_SEGMENTS = {"wp-json"}
# Stilar och script
_ASSET_EXTS = {".css", ".js"}


def _fmt_size(n_bytes: int) -> str:
    """Formaterar ett antal bytes som läsbar sträng (B/kB/MB)."""
    if n_bytes < 1024:
        return f"{n_bytes} B"
    if n_bytes < 1024 * 1024:
        return f"{n_bytes / 1024:.0f} kB"
    return f"{n_bytes / (1024 * 1024):.1f} MB"


def _classify_file(path: Path, root: Path) -> str | None:
    """
    Returnerar kategorinamn för filen, eller None om den ska bevaras.
    Ordning: httrack → empty_html → assets → other
    Bilder bevaras alltid (returnerar None).
    """
    name  = path.name.lower()
    ext   = path.suffix.lower()
    parts = {p.lower() for p in path.parts}

    # HTTrack-metadata: kända filnamn
    if name in _HTTRACK_FILES:
        return "httrack"

    # HTTrack .orig-filer (backup av överskrivna filer)
    if ext == ".orig":
        return "httrack"

    # HTTrack .z-filer (gzip-komprimerad cache)
    if ext == ".z":
        return "httrack"

    # WordPress API-sökvägar (wp-json, oembed etc.)
    if parts & _WP_JUNK_SEGMENTS:
        return "httrack"

    # HTTrack-metadata: rotkatalogs index.html med HTTrack-signatur
    if name == "index.html" and path.parent.resolve() == root:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            if "httrack" in content.lower() or "mirrored by" in content.lower():
                return "httrack"
        except OSError:
            pass

    # Tomma HTML-filer
    if ext in {".html", ".htm"}:
        try:
            if path.stat().st_size < EMPTY_HTML_THRESHOLD:
                return "empty_html"
        except OSError:
            pass
        return None  # Bevarad HTML-fil

    # Bilder och dokument bevaras alltid
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
               ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm",
               ".ppt", ".pptx"}:
        return None

    # Stilar och script
    if ext in _ASSET_EXTS:
        return "assets"

    # Övrigt (allt som inte är .html/.htm eller bild)
    return "other"


def clean(start_dir: str | Path, dry_run: bool = False) -> None:
    """
    Städar en HTTrack-hämtad katalog interaktivt.

    Kategoriserar alla filer, visar en sammanfattning per kategori och
    frågar om varje kategori ska flyttas till papperskorgen.
    Ingenting raderas permanent – send2trash används genomgående.

    Args:
        start_dir: Rotkatalogen för HTTrack-nedladdningen.
        dry_run:   Om True visas vad som skulle hända utan att flytta något.
    """
    if not _HAVE_SEND2TRASH:
        sys.exit(
            "[fel] 'send2trash' saknas. Kör: pip install send2trash"
        )

    root = Path(start_dir).resolve()
    if not root.exists():
        sys.exit(f"[fel] Mappen hittades inte: {root}")

    # ── Scanna och klassificera ───────────────────────────────────────────────
    categories: dict[str, list[Path]] = {
        "httrack":    [],
        "empty_html": [],
        "assets":     [],
        "other":      [],
    }
    category_labels = {
        "httrack":    "HTTrack-metadata (hts-*, *.orig, *.z, wp-json, …)",
        "empty_html": f"Tomma HTML-filer (< {EMPTY_HTML_THRESHOLD} B)",
        "assets":     "Stilar och script (.css/.js)",
        "other":      "Övrigt (ej .html, bild eller dokument)",
    }

    # Inkludera också katalogen hts-cache (läggs till som ett enda objekt)
    hts_cache = root / "hts-cache"

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # Filer inuti hts-cache räknas via katalogen nedan
        if hts_cache.exists() and path.is_relative_to(hts_cache):
            continue
        cat = _classify_file(path, root)
        if cat is not None:
            categories[cat].append(path)

    # Lägg till hts-cache-katalogen som ett enda "objekt" i httrack-listan
    if hts_cache.exists():
        categories["httrack"].insert(0, hts_cache)

    # ── Sammanfattning ────────────────────────────────────────────────────────
    label_w = max(len(v) for v in category_labels.values()) + 2

    if dry_run:
        print("\n[clio-clean] DRY-RUN – inga filer flyttas\n")
    else:
        print()

    print(f"[clio-clean] Katalog: {root}\n")

    has_files = False
    for cat, files in categories.items():
        if not files:
            continue
        has_files = True
        total_size = sum(
            p.stat().st_size for p in files if p.is_file()
        )
        label = category_labels[cat]
        count_str = f"{len(files)} objekt"
        size_str  = _fmt_size(total_size)
        print(f"  [{cat:<10}]  {label:<{label_w}}  {count_str:>10}  {size_str:>8}")

    if not has_files:
        print("  Inga filer att städa.")
        return

    # ── Interaktiv bekräftelse per kategori ──────────────────────────────────
    print()
    total_trashed = 0
    PREVIEW_LIMIT = 20

    for cat, files in categories.items():
        if not files:
            continue

        label = category_labels[cat]
        print(f"  [{cat}] {label}")

        # Visa upp till 20 filer (relativ sökväg från root)
        for p in files[:PREVIEW_LIMIT]:
            try:
                rel = p.relative_to(root)
            except ValueError:
                rel = p
            print(f"    {rel}")
        if len(files) > PREVIEW_LIMIT:
            print(f"    ... och {len(files) - PREVIEW_LIMIT} till")

        if dry_run:
            prompt = f"  >> [dry-run] Flytta till papperskorgen? [y/N] "
        else:
            prompt = f"  >> Flytta till papperskorgen? [y/N] "

        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n[clio-clean] Avbruten.")
            return

        print()

        if answer != "y":
            continue

        if dry_run:
            total_trashed += len(files)
            print(f"    (dry-run) {len(files)} objekt SKULLE ha flyttats.\n")
        else:
            moved = 0
            for p in files:
                try:
                    send2trash.send2trash(str(p))
                    moved += 1
                except Exception as e:
                    print(f"    [varning] Kunde inte flytta {p.name}: {e}")
            total_trashed += moved
            print(f"    ✓ {moved} objekt skickade till papperskorgen.\n")

    # ── Avslutning ────────────────────────────────────────────────────────────
    print()
    if dry_run:
        print(f"[clio-clean] Dry-run klar. {total_trashed} objekt SKULLE ha flyttats.")
    else:
        print(f"[clio-clean] Klar. {total_trashed} objekt skickade till papperskorgen.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    # Säkerställ UTF-8 på Windows-terminaler (CP1252 klarar inte t.ex. ✓)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) == 1:
        print(__doc__)
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Clio Tools – Webbhämtning MVP"
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--url", metavar="URL",
        help="Live URL, t.ex. https://gtff.se"
    )
    source_group.add_argument(
        "--file", metavar="SÖKVÄG",
        help="Enstaka lokal HTML-fil från HTTrack"
    )
    source_group.add_argument(
        "--dir", metavar="MAPP",
        help="HTTrack-mapp – alla HTML-filer läses rekursivt"
    )
    source_group.add_argument(
        "--clean", metavar="MAPP",
        help="Städa en HTTrack-mapp – flytta skräp till papperskorgen"
    )
    parser.add_argument(
        "--recursive", action="store_true",
        help="Crawla rekursivt vid --url (följer länkar på samma domän)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Visa vad --clean SKULLE göra utan att flytta något"
    )
    parser.add_argument(
        "--out", metavar="MAPP", default="./output",
        help="Output-mapp för JSON-filer (standard: ./output)"
    )
    parser.add_argument(
        "--engine", choices=["requests", "playwright"], default="requests",
        help="Scraping-motor: 'requests' (standard) eller 'playwright' (JS-sidor)"
    )
    args = parser.parse_args()

    if args.engine == "playwright" and not args.url:
        parser.error("--engine playwright kräver --url (fungerar inte med --file, --dir eller --clean)")

    results = []

    if args.url:
        _fetch = fetch_url_playwright if args.engine == "playwright" else fetch_url
        if args.engine == "playwright":
            print(f"[clio] Motor: Playwright (Chromium headless)")
        if args.recursive:
            pages = crawl_url(args.url, fetch_fn=_fetch)
            base_url = args.url
            for html, src in pages:
                r = process_one(html, src, args.out, base_url=base_url)
                if r:
                    results.append(r)
        else:
            print(f"[clio] Hämtar: {args.url}")
            html, src = _fetch(args.url)
            r = process_one(html, src, args.out, base_url=args.url)
            if r:
                results.append(r)

    elif args.file:
        print(f"[clio] Läser fil: {args.file}")
        html, src = load_html(args.file)
        # base_dir = förälder till filen för bästa möjliga slug
        base_dir = Path(args.file).resolve().parent.parent
        r = process_one(html, src, args.out, base_dir=base_dir)
        if r:
            results.append(r)

    elif args.dir:
        pages, base_dir = load_dir(args.dir)
        for html, src in pages:
            r = process_one(html, src, args.out, base_dir=base_dir)
            if r:
                results.append(r)

    elif args.clean:
        clean(args.clean, dry_run=args.dry_run)
        return

    # ── Sammanfattning ────────────────────────────────────────────────────────
    print(f"\n[clio] ✓ Klar! {len(results)} fil(er) sparade i {args.out}")
    if len(results) == 1:
        d = results[0]
        print(f"       Titel      : {d['data']['title'] or '(ingen)'}")
        print(f"       Ordräkning : {d['data']['word_count']:,}")
        print(f"       Sparad till: {d['saved']}")
    elif results:
        total_words = sum(r["data"]["word_count"] for r in results)
        print(f"       Totalt ord : {total_words:,}")
        print(f"       Exempel    : {results[0]['saved'].name}")


if __name__ == "__main__":
    main()
