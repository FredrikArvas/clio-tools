"""
uap_web_enrich.py — Datumberika encounters via Wikipedia REST API (alla språkversioner)

Hämtar encounters utan historiskt datum, söker på Wikipedia (engelska + lokal edition
baserad på encounter-landets ISO-kod), extraherar år ur artikelns inledning.
Sätter även koordinater om encounter saknar dem och Wikipedia returnerar coords.

Sökkedja per encounter:
  1. Engelska Wikipedia (direkt slug + sentence-case + OpenSearch)
  2. Lokal Wikipedia-edition (land → ISO → språk → wiki-domain)
     — söker med OpenSearch + UAP-nyckelord på lokalt språk
  3. Returnerar None om inget hittas

Kör: python3 uap_web_enrich.py [--dry-run] [--max N] [--delay 1.0]
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.request, urllib.parse, xmlrpc.client
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = "uapdb"
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

WIKI_SUMMARY_TMPL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}"
WIKI_SEARCH_TMPL  = "https://{lang}.wikipedia.org/w/api.php"
USER_AGENT        = "clio-uap-enrichment/1.0 (contact: research@arvas.international)"

# ---------------------------------------------------------------------------
# Flerspråkig Wikipedia-konfiguration
# ---------------------------------------------------------------------------

# ISO-landskod → Wikipedia-språkkod
COUNTRY_WIKI_LANG: dict[str, str] = {
    # Spanska
    "AR": "es", "ES": "es", "MX": "es", "CL": "es", "CO": "es",
    "PE": "es", "BO": "es", "EC": "es", "UY": "es", "PY": "es",
    "VE": "es", "CU": "es", "DO": "es", "PR": "es", "PA": "es",
    "CR": "es", "HN": "es", "GT": "es", "NI": "es", "SV": "es",
    "GQ": "es",
    # Svenska
    "SE": "sv",
    # Norska (bokmål)
    "NO": "no",
    # Danska
    "DK": "da",
    # Finska
    "FI": "fi",
    # Franska
    "FR": "fr", "BE": "fr", "LU": "fr", "MC": "fr",
    # Tyska
    "DE": "de", "AT": "de", "CH": "de", "LI": "de",
    # Portugisiska
    "BR": "pt", "PT": "pt", "AO": "pt", "MZ": "pt",
    # Italienska
    "IT": "it", "SM": "it", "VA": "it",
    # Holländska
    "NL": "nl",
    # Polska
    "PL": "pl",
    # Ryska
    "RU": "ru", "BY": "ru", "KZ": "ru",
    # Japanska
    "JP": "ja",
    # Kinesiska
    "CN": "zh", "TW": "zh", "HK": "zh",
    # Arabiska
    "EG": "ar", "SA": "ar", "IQ": "ar", "SY": "ar", "JO": "ar",
    "LB": "ar", "LY": "ar", "TN": "ar", "MA": "ar", "DZ": "ar",
    "AE": "ar", "KW": "ar", "QA": "ar", "BH": "ar", "OM": "ar",
    "YE": "ar", "SD": "ar",
    # Turkiska
    "TR": "tr",
    # Grekiska
    "GR": "el",
    # Hebreiska
    "IL": "he",
    # Ungerska
    "HU": "hu",
    # Tjeckiska
    "CZ": "cs",
    # Rumänska
    "RO": "ro",
    # Ukrainska
    "UA": "uk",
    # Kroatiska/Serbiska
    "HR": "hr", "RS": "sr",
    # Slovakiska
    "SK": "sk",
    # Bulgariska
    "BG": "bg",
    # Koreanska
    "KR": "ko",
    # Indonesiska
    "ID": "id",
    # Persiska
    "IR": "fa",
}

# UAP-sökterm per språk (för OpenSearch-frågan)
LANG_UAP_TERM: dict[str, str] = {
    "es": "OVNI",
    "sv": "UFO",
    "no": "UFO",
    "da": "UFO",
    "fi": "UFO",
    "fr": "OVNI",
    "de": "UFO",
    "pt": "OVNI",
    "it": "UFO",
    "nl": "UFO",
    "pl": "UFO",
    "ru": "НЛО",
    "ja": "UFO",
    "zh": "UFO",
    "ar": "UFO",
    "tr": "UFO",
    "el": "UFO",
    "he": "UFO",
    "hu": "UFO",
    "cs": "UFO",
    "ro": "UFO",
    "uk": "НЛО",
    "hr": "UFO",
    "sr": "UFO",
    "sk": "UFO",
    "bg": "НЛО",
    "ko": "UFO",
    "id": "UFO",
    "fa": "UFO",
}

# UAP-nyckelord per språk (relevanscheck på artikeltext)
_UAP_LOCAL: dict[str, re.Pattern] = {
    "es": re.compile(
        r"\b(ovni|objeto volador|platillo volante|avistamiento|fenómeno|"
        r"extraterrestre|abducción|testigos|misterioso|no identificado|"
        r"luces|aparición|aeronave)\b", re.IGNORECASE),
    "sv": re.compile(
        r"\b(ufo|oidentifierat|flygande tefat|iakttagelse|observation|fenomen|"
        r"utomjordisk|rymdskepp|vittnen|mystiska|ljusfenomen|luftfenomen)\b", re.IGNORECASE),
    "no": re.compile(
        r"\b(ufo|uidentifisert|flygende|observasjon|fenomen|utenomjordisk|"
        r"vitner|mystisk|lysf[e]nomen)\b", re.IGNORECASE),
    "da": re.compile(
        r"\b(ufo|uidentificeret|flyvende|observation|f[æe]nomen|"
        r"udenomjordisk|vidner|mystisk)\b", re.IGNORECASE),
    "fi": re.compile(
        r"\b(ufo|tunnistamaton|lentava|havainto|ilmio|ulkomaailmasta|"
        r"todistajat|salaperainen)\b", re.IGNORECASE),
    "fr": re.compile(
        r"\b(ovni|ph[eé]nom[eè]ne|observation|t[eé]moins|extraterrestre|"
        r"soucoupe|lumineux|myst[eé]rieux|non identifi[eé]|a[eé]ronef)\b", re.IGNORECASE),
    "de": re.compile(
        r"\b(ufo|unbekanntes|flugobjekt|fliegende|beobachtung|zeugen|"
        r"außerirdisch|ph[äa]nomen|untertasse|mysteriös|unidentifiziert)\b", re.IGNORECASE),
    "pt": re.compile(
        r"\b(ovni|objeto voador|platinho|avistamento|fen[ôo]meno|"
        r"extraterrestre|abdução|testemunhas|misterioso|n[aã]o identificado)\b", re.IGNORECASE),
    "it": re.compile(
        r"\b(ufo|oggetto volante|avvistamento|fenomeno|extraterrestre|"
        r"testimoni|misterioso|non identificato|disco volante)\b", re.IGNORECASE),
    "nl": re.compile(
        r"\b(ufo|ongeïdentificeerd|vliegende|waarneming|getuigen|"
        r"buitenaards|fenomeen|mysterieus|vliegend object)\b", re.IGNORECASE),
    "pl": re.compile(
        r"\b(ufo|niezidentyfikowany|latający|obserwacja|świadkowie|"
        r"pozaziemski|zjawisko|tajemniczy|latający talerz)\b", re.IGNORECASE),
    "ru": re.compile(
        r"(нло|неопознанный|летающий|наблюдение|свидетели|"
        r"инопланетный|явление|загадочный|тарелка)", re.IGNORECASE),
    "ja": re.compile(r"(UFO|未確認飛行物体|目撃|宇宙人|謎|現象|飛行物体)", re.IGNORECASE),
    "zh": re.compile(r"(UFO|不明飞行物|目击|外星人|神秘|现象|飞碟)", re.IGNORECASE),
    "ar": re.compile(r"(طائرة|ظاهرة|مجهول|شهود|غامض|فضائي|يوفو)", re.IGNORECASE),
    "uk": re.compile(r"(нло|невстановлений|літаючий|спостереження|свідки|позаземний)", re.IGNORECASE),
}

# ---------------------------------------------------------------------------
# Regex-hjälpare
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b")

_BIRTH_CTX_RE = re.compile(
    r"(?:born(?:\s+in)?|b\.)\s*\(?\s*(?:\w+\s+\d+,?\s*)?(\b1[5-9]\d{2}|20[0-2]\d\b)"
    r"|"
    r"\(\s*(1[5-9]\d{2}|20[0-2]\d)\s*[–—-]\s*(?:1[5-9]\d{2}|20[0-2]\d|present)\s*\)",
    re.IGNORECASE,
)

_STRIP_SUFFIX = re.compile(
    r"\s+(incident|case|sighting|encounter|abduction|event|wave|affair|"
    r"ufo|uap|crash|landing|contact|phenomenon|mystery|flap)s?$",
    re.IGNORECASE,
)
_STRIP_PREFIX = re.compile(r"^the\s+", re.IGNORECASE)

# Nyckelord för engelska Wikipedia-artiklar
_UAP_KEYWORDS = re.compile(
    r"\b(ufo|uap|unidentified flying|unidentified aerial|flying saucer|"
    r"flying object|flying disc|flying disk|abduction|close encounter|"
    r"alien|extraterrestrial|spacecraft|anomalous aerial|military observation|"
    r"incident|sighting|encounter|witnesses reported|reported seeing|"
    r"alleged|phenomenon|mysterious light|mysterious object)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Odoo
# ---------------------------------------------------------------------------
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
UID    = common.authenticate(DB, USER, PWD, {})
if not UID:
    sys.exit("Odoo-autentisering misslyckades")
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, kwargs=None):
    return M.execute_kw(DB, UID, PWD, model, method, args, kwargs or {})


# ---------------------------------------------------------------------------
# Wikipedia-sökning (generisk, alla språk)
# ---------------------------------------------------------------------------

def _wiki_fetch(slug: str, lang: str = "en", delay: float = 0.0) -> dict | None:
    """Hämtar Wikipedia summary JSON för en slug på ett givet språk.
    Returnerar None vid 404/403 och nätverkstimeout. Retry vid 5xx/timeout.
    """
    if delay:
        time.sleep(delay)
    url = WIKI_SUMMARY_TMPL.format(
        lang=lang,
        slug=urllib.parse.quote(slug.replace(" ", "_"), safe=""),
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404, 429):
                return None
            if e.code in (500, 502, 503, 504):
                if attempt == 0:
                    time.sleep(5)
                    continue
                print(f"  [WARN] HTTP {e.code} {lang}:{slug!r} — hoppar", flush=True)
                return None
            raise
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            if attempt == 0:
                time.sleep(3)
                continue
            print(f"  [WARN] timeout {lang}:{slug!r}: {e}", flush=True)
            return None
    return None


def _wiki_search(query: str, lang: str = "en", delay: float = 0.0) -> str | None:
    """OpenSearch på valfri Wikipedia-edition. Returnerar första träffens titel."""
    if delay:
        time.sleep(delay)
    params = urllib.parse.urlencode({
        "action":    "opensearch",
        "search":    query,
        "limit":     1,
        "format":    "json",
        "redirects": "resolve",
    })
    url = f"{WIKI_SEARCH_TMPL.format(lang=lang)}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data[1][0] if data[1] else None
    except Exception:
        return None


def _sentence_case(s: str) -> str:
    """'Lead Masks Case' → 'Lead masks case' (Wikipedia är case-sensitive internt)"""
    return (s[0].upper() + s[1:].lower()) if s else s


def _extract_year(text: str) -> int | None:
    """Extraherar det första relevanta historiska året ur en text, hoppar biografi-kontext."""
    if not text:
        return None
    birth_positions: set[int] = set()
    for bm in _BIRTH_CTX_RE.finditer(text):
        birth_positions.add(bm.start())
    for m in _YEAR_RE.finditer(text):
        if any(abs(m.start() - bp) < 30 for bp in birth_positions):
            continue
        y = int(m.group(1))
        if y < 2025:
            return y
    return None


def _make_result(data: dict, slug: str) -> dict:
    """Bygger ett resultatobjekt från ett Wikipedia summary-svar."""
    coords = data.get("coordinates")
    extract = data.get("extract", "")
    return {
        "year":    _extract_year(extract),
        "coords":  (coords["lat"], coords["lon"]) if coords else None,
        "title":   data.get("title", ""),
        "extract": extract[:200],
        "slug":    slug,
    }


# ---------------------------------------------------------------------------
# Engelska Wikipedia-sökning
# ---------------------------------------------------------------------------

def _english_lookup(title: str, req_delay: float) -> dict | None:
    """
    Söker engelska Wikipedia med flera slug-varianter + OpenSearch-fallback.

    Slugg-strategi:
      1. Exakt titel
      2. Prefix-strippad:              "The Lead Masks Case" → "Lead Masks Case"
      3. Prefix-strippad sentence-case: "Lead Masks Case"   → "Lead masks case"
      4. Prefix+suffix-strippad:        → "Lead Masks"
      5. Suffix-strippad sentence-case
      6. + "UFO incident" och + "UFO"
      7. OpenSearch-fallback (fuzzy, case-insensitivt)
    """
    attempts: list[str] = []
    attempts.append(title)

    prefix_only = _STRIP_PREFIX.sub("", title).strip()
    if prefix_only != title:
        attempts.append(prefix_only)
        sc = _sentence_case(prefix_only)
        if sc not in attempts:
            attempts.append(sc)

    clean = _STRIP_SUFFIX.sub("", prefix_only).strip()
    if clean != prefix_only and clean not in attempts:
        attempts.append(clean)
        sc_clean = _sentence_case(clean)
        if sc_clean not in attempts:
            attempts.append(sc_clean)

    if "ufo" not in title.lower() and "uap" not in title.lower():
        attempts.append(clean + " UFO incident")
        attempts.append(title + " UFO")

    for i, attempt in enumerate(attempts):
        data = _wiki_fetch(attempt, lang="en", delay=req_delay if i > 0 else 0.0)
        if not data or data.get("type") == "disambiguation":
            continue
        extract = data.get("extract", "")
        slug_is_specific = (
            "ufo" in attempt.lower()
            or "uap" in attempt.lower()
            or "incident" in attempt.lower()
        )
        if not slug_is_specific and not _UAP_KEYWORDS.search(extract):
            continue
        return _make_result(data, attempt)

    # OpenSearch-fallback
    for search_q in [clean + " UFO", clean, prefix_only]:
        found = _wiki_search(search_q, lang="en", delay=req_delay)
        if found:
            data = _wiki_fetch(found, lang="en", delay=req_delay)
            if data and data.get("type") != "disambiguation":
                extract = data.get("extract", "")
                if _UAP_KEYWORDS.search(extract):
                    return _make_result(data, "en:search:" + found)
            break

    return None


# ---------------------------------------------------------------------------
# Lokal Wikipedia-sökning (land-specifik edition)
# ---------------------------------------------------------------------------

def _local_lookup(title: str, country_code: str, req_delay: float) -> dict | None:
    """
    Söker landets lokala Wikipedia-edition efter encounter-titeln.

    Strategi:
      - OpenSearch med encounter-titeln (engelska namn hittas ofta även i lokala wikis)
      - OpenSearch med titel + lokal UAP-term (OVNI, НЛО, etc.)
      - UAP-relevanscheck med lokalt regexmönster (faller tillbaka på engelska)
      - Relevanscheck är något mjukare här — vi litar mer på att encounter-titeln
        är korrekt klassificerad, och lokala wikis är sällan disambiguerade på UAP-ämnen
    """
    lang = COUNTRY_WIKI_LANG.get(country_code)
    if not lang or lang == "en":
        return None

    uap_term  = LANG_UAP_TERM.get(lang, "UFO")
    uap_re    = _UAP_LOCAL.get(lang, _UAP_KEYWORDS)

    prefix_only = _STRIP_PREFIX.sub("", title).strip()
    clean       = _STRIP_SUFFIX.sub("", prefix_only).strip()

    search_queries = [
        clean + " " + uap_term,   # "Trancas OVNI", "Gotland UFO"
        clean,                     # "Trancas", "Gotland Silver Spheres"
        prefix_only,               # "Trancas Encounter"
    ]
    # Deduplicera utan att tappa ordning
    seen: set[str] = set()
    queries: list[str] = []
    for q in search_queries:
        if q not in seen:
            seen.add(q)
            queries.append(q)

    for q in queries:
        found = _wiki_search(q, lang=lang, delay=req_delay)
        if not found:
            continue

        data = _wiki_fetch(found, lang=lang, delay=req_delay)
        if not data or data.get("type") == "disambiguation":
            continue

        extract = data.get("extract", "")

        # Relevanscheck: lokalt mönster ELLER engelska UAP-nyckelord
        if not uap_re.search(extract) and not _UAP_KEYWORDS.search(extract):
            continue

        result = _make_result(data, f"{lang}:{found}")
        return result

    return None


# ---------------------------------------------------------------------------
# Huvudfunktion: prova engelska → lokal edition
# ---------------------------------------------------------------------------

def wikipedia_lookup(title: str, country_code: str = "",
                     req_delay: float = 1.0) -> dict | None:
    """
    Söker engelska Wikipedia, sedan landets lokala edition.
    Returnerar dict med year, coords, title, extract, slug — eller None.
    """
    result = _english_lookup(title, req_delay)
    if result:
        return result

    if country_code:
        result = _local_lookup(title, country_code, req_delay)
        if result:
            return result

    return None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(max_enc: int, delay: float, dry_run: bool):
    print(f"\n{'='*60}")
    print(f"  Wikipedia Web Enrichment (multi-lang)  {'[DRY RUN] ' if dry_run else ''}")
    print(f"  Delay: {delay}s per request | Max: {max_enc or 'alla'}")
    print(f"{'='*60}")

    # Hämta landsmappning för lokal Wikipedia
    all_countries = kw("res.country", "search_read", [[]], {"fields": ["id", "code"], "limit": 300})
    country_id_to_iso: dict[int, str] = {c["id"]: c["code"] for c in all_countries}

    # Hämta encounters utan historiskt datum (inkl. country_id)
    all_enc = kw("uap.encounter", "search_read",
                 [[["title_en", "!=", False]]],
                 {"fields": ["id", "title_en", "date_observed", "geo_lat", "geo_lng",
                             "research_notes", "country_id"],
                  "limit": 5000})

    candidates = []
    for enc in all_enc:
        d = enc.get("date_observed")
        if d:
            try:
                if datetime.fromisoformat(str(d)).year < 2025:
                    continue
            except Exception:
                pass
        title = enc.get("title_en") or ""
        # Skippa organisationer och testimonier
        if any(kw_skip in title for kw_skip in [
            "Association", "Organization", "Group", "Committee",
            "Testimony", "Statement", "Hearing", "Congress",
            "Ministry", "Agency", "Bureau", "Institute",
        ]):
            continue
        # Skippa databas-ID-titlar (GEIPAN-YYYY-MM-NNNNN etc.)
        if re.match(r"^(GEIPAN|NUFORC)-[\w/-]+$", title):
            continue
        # Skippa podcast/YouTube-titlar
        if " | " in title or (len(title) > 90 and ":" in title):
            continue
        candidates.append(enc)

    print(f"  Candidates: {len(candidates)} encounters utan historiskt datum")
    # Visa språkfördelning
    lang_counts: dict[str, int] = {}
    for enc in candidates:
        c = enc.get("country_id")
        cid = c[0] if c else None
        iso = country_id_to_iso.get(cid, "") if cid else ""
        lang = COUNTRY_WIKI_LANG.get(iso, "en") if iso else "en"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    top_langs = sorted(lang_counts.items(), key=lambda x: -x[1])[:8]
    print(f"  Lokal-wiki fördelning: " + " | ".join(f"{l}:{n}" for l, n in top_langs))

    if max_enc:
        candidates = candidates[:max_enc]
        print(f"  Begränsat till {max_enc}")

    wiki_hits = local_hits = coord_hits = no_result = errors = 0
    t0 = time.time()

    for i, enc in enumerate(candidates, 1):
        title = enc.get("title_en") or ""
        has_coords = (enc.get("geo_lat") or 0.0) != 0.0

        # Hämta landsinfo
        c = enc.get("country_id")
        cid = c[0] if c else None
        country_code = country_id_to_iso.get(cid, "") if cid else ""

        result = wikipedia_lookup(title, country_code=country_code, req_delay=delay)

        if not result or not result["year"]:
            no_result += 1
            if i % 100 == 0:
                print(f"  [{i}/{len(candidates)}] ingen träff | "
                      f"en={wiki_hits} local={local_hits} coords={coord_hits} no={no_result}",
                      flush=True)
            continue

        year     = result["year"]
        date_str = f"{year}-01-01 00:00:00"
        coords   = result["coords"]
        is_local = result["slug"].startswith(("es:", "sv:", "fr:", "de:", "pt:", "it:",
                                               "nl:", "pl:", "ru:", "ja:", "zh:", "ar:",
                                               "no:", "da:", "fi:", "tr:", "el:", "he:",
                                               "hu:", "cs:", "ro:", "uk:", "hr:", "sr:",
                                               "sk:", "bg:", "ko:", "id:", "fa:"))

        update_vals: dict = {"date_observed": date_str}

        if not has_coords and coords:
            update_vals["geo_lat"] = coords[0]
            update_vals["geo_lng"] = coords[1]
            coord_hits += 1

        notes = enc.get("research_notes") or ""
        tag   = f"[DATE_SRC] Wikipedia({result['slug'].split(':')[0] if ':' in result['slug'] else 'en'}) — {result['title']} ({year})"
        if tag not in notes:
            update_vals["research_notes"] = (notes + "\n" + tag).strip()

        if dry_run:
            lang_tag = result["slug"].split(":")[0] if ":" in result["slug"] else "en"
            print(f"  [DRY] {title[:55]!r}")
            print(f"         → {year} [{lang_tag}] | {result['title']!r}")
            if coords and not has_coords:
                print(f"         + coords: {coords[0]:.4f}, {coords[1]:.4f}")
            if is_local:
                local_hits += 1
            else:
                wiki_hits += 1
        else:
            try:
                kw("uap.encounter", "write", [[enc["id"]], update_vals])
                if is_local:
                    local_hits += 1
                else:
                    wiki_hits += 1
                if i % 20 == 0:
                    elapsed = time.time() - t0
                    rate    = i / elapsed
                    eta     = (len(candidates) - i) / rate if rate > 0 else 0
                    print(f"  [{i}/{len(candidates)}] en={wiki_hits} local={local_hits} "
                          f"coords={coord_hits} no={no_result} | "
                          f"{rate:.1f}/s | ETA {eta/60:.1f}min", flush=True)
            except Exception as e:
                print(f"  FEL {enc['id']}: {e}", flush=True)
                errors += 1

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Engelska Wikipedia-träffar : {wiki_hits}")
    print(f"  Lokala Wikipedia-träffar   : {local_hits}")
    print(f"  Koordinater satta          : {coord_hits}")
    print(f"  Ingen träff                : {no_result}")
    print(f"  Fel                        : {errors}")
    print(f"  Tid                        : {elapsed:.1f}s")

    if not dry_run:
        dated = kw("uap.encounter", "search_count", [[["date_observed", "!=", False]]])
        total = kw("uap.encounter", "search_count", [[]])
        print(f"  Encounters med datum: {dated}/{total} ({dated*100//total}%)")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Beriker UAP-encounters med datum/koordinater från Wikipedia (alla språk)"
    )
    ap.add_argument("--dry-run", action="store_true", help="Skriv ej till Odoo")
    ap.add_argument("--max",     type=int, default=0,  help="Max antal encounters att processa")
    ap.add_argument("--delay",   type=float, default=1.0,
                    help="Sekunder mellan Wikipedia-anrop (default 1.0; respekterar Wikipedias policy)")
    args = ap.parse_args()

    if args.dry_run:
        print("*** DRY RUN ***")

    run(args.max, args.delay, args.dry_run)
