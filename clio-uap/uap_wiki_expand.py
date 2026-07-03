"""
uap_wiki_expand.py — Expansiv Wikipedia UAP-insamling

Lägen:
  --subcats     Traverserar subkategorier (djup 3) i 36 funna Wikipedia-utgåvor
  --uap-terms   Söker UAP/PANI som alternativa kategorinamn
  --lists       Parsar lista-artiklar ("List of UFO sightings" m.fl.)
  --wikidata       Hämtar alla Q40728071-instanser via Wikidata SPARQL
  --country-lists  Parsar per-land-artiklar (UFO sightings in X) på Wikipedia
  --films          Importerar UAP-relaterade filmer som encounter_class=5

Dedup-lager:
  L1: encounter_id = WIKI-{lang}-{slug}  — exakt match mot Odoo
  L2: [QID] {qid} i research_notes       — kopplar sitelinks över språk
  L3: titel-softmatch (--lists only)      — flaggar kandidater

Kör:
  python3 uap_wiki_expand.py --subcats [--dry-run] [--lang sv,en,fr]
  python3 uap_wiki_expand.py --uap-terms [--dry-run]
  python3 uap_wiki_expand.py --lists [--dry-run]
  python3 uap_wiki_expand.py --wikidata [--dry-run]
  python3 uap_wiki_expand.py --country-lists [--dry-run]
  python3 uap_wiki_expand.py --films [--dry-run]
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, unicodedata, urllib.request, urllib.parse
import xmlrpc.client
from hashlib import sha256
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
BASE_DIR  = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8079")
ODOO_DB  = os.getenv("ODOO_DB",  "uap")
ODOO_USER = os.getenv("ODOO_USER", "")
ODOO_PWD  = os.getenv("ODOO_PASSWORD", "")

UA = "Mozilla/5.0 clio-uap-research/1.0 (contact: research@arvas.international)"
WIKI_API     = "https://{lang}.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}"

DISCOVERED_FILE = BASE_DIR / "wiki_discovered_cats.json"
EXPAND_LOG      = BASE_DIR / "wiki_expand_log.json"
SUBCATS_STATE   = BASE_DIR / ".subcats_state.json"

MAX_SUBCAT_DEPTH = 3
API_DELAY        = 1.2
WIKIDATA_DELAY   = 2.0

BLOCKLIST = [
    "album", "discography", "members", "songs", "music", "band",
    "film", "manga", "anime", "novel", "game", "fiction",
    "mitglied", "musikgruppe",
    "panier", "basket", "corbeille", "cestino", "cesta",
]

VALID_LANG_FIELD = {"en", "sv", "pt", "es", "fr", "de", "ja"}

def lang_field(lang: str) -> str:
    return lang if lang in VALID_LANG_FIELD else "other"

UAP_REQUIRED_IN_CAT = [
    "ufo", "ovni", "nlo", "нло", "uap", "飞行物", "비행",
    "ufologi", "pani", "phenomena", "phénomène", "sighting",
    "observation", "avistamiento", "avvistamento", "müşahidə",
]

def is_uap_category(title: str) -> bool:
    tl = title.lower()
    return any(kw in tl for kw in UAP_REQUIRED_IN_CAT)

UAP_EXPANDED_TERMS: dict[str, list[str]] = {
    "en": ["Unidentified aerial phenomena", "UAP sightings", "UFO sightings"],
    "fr": ["phénomène aérien non identifié", "observation OVNI", "OVNI"],
    "ja": ["未確認航空現象", "UAP"],
    "zh": ["不明飛行物", "不明飞行物"],
    "pt": ["fenômeno aéreo não identificado", "OVNI"],
    "de": ["unbekannte Flugobjekte", "UAP"],
    "ko": ["미확인비행현상", "UAP"],
    "ru": ["Неопознанное аномальное явление", "НАЯ"],
    "es": ["fenómeno aéreo no identificado", "FANI"],
    "it": ["fenomeno aereo non identificato"],
    "nl": ["ongeïdentificeerd vliegend object"],
    "sv": ["oidentifierade flygande föremål", "UAP"],
}

LIST_ARTICLES: dict[str, str] = {
    "en": "List of reported UFO sightings",
    "fr": "Liste d'observations d'OVNI",
    "es": "Anexo:Avistamientos de OVNI",
    "de": "Liste von UFO-Sichtungen",
    "pt": "Lista de avistamentos de OVNIs",
    "ja": "UFO目撃例の一覧",
    "ko": "UFO 목격 사례 목록",
    "zh": "不明飞行物目击事件列表",
    "ru": "Список наблюдений НЛО",
    "it": "Lista di avvistamenti di UFO",
    "pl": "Lista obserwacji UFO",
    "ar": "قائمة رصد الأجسام الطائرة المجهولة",
}

# ---------------------------------------------------------------------------
# Odoo
# ---------------------------------------------------------------------------
def _make_odoo():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PWD, {})
    if not uid:
        sys.exit("Odoo-autentisering misslyckades — kontrollera .env")
    M = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)
    return uid, M

def kw(M, uid, model, method, args, kwargs=None):
    return M.execute_kw(ODOO_DB, uid, ODOO_PWD, model, method, args, kwargs or {})

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def http_get(url: str, delay: float = API_DELAY) -> bytes | None:
    if delay:
        time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404, 414):
                return None
            if e.code in (429, 500, 502, 503, 504):
                wait = 30 if e.code == 429 else 10
                if attempt < 2:
                    print(f"  [WARN] HTTP {e.code}, väntar {wait}s…", flush=True)
                    time.sleep(wait)
                    continue
                return None
            return None
        except Exception:
            if attempt < 2:
                time.sleep(5)
                continue
            return None
    return None

def wiki_api(params: dict, lang: str = "en", delay: float = API_DELAY) -> dict | None:
    params.setdefault("format", "json")
    url = WIKI_API.format(lang=lang) + "?" + urllib.parse.urlencode(params)
    raw = http_get(url, delay=delay)
    return json.loads(raw) if raw else None

def wiki_summary(title: str, lang: str = "en", delay: float = API_DELAY) -> dict | None:
    slug = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url  = WIKI_SUMMARY.format(lang=lang, slug=slug)
    raw  = http_get(url, delay=delay)
    if not raw:
        return None
    d = json.loads(raw)
    return d if d.get("type") not in ("disambiguation",) else None

# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b")
_QID_RE  = re.compile(r"\[QID\]\s*(Q\d+)")

def norm_slug(title: str) -> str:
    return unicodedata.normalize("NFC", title.strip().replace(" ", "_"))

def make_eid(lang: str, title: str) -> str:
    return f"WIKI-{lang}-{norm_slug(title)}"

def is_blocked(title: str) -> bool:
    tl = title.lower()
    return any(b in tl for b in BLOCKLIST)

class DeduplicatorL1:
    def __init__(self, M, uid):
        enc = kw(M, uid, "uap.encounter", "search_read",
                 [[["encounter_id", "like", "WIKI-"]]], {"fields": ["encounter_id"], "limit": 200000})
        wd_enc = kw(M, uid, "uap.encounter", "search_read",
                    [[["encounter_id", "like", "WD-"]]], {"fields": ["encounter_id"], "limit": 200000})
        list_enc = kw(M, uid, "uap.encounter", "search_read",
                      [[["encounter_id", "like", "LIST-"]]], {"fields": ["encounter_id"], "limit": 200000})
        film_enc = kw(M, uid, "uap.encounter", "search_read",
                      [[["encounter_id", "like", "FILM-"]]], {"fields": ["encounter_id"], "limit": 200000})
        ctry_enc = kw(M, uid, "uap.encounter", "search_read",
                      [[["encounter_id", "like", "CTRY-"]]], {"fields": ["encounter_id"], "limit": 200000})
        self.known: set[str] = (
            {e["encounter_id"] for e in enc} |
            {e["encounter_id"] for e in wd_enc} |
            {e["encounter_id"] for e in list_enc} |
            {e["encounter_id"] for e in film_enc} |
            {e["encounter_id"] for e in ctry_enc}
        )
        print(f"  L1: {len(self.known)} kända WIKI-/WD-/LIST- encounter_ids inlästa", flush=True)

    def exists(self, eid: str) -> bool:
        return eid in self.known

    def add(self, eid: str):
        self.known.add(eid)

class DeduplicatorL2:
    def __init__(self, M, uid):
        enc = kw(M, uid, "uap.encounter", "search_read",
                 [[["research_notes", "like", "[QID]"]]],
                 {"fields": ["id", "encounter_id", "research_notes"], "limit": 200000})
        self.qid_to: dict[str, dict] = {}
        for e in enc:
            m = _QID_RE.search(e.get("research_notes") or "")
            if m:
                self.qid_to[m.group(1)] = e
        print(f"  L2: {len(self.qid_to)} QID-kopplade encounters", flush=True)

    def get(self, qid: str) -> dict | None:
        return self.qid_to.get(qid)

    def add(self, qid: str, rec: dict):
        self.qid_to[qid] = rec

# ---------------------------------------------------------------------------
# Hjälpare
# ---------------------------------------------------------------------------
def load_country_map(M, uid):
    countries = kw(M, uid, "res.country", "search_read", [[]], {"fields": ["id", "name", "code"], "limit": 300})
    return {c["name"].lower(): c["id"] for c in countries}, {c["code"].upper(): c["id"] for c in countries}

LANG_TO_ISO = {
    "sv": "SE", "fi": "FI", "no": "NO", "da": "DK", "nl": "NL",
    "de": "DE", "fr": "FR", "it": "IT", "es": "ES", "pt": "PT",
    "pl": "PL", "cs": "CZ", "hu": "HU", "ro": "RO", "bg": "BG",
    "hr": "HR", "sk": "SK", "sl": "SI", "sq": "AL", "mk": "MK",
    "sr": "RS", "bs": "BA", "uk": "UA", "ru": "RU", "el": "GR",
    "tr": "TR", "he": "IL", "ar": "SA", "fa": "IR", "ko": "KR",
    "ja": "JP", "zh": "CN", "vi": "VN", "th": "TH", "id": "ID",
    "ms": "MY", "az": "AZ", "ka": "GE", "kk": "KZ", "my": "MM",
}

def resolve_country(lang: str, code_to_id: dict) -> int | None:
    iso = LANG_TO_ISO.get(lang)
    return code_to_id.get(iso) if iso else None

def extract_year(text: str) -> str | None:
    m = _YEAR_RE.search(text or "")
    return m.group(1) if m else None

def get_qid(lang: str, title: str) -> str | None:
    data = wiki_api({
        "action": "query", "titles": title,
        "prop": "pageprops", "ppprop": "wikibase_item",
    }, lang=lang, delay=0.5)
    if not data:
        return None
    for page in data.get("query", {}).get("pages", {}).values():
        return page.get("pageprops", {}).get("wikibase_item")
    return None

def get_cat_members(lang: str, cat: str, cmtype: str = "page") -> list[str]:
    titles = []
    cont: dict = {}
    for _ in range(20):
        params = {"action": "query", "list": "categorymembers",
                  "cmtitle": cat, "cmtype": cmtype, "cmlimit": "500"}
        params.update(cont)
        data = wiki_api(params, lang=lang, delay=API_DELAY)
        if not data:
            break
        titles.extend(m["title"] for m in data.get("query", {}).get("categorymembers", []))
        cont = data.get("continue", {})
        if not cont:
            break
    return titles

def build_vals(lang: str, title: str, summary: dict, qid: str | None,
               country_id: int | None) -> dict:
    extract = summary.get("extract", "")
    year = extract_year(summary.get("description", "") + " " + extract + " " + title)
    notes = []
    if qid:
        notes.append(f"[QID] {qid}")
    notes.append(f"[SRC] Wikipedia:{lang}:{title}")
    url = summary.get("content_urls", {}).get("desktop", {}).get("page", "")
    if url:
        notes.append(f"[URL] {url}")
    vals = {
        "encounter_id":    make_eid(lang, title),
        "title_en":        summary.get("title", title) if lang == "en" else title,
        "title_original":  title if lang != "en" else False,
        "language_original": lang_field(lang) if lang != "en" else False,
        "description_en":  extract[:2000] if extract else False,
        "date_observed":   f"{year}-01-01" if year else False,
        "status":          "pending",
        "research_notes":  "\n".join(notes),
    }
    if country_id:
        vals["country_id"] = country_id
    return vals

def save_log(key: str, stats: dict):
    log = json.loads(EXPAND_LOG.read_text()) if EXPAND_LOG.exists() else {}
    log[key] = stats
    EXPAND_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False))

# ---------------------------------------------------------------------------
# LÄGE 1: --subcats
# ---------------------------------------------------------------------------
def run_subcats(uid, M, l1, l2, code_to_id, dry_run, lang_filter):
    cats = json.loads(DISCOVERED_FILE.read_text()) if DISCOVERED_FILE.exists() else {}
    cats = {k: v for k, v in cats.items() if v}
    if lang_filter:
        cats = {k: v for k, v in cats.items() if k in lang_filter}

    state = json.loads(SUBCATS_STATE.read_text()) if SUBCATS_STATE.exists() else {}
    stats = {"new": 0, "l1_skip": 0, "l2_enrich": 0, "no_date": 0, "errors": 0}

    print(f"\n{'='*60}")
    print(f"  SUBCATS — {len(cats)} utgåvor, djup {MAX_SUBCAT_DEPTH}, dry={dry_run}")
    print(f"{'='*60}\n")

    for i, (lang, top_cat) in enumerate(sorted(cats.items())):
        key = f"{lang}:{top_cat}"
        if state.get(key) == "done":
            print(f"  [{i+1}/{len(cats)}] {lang} — redan klar (state)")
            continue

        print(f"\n  [{i+1}/{len(cats)}] {lang} — {top_cat}", flush=True)
        country_id = resolve_country(lang, code_to_id)
        lang_new = lang_skip = lang_enrich = 0

        # BFS subkategorier
        queue: list[tuple[str, int]] = [(top_cat, 0)]
        visited: set[str] = set()
        articles: list[str] = []

        while queue:
            cat, depth = queue.pop(0)
            if cat in visited:
                continue
            visited.add(cat)

            for title in get_cat_members(lang, cat, "page"):
                if not is_blocked(title):
                    articles.append(title)

            if depth < MAX_SUBCAT_DEPTH:
                for sc in get_cat_members(lang, cat, "subcat"):
                    if sc not in visited and not is_blocked(sc):
                        queue.append((sc, depth + 1))

        # Ta bort dubbla titlar
        seen_titles: set[str] = set()
        unique_articles = []
        for t in articles:
            if t not in seen_titles:
                seen_titles.add(t)
                unique_articles.append(t)

        print(f"    Kategorier: {len(visited)} | Artiklar: {len(unique_articles)}", flush=True)

        for title in unique_articles:
            eid = make_eid(lang, title)
            if l1.exists(eid):
                lang_skip += 1
                stats["l1_skip"] += 1
                continue

            summary = wiki_summary(title, lang=lang)
            if not summary:
                stats["errors"] += 1
                continue

            qid = get_qid(lang, title)
            if qid:
                existing = l2.get(qid)
                if existing:
                    if not dry_run and existing.get("id"):
                        notes = existing.get("research_notes") or ""
                        tag = f"[SITELINK] {lang}:{title}"
                        if tag not in notes:
                            kw(M, uid, "uap.encounter", "write",
                               [[existing["id"]], {"research_notes": notes + f"\n{tag}"}])
                    l1.add(eid)
                    lang_enrich += 1
                    stats["l2_enrich"] += 1
                    continue

            vals = build_vals(lang, title, summary, qid, country_id)
            if not vals.get("date_observed"):
                stats["no_date"] += 1

            if dry_run:
                yr = (vals.get("date_observed") or "????")[:4]
                print(f"    [DRY] {eid[:65]} | {yr}", flush=True)
            else:
                try:
                    kw(M, uid, "uap.encounter", "create", [vals])
                    l1.add(eid)
                    if qid:
                        l2.add(qid, {"id": None, "encounter_id": eid,
                                     "research_notes": vals["research_notes"]})
                except Exception as e:
                    print(f"    [ERR] {title[:50]}: {e}", flush=True)
                    stats["errors"] += 1
                    continue

            lang_new += 1
            stats["new"] += 1
            if lang_new % 25 == 0:
                print(f"    … {lang_new} nya, {lang_skip} skip", flush=True)

        print(f"    → ny={lang_new} l1_skip={lang_skip} l2_enrich={lang_enrich}")

        if not dry_run:
            state[key] = "done"
            SUBCATS_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    _print_stats("SUBCATS", stats)
    save_log("subcats", stats)

# ---------------------------------------------------------------------------
# LÄGE 2: --uap-terms
# ---------------------------------------------------------------------------
def run_uap_terms(uid, M, l1, l2, code_to_id, dry_run):
    stats = {"new": 0, "l1_skip": 0, "l2_enrich": 0, "no_cat": 0, "errors": 0}
    print(f"\n{'='*60}")
    print(f"  UAP-TERMS — alternativa kategorier, dry={dry_run}")
    print(f"{'='*60}\n")

    for lang, terms in UAP_EXPANDED_TERMS.items():
        print(f"  {lang}: {terms}", flush=True)
        country_id = resolve_country(lang, code_to_id)
        found_cat = None

        for term in terms:
            url = (f"https://{lang}.wikipedia.org/w/api.php?action=query"
                   f"&list=search&srsearch={urllib.parse.quote(term)}"
                   f"&srnamespace=14&srlimit=5&format=json")
            raw = http_get(url, delay=API_DELAY)
            if not raw:
                continue
            data = json.loads(raw)
            for h in data.get("query", {}).get("search", []):
                if not is_blocked(h["title"]):
                    found_cat = h["title"]
                    break
            if found_cat:
                break

        if not found_cat:
            stats["no_cat"] += 1
            continue

        if not is_uap_category(found_cat):
            print(f"    [SKIP] Ej UAP-relaterad kategori: {found_cat}")
            stats["no_cat"] += 1
            continue

        print(f"    → {found_cat}", flush=True)
        lang_new = 0
        for title in get_cat_members(lang, found_cat, "page"):
            if is_blocked(title):
                continue
            eid = make_eid(lang, title)
            if l1.exists(eid):
                stats["l1_skip"] += 1
                continue
            summary = wiki_summary(title, lang=lang)
            if not summary:
                continue
            qid = get_qid(lang, title)
            if qid and l2.get(qid):
                stats["l2_enrich"] += 1
                l1.add(eid)
                continue
            vals = build_vals(lang, title, summary, qid, country_id)
            if dry_run:
                print(f"    [DRY] {eid[:65]}", flush=True)
            else:
                try:
                    kw(M, uid, "uap.encounter", "create", [vals])
                    l1.add(eid)
                    if qid:
                        l2.add(qid, {"id": None, "encounter_id": eid,
                                     "research_notes": vals["research_notes"]})
                except Exception as e:
                    print(f"    [ERR] {title[:50]}: {e}", flush=True)
                    stats["errors"] += 1
                    continue
            lang_new += 1
            stats["new"] += 1
        print(f"    → ny={lang_new}")

    _print_stats("UAP-TERMS", stats)
    save_log("uap_terms", stats)

# ---------------------------------------------------------------------------
# LÄGE 3: --lists
# ---------------------------------------------------------------------------
def run_lists(uid, M, l1, l2, code_to_id, dry_run):
    stats = {"new": 0, "l1_skip": 0, "no_article": 0, "rows": 0, "errors": 0}
    _DATE_FULL = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    _WLINK     = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]")

    print(f"\n{'='*60}")
    print(f"  LISTS — lista-artiklar, dry={dry_run}")
    print(f"{'='*60}\n")

    for lang, list_title in LIST_ARTICLES.items():
        print(f"  {lang}: {list_title}", flush=True)
        check = wiki_summary(list_title, lang=lang, delay=1.0)
        if not check:
            print(f"    Artikel saknas")
            stats["no_article"] += 1
            continue

        data = wiki_api({"action": "query", "titles": list_title,
                         "prop": "revisions", "rvprop": "content", "rvslots": "main"},
                        lang=lang, delay=2.0)
        if not data:
            continue

        wikitext = ""
        for page in data.get("query", {}).get("pages", {}).values():
            revs = page.get("revisions", [])
            if revs:
                wikitext = revs[0].get("slots", {}).get("main", {}).get("*", "")

        if not wikitext:
            continue

        table_rows = re.findall(r"\|-\s*\n((?:\|[^\n]*\n)+)", wikitext)
        lang_new = rows_found = 0

        for row_raw in table_rows:
            cells = [c.strip() for c in re.split(r"(?:^|\n)\|(?!\|)", row_raw) if c.strip()]
            if len(cells) < 2:
                continue

            date_str = None
            dm = _DATE_FULL.search(cells[0])
            if dm:
                date_str = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
            else:
                ym = _YEAR_RE.search(cells[0])
                if ym:
                    date_str = f"{ym.group(1)}-01-01"
            if not date_str:
                continue

            linked = None
            for cell in cells[:4]:
                m = _WLINK.search(cell)
                if m:
                    linked = m.group(1).strip()
                    break

            desc_raw = " | ".join(cells[:4])
            desc = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", desc_raw)
            desc = re.sub(r"<[^>]+>|\{\{[^}]+\}\}", "", desc)[:500].strip()

            row_hash = sha256(f"{lang}|{date_str}|{desc[:80]}".encode()).hexdigest()[:8]
            eid = f"LIST-{lang}-{row_hash}"

            if l1.exists(eid):
                stats["l1_skip"] += 1
                continue

            stats["rows"] += 1
            rows_found += 1

            qid = get_qid(lang, linked) if linked else None
            if qid and l2.get(qid):
                l1.add(eid)
                stats["l1_skip"] += 1
                continue

            notes = f"[SRC] Wikipedia:{lang}:LIST:{list_title}\n[HASH] {row_hash}"
            if qid:
                notes += f"\n[QID] {qid}"

            vals = {
                "encounter_id":    eid,
                "title_en":        linked or desc[:100],
                "date_observed":   date_str,
                "description_en":  desc[:2000],
                "language_original": lang_field(lang) if lang != "en" else False,
                "status":          "pending",
                "research_notes":  notes,
            }

            if dry_run:
                print(f"    [DRY] {eid} | {date_str} | {desc[:45]}", flush=True)
            else:
                try:
                    kw(M, uid, "uap.encounter", "create", [vals])
                    l1.add(eid)
                    if qid:
                        l2.add(qid, {"id": None, "encounter_id": eid,
                                     "research_notes": notes})
                except Exception as e:
                    print(f"    [ERR] {eid}: {e}", flush=True)
                    stats["errors"] += 1
                    continue

            lang_new += 1
            stats["new"] += 1

        print(f"    → rader={rows_found} ny={lang_new}")

    _print_stats("LISTS", stats)
    save_log("lists", stats)

# ---------------------------------------------------------------------------
# LÄGE 4: --wikidata
# ---------------------------------------------------------------------------
def run_wikidata(uid, M, l1, l2, code_to_id, dry_run):
    stats = {"new": 0, "l1_skip": 0, "l2_skip": 0, "errors": 0}
    CACHE = BASE_DIR / "wikidata_sparql_cache.json"

    print(f"\n{'='*60}")
    print(f"  WIKIDATA — Q3814401 SPARQL, dry={dry_run}")
    print(f"{'='*60}\n")

    items = []
    if CACHE.exists():
        cached = json.loads(CACHE.read_text())
        age = (time.time() - cached.get("ts", 0)) / 86400
        if age < 7:
            items = cached["items"]
            print(f"  Cache: {len(items)} items ({age:.1f} d)")

    if not items:
        query = (
            "SELECT ?item ?itemLabel ?date ?country ?countryLabel WHERE {"
            " ?item wdt:P31/wdt:P279* wd:Q40728071 ."
            " OPTIONAL { ?item wdt:P585 ?date . }"
            " OPTIONAL { ?item wdt:P17 ?country . }"
            " SERVICE wikibase:label { bd:serviceParam wikibase:language \"en,sv,fr,de\" . }"
            " } LIMIT 3000"
        )
        url = ("https://query.wikidata.org/sparql?query="
               + urllib.parse.quote(query) + "&format=json")
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/sparql-results+json"})
        time.sleep(5)
        try:
            resp = urllib.request.urlopen(req, timeout=90)
            data = json.loads(resp.read())
            for b in data["results"]["bindings"]:
                items.append({
                    "qid":     b["item"]["value"].rsplit("/", 1)[-1],
                    "label":   b.get("itemLabel", {}).get("value", ""),
                    "date":    b.get("date", {}).get("value", "")[:10],
                    "country": b.get("countryLabel", {}).get("value", ""),
                })
            CACHE.write_text(json.dumps({"ts": time.time(), "items": items},
                                        indent=2, ensure_ascii=False))
            print(f"  SPARQL: {len(items)} items")
        except urllib.error.HTTPError as e:
            print(f"  [ERR] SPARQL HTTP {e.code}")
            if e.code == 429:
                print("  Rate-limitad — försök igen om 60s")
            return

    COUNTRY_NAME_TO_ISO = {
        "United States of America": "US", "United States": "US",
        "France": "FR", "United Kingdom": "GB", "Russia": "RU",
        "Germany": "DE", "Brazil": "BR", "Sweden": "SE", "Australia": "AU",
        "Canada": "CA", "Japan": "JP", "Italy": "IT", "Spain": "ES",
        "Norway": "NO", "Finland": "FI", "Belgium": "BE",
    }

    for idx, item in enumerate(items):
        qid, label, date = item["qid"], item["label"], item["date"]
        eid = f"WD-{qid}"

        if l1.exists(eid):
            stats["l1_skip"] += 1
            continue
        if l2.get(qid):
            stats["l2_skip"] += 1
            l1.add(eid)
            continue

        # Sitelinks
        time.sleep(WIKIDATA_DELAY)
        ent_url = (f"https://www.wikidata.org/w/api.php?action=wbgetentities"
                   f"&ids={qid}&props=sitelinks&format=json")
        raw = http_get(ent_url, delay=0)
        sitelinks: list[str] = []
        if raw:
            ent = json.loads(raw)
            sl = ent.get("entities", {}).get(qid, {}).get("sitelinks", {})
            sitelinks = [f"{k.replace('wiki','').replace('_wiki','')}:{v['title']}"
                         for k, v in sl.items()
                         if k.endswith("wiki") and k not in ("commonswiki", "specieswiki")]

        country_id = None
        iso = COUNTRY_NAME_TO_ISO.get(item.get("country", ""))
        if iso:
            country_id = code_to_id.get(iso)

        notes = f"[QID] {qid}"
        if sitelinks:
            notes += f"\n[SITELINKS] {','.join(sitelinks[:20])}"
        notes += "\n[SRC] Wikidata"

        vals: dict = {
            "encounter_id":  eid,
            "title_en":      label,
            "date_observed": date if date else False,
            "status":        "pending",
            "research_notes": notes,
        }
        if country_id:
            vals["country_id"] = country_id

        if dry_run:
            print(f"  [DRY] {eid} | {label[:50]} | {date} | {len(sitelinks)} sl", flush=True)
        else:
            try:
                kw(M, uid, "uap.encounter", "create", [vals])
                l1.add(eid)
                l2.add(qid, {"id": None, "encounter_id": eid, "research_notes": notes})
            except Exception as e:
                print(f"  [ERR] {qid} {label[:40]}: {e}", flush=True)
                stats["errors"] += 1
                continue
        stats["new"] += 1

        if idx % 50 == 0 and idx > 0:
            print(f"  … {idx}/{len(items)} | ny={stats['new']} skip={stats['l1_skip']+stats['l2_skip']}",
                  flush=True)

    _print_stats("WIKIDATA", stats)
    save_log("wikidata", stats)


# ---------------------------------------------------------------------------
# LÄGE 5: --country-lists
# ---------------------------------------------------------------------------
COUNTRY_LIST_CAT = "Category:UFO sightings by country"
_DATE_FULL_CTRY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_WLINK_CTRY     = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]")

def _get_country_list_pages(lang: str = "en") -> list[str]:
    data = wiki_api({"action": "query", "list": "categorymembers",
                     "cmtitle": COUNTRY_LIST_CAT, "cmlimit": "500", "cmtype": "page"}, lang=lang)
    if not data:
        return []
    return [m["title"] for m in data.get("query", {}).get("categorymembers", [])]

def _country_from_title(title: str, name_to_id: dict) -> int | None:
    m = re.search(r"\bin\s+(?:the\s+)?(.+)$", title, re.IGNORECASE)
    if not m:
        return None
    return name_to_id.get(m.group(1).strip().lower())

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}
_FULLDATE_RE = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{4})\b", re.IGNORECASE
)
_SECTION_YEAR_RE = re.compile(r"==+\s*(?:Pre\s+)?(\d{4})", re.IGNORECASE)

def _parse_wikitext_rows(wikitext: str):
    """Parsar bullet-listformat ('* datum, beskrivning') i Wikipedia landsartiklar."""
    rows = []
    section_year = None
    for line in wikitext.split("\n"):
        sm = _SECTION_YEAR_RE.search(line)
        if sm:
            section_year = sm.group(1)
            continue
        if not line.startswith("* "):
            continue
        text = line[2:].strip()
        if not text or len(text) < 10:
            continue
        # Extrahera datum
        date_str = None
        fm = _FULLDATE_RE.search(text)
        if fm:
            day = fm.group(1).zfill(2)
            mon = _MONTHS[fm.group(2).lower()]
            yr  = fm.group(3)
            date_str = f"{yr}-{mon}-{day}"
        else:
            ym = _YEAR_RE.search(text)
            if ym:
                date_str = f"{ym.group(1)}-01-01"
            elif section_year:
                date_str = f"{section_year}-01-01"
        if not date_str:
            continue
        # Extrahera första meningsfulla wikilink
        linked = None
        lm = _WLINK_CTRY.search(text)
        if lm:
            cand = lm.group(1).strip()
            if not any(b in cand.lower() for b in ("list of", "category:", "file:", "see also")):
                linked = cand
        # Rensa beskrivning
        desc = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", text)
        desc = re.sub(r"<ref[^/][^>]*>.*?</ref>", "", desc, flags=re.DOTALL)
        desc = re.sub(r"<[^>]+>|\{\{[^}]+\}\}", "", desc)[:500].strip()
        rows.append((date_str, linked, desc))
    return rows


def run_country_lists(uid, M, l1, l2, code_to_id, dry_run):
    name_to_id, _ = load_country_map(M, uid)
    stats = {"new": 0, "l1_skip": 0, "no_date": 0, "no_article": 0, "errors": 0}

    print(f"\n{'='*60}")
    print(f"  COUNTRY-LISTS — UFO sightings per land, dry={dry_run}")
    print(f"{'='*60}\n")

    pages = _get_country_list_pages("en")
    print(f"  {len(pages)} land-artiklar funna", flush=True)

    for page_title in pages:
        country_id = _country_from_title(page_title, name_to_id)
        print(f"  {page_title}", flush=True)

        data = wiki_api({"action": "query", "titles": page_title,
                         "prop": "revisions", "rvprop": "content", "rvslots": "main"},
                        lang="en", delay=2.0)
        if not data:
            stats["no_article"] += 1
            continue

        wikitext = ""
        for p in data.get("query", {}).get("pages", {}).values():
            revs = p.get("revisions", [])
            if revs:
                wikitext = revs[0].get("slots", {}).get("main", {}).get("*", "")

        if not wikitext:
            stats["no_article"] += 1
            continue

        rows = _parse_wikitext_rows(wikitext)
        page_new = 0
        for date_str, linked_title, desc in rows:
            if not date_str:
                stats["no_date"] += 1
                continue

            row_hash = sha256(f"CTRY|{page_title}|{date_str}|{desc[:80]}".encode()).hexdigest()[:8]
            eid = f"CTRY-en-{row_hash}"
            if l1.exists(eid):
                stats["l1_skip"] += 1
                continue

            qid = None
            summary = None
            if linked_title:
                qid = get_qid("en", linked_title)
                if qid and l2.get(qid):
                    l1.add(eid)
                    continue
                summary = wiki_summary(linked_title, lang="en")

            notes = [f"[SRC] Wikipedia:en:{page_title}"]
            if linked_title:
                notes.append(f"[LINKED] {linked_title}")
            if qid:
                notes.append(f"[QID] {qid}")

            vals = {
                "encounter_id":   eid,
                "title_en":       linked_title or desc[:100],
                "date_observed":  date_str,
                "description_en": (summary.get("extract", "")[:2000] if summary else desc[:2000]) or False,
                "status":         "pending",
                "research_notes": "\n".join(notes),
            }
            if country_id:
                vals["country_id"] = country_id

            if dry_run:
                print(f"    [DRY] {eid} | {date_str} | {(linked_title or desc)[:50]}", flush=True)
            else:
                try:
                    kw(M, uid, "uap.encounter", "create", [vals])
                    l1.add(eid)
                    if qid:
                        l2.add(qid, {"id": None, "encounter_id": eid,
                                     "research_notes": "\n".join(notes)})
                except Exception as e:
                    print(f"    [ERR] {eid}: {e}", flush=True)
                    stats["errors"] += 1
                    continue
            page_new += 1
            stats["new"] += 1

        print(f"    -> ny={page_new}", flush=True)

    _print_stats("COUNTRY-LISTS", stats)
    save_log("country_lists", stats)


# ---------------------------------------------------------------------------
# LÄGE 6: --films
# ---------------------------------------------------------------------------
FILM_CATS = [
    "Category:UFO-related films",
    "Category:Documentary films about UFOs",
    "Category:Flying saucers in film",
]
_FILM_BLOCK = {"list of", "category:", "template:"}

def _film_blocked(title: str) -> bool:
    tl = title.lower()
    return any(b in tl for b in _FILM_BLOCK)

def run_films(uid, M, l1, l2, code_to_id, dry_run):
    stats = {"new": 0, "l1_skip": 0, "errors": 0}

    print(f"\n{'='*60}")
    print(f"  FILMS — UAP-relaterade filmer, dry={dry_run}")
    print(f"{'='*60}\n")

    seen: set[str] = set()
    film_list: list[tuple[str, str]] = []

    for cat in FILM_CATS:
        print(f"  Kategori: {cat}", flush=True)
        for title in get_cat_members("en", cat, cmtype="page"):
            if title not in seen and not _film_blocked(title):
                seen.add(title)
                film_list.append((cat, title))
        for subcat in get_cat_members("en", cat, cmtype="subcat"):
            for title in get_cat_members("en", subcat, cmtype="page"):
                if title not in seen and not _film_blocked(title):
                    seen.add(title)
                    film_list.append((subcat, title))

    print(f"  {len(film_list)} unika filmer funna", flush=True)

    for cat_src, title in film_list:
        eid = f"FILM-en-{norm_slug(title)}"
        if l1.exists(eid):
            stats["l1_skip"] += 1
            continue

        qid = get_qid("en", title)
        if qid and l2.get(qid):
            l1.add(eid)
            stats["l1_skip"] += 1
            continue

        summary = wiki_summary(title, lang="en")
        if not summary:
            continue

        extract = summary.get("extract", "")
        year = extract_year(summary.get("description", "") + " " + extract + " " + title)

        notes = ["[FILM]", f"[SRC] Wikipedia:en:{title}", f"[CAT] {cat_src}"]
        if qid:
            notes.append(f"[QID] {qid}")
        url = summary.get("content_urls", {}).get("desktop", {}).get("page", "")
        if url:
            notes.append(f"[URL] {url}")

        vals = {
            "encounter_id":    eid,
            "title_en":        title,
            "encounter_class": "5",
            "description_en":  extract[:2000] if extract else False,
            "date_observed":   f"{year}-01-01" if year else False,
            "status":          "pending",
            "research_notes":  "\n".join(notes),
        }

        if dry_run:
            print(f"  [DRY] {eid} | {year or '????'} | {title[:55]}", flush=True)
        else:
            try:
                kw(M, uid, "uap.encounter", "create", [vals])
                l1.add(eid)
                if qid:
                    l2.add(qid, {"id": None, "encounter_id": eid,
                                 "research_notes": "\n".join(notes)})
                print(f"  [OK] {title[:60]}", flush=True)
            except Exception as e:
                print(f"  [ERR] {title[:50]}: {e}", flush=True)
                stats["errors"] += 1
                continue
        stats["new"] += 1

    _print_stats("FILMS", stats)
    save_log("films", stats)



# ---------------------------------------------------------------------------
# LÄGE 7: --nordic
# ---------------------------------------------------------------------------
NORDIC_CATS = [
    # Svenska — helt osökt hittills
    ("sv", "Kategori:Oidentifierade flygande föremål"),
    ("sv", "Kategori:Spökraketer"),
    # Norska — helt osökt hittills
    ("no", "Kategori:Uidentifiserte flygende objekter"),
    ("no", "Kategori:Spøkelsesraketter"),
    # Danska — komplettering (subcats gav 7, men ej ghost rockets)
    ("da", "Kategori:Spøgelsesraketter"),
]

NORDIC_LISTS = [
    # Möjliga listartiklar per språk
    ("sv", "Lista över UFO-observationer i Sverige"),
    ("sv", "Spökraketer"),
    ("sv", "UFO-observationer i Sverige"),
    ("no", "Spøkelsesraketter"),
    ("no", "UFO-observasjoner i Norge"),
    ("da", "Spøgelsesraketter"),
]

def run_nordic(uid, M, l1, l2, code_to_id, dry_run):
    stats = {"new": 0, "l1_skip": 0, "l2_enrich": 0, "no_cat": 0,
             "no_article": 0, "no_date": 0, "errors": 0}

    print(f"\n{'='*60}")
    print(f"  NORDIC — sv/no/da UAP & spökraketer, dry={dry_run}")
    print(f"{'='*60}\n")

    lang_iso = {"sv": "SE", "no": "NO", "da": "DK"}

    # --- DEL 1: Kategorisweep (djup 2) ---
    print("  DEL 1: Kategorier", flush=True)
    for lang, top_cat in NORDIC_CATS:
        country_id = code_to_id.get(lang_iso.get(lang, ""))
        print(f"\n  [{lang}] {top_cat}", flush=True)

        # Kontrollera att kategorin finns
        test = wiki_api({"action": "query", "titles": top_cat,
                         "prop": "info"}, lang=lang, delay=1.0)
        pages = test.get("query", {}).get("pages", {}) if test else {}
        if any(p.get("missing") is not None for p in pages.values()):
            print(f"    [SKIP] Kategori saknas på {lang}.wikipedia.org")
            stats["no_cat"] += 1
            continue

        # Samla artiklar från kategorin och dess underkategorier (djup 2)
        article_titles: list[str] = []
        subcats = get_cat_members(lang, top_cat, cmtype="subcat")
        article_titles.extend(get_cat_members(lang, top_cat, cmtype="page"))
        for sub in subcats:
            article_titles.extend(get_cat_members(lang, sub, cmtype="page"))

        print(f"    {len(article_titles)} artiklar", flush=True)
        cat_new = 0

        for title in article_titles:
            if is_blocked(title):
                continue
            eid = make_eid(lang, title)
            if l1.exists(eid):
                stats["l1_skip"] += 1
                continue

            summary = wiki_summary(title, lang=lang)
            if not summary:
                continue

            qid = get_qid(lang, title)
            if qid:
                existing = l2.get(qid)
                if existing:
                    if not dry_run and existing.get("id"):
                        notes = existing.get("research_notes") or ""
                        tag = f"[SITELINK] {lang}:{title}"
                        if tag not in notes:
                            try:
                                kw(M, uid, "uap.encounter", "write",
                                   [[existing["id"]], {"research_notes": notes + f"\n{tag}"}])
                            except Exception:
                                pass
                    l1.add(eid)
                    stats["l2_enrich"] += 1
                    continue

            vals = build_vals(lang, title, summary, qid, country_id)
            if not vals.get("date_observed"):
                stats["no_date"] += 1

            if dry_run:
                yr = (vals.get("date_observed") or "????")[:4]
                print(f"    [DRY] {eid[:65]} | {yr}", flush=True)
            else:
                try:
                    kw(M, uid, "uap.encounter", "create", [vals])
                    l1.add(eid)
                    if qid:
                        l2.add(qid, {"id": None, "encounter_id": eid,
                                     "research_notes": vals["research_notes"]})
                except Exception as e:
                    print(f"    [ERR] {title[:50]}: {e}", flush=True)
                    stats["errors"] += 1
                    continue
            cat_new += 1
            stats["new"] += 1

        print(f"    -> ny={cat_new} l1_skip={stats['l1_skip']} l2_enrich={stats['l2_enrich']}",
              flush=True)

    # --- DEL 2: Listartiklar (bullet-format) ---
    print(f"\n  DEL 2: Listartiklar", flush=True)
    for lang, list_title in NORDIC_LISTS:
        country_id = code_to_id.get(lang_iso.get(lang, ""))
        print(f"  [{lang}] {list_title}", flush=True)

        check = wiki_summary(list_title, lang=lang, delay=1.0)
        if not check:
            print(f"    Artikel saknas")
            stats["no_article"] += 1
            continue

        data = wiki_api({"action": "query", "titles": list_title,
                         "prop": "revisions", "rvprop": "content", "rvslots": "main"},
                        lang=lang, delay=2.0)
        if not data:
            continue

        wikitext = ""
        for p in data.get("query", {}).get("pages", {}).values():
            revs = p.get("revisions", [])
            if revs:
                wikitext = revs[0].get("slots", {}).get("main", {}).get("*", "")

        if not wikitext:
            continue

        rows = _parse_wikitext_rows(wikitext)
        list_new = 0
        for date_str, linked_title, desc in rows:
            if not date_str:
                stats["no_date"] += 1
                continue

            row_hash = sha256(f"NORDIC|{lang}|{list_title}|{date_str}|{desc[:80]}".encode()).hexdigest()[:8]
            eid = f"CTRY-{lang}-{row_hash}"
            if l1.exists(eid):
                stats["l1_skip"] += 1
                continue

            qid = None
            summary = None
            if linked_title:
                qid = get_qid(lang, linked_title)
                if qid and l2.get(qid):
                    l1.add(eid)
                    stats["l2_enrich"] += 1
                    continue
                summary = wiki_summary(linked_title, lang=lang)

            notes = [f"[SRC] Wikipedia:{lang}:{list_title}"]
            if linked_title:
                notes.append(f"[LINKED] {linked_title}")
            if qid:
                notes.append(f"[QID] {qid}")

            vals = {
                "encounter_id":   eid,
                "title_en":       linked_title or desc[:100],
                "title_original": linked_title or desc[:100],
                "language_original": lang_field(lang),
                "date_observed":  date_str,
                "description_en": False,
                "description_original": (summary.get("extract", "")[:2000]
                                         if summary else desc[:2000]) or False,
                "status":         "pending",
                "research_notes": "\n".join(notes),
            }
            if country_id:
                vals["country_id"] = country_id

            if dry_run:
                print(f"    [DRY] {eid} | {date_str} | {(linked_title or desc)[:50]}", flush=True)
            else:
                try:
                    kw(M, uid, "uap.encounter", "create", [vals])
                    l1.add(eid)
                    if qid:
                        l2.add(qid, {"id": None, "encounter_id": eid,
                                     "research_notes": "\n".join(notes)})
                except Exception as e:
                    print(f"    [ERR] {eid}: {e}", flush=True)
                    stats["errors"] += 1
                    continue
            list_new += 1
            stats["new"] += 1

        print(f"    -> ny={list_new}", flush=True)

    _print_stats("NORDIC", stats)
    save_log("nordic", stats)



# ---------------------------------------------------------------------------
# LÄGE 8: --uso  (unidentified submerged objects + UFO-type articles)
# ---------------------------------------------------------------------------
USO_SEED_ARTICLES = [
    # USO / undervattensanomalier
    "Unidentified submerged object",
    "Unidentified submarine object",
    "Baltic Sea anomaly",
    "Lake Michigan Triangle",
    "Yonaguni Monument",
    "Utsuro-bune",
    # Kända UAP-incidenter med inslag i vatten / saknades i DB
    "USS Nimitz UFO incident",
    "2004 USS Princeton UFO incident",
    "USS Theodore Roosevelt UFO incidents",
    "UAP Task Force",
    "All-domain Anomaly Resolution Office",
    # Övriga UFO-typer ej täckta
    "Mystery airship",
    "Phantom airship",
    "Kenneth Arnold UFO sighting",
    "Maury Island incident",
    "Underwater UFO",
    # USO-forskare och teorier (tillagda efter sökanalys)
    "Meade Layne",
    "Ivan T. Sanderson",
    "Pascagoula incident",
    "Bruce Maccabee",
    "UFO reports and disinformation",
    "Cryptoterrestrial hypothesis",
    "The Atomic Submarine",
    "Project U.F.O.",
]

def _get_uso_backlinks(lang="en") -> list[str]:
    titles = []
    cont = {}
    for _ in range(5):
        params = {"action": "query", "list": "backlinks",
                  "bltitle": "Unidentified submerged object",
                  "blnamespace": "0", "bllimit": "100"}
        params.update(cont)
        data = wiki_api(params, lang=lang, delay=1.5)
        if not data:
            break
        titles.extend(b["title"] for b in data.get("query", {}).get("backlinks", []))
        cont = data.get("continue", {})
        if not cont:
            break
    return titles


def run_uso(uid, M, l1, l2, code_to_id, dry_run):
    stats = {"new": 0, "l1_skip": 0, "l2_enrich": 0, "no_summary": 0, "errors": 0}

    print(f"\n{'='*60}")
    print(f"  USO — undervattensanomalier & UAP-typer, dry={dry_run}")
    print(f"{'='*60}\n")

    # Bygg artikellista: seed + bakåtlänkar till USO-artikeln
    backlinks = _get_uso_backlinks("en")
    all_titles = list(dict.fromkeys(USO_SEED_ARTICLES + backlinks))
    print(f"  {len(all_titles)} artiklar att bearbeta ({len(USO_SEED_ARTICLES)} seed + {len(backlinks)} backlinks)", flush=True)

    SKIP_TITLES = {"water", "sea monster", "wikipedia:stub", "ufologists",
                   "unidentified flying object", "unidentified flying objects",
                   "charles fort", "underwater archaeology"}

    for title in all_titles:
        if title.lower() in SKIP_TITLES:
            continue
        if is_blocked(title):
            continue

        eid = make_eid("en", title)
        if l1.exists(eid):
            stats["l1_skip"] += 1
            continue

        qid = get_qid("en", title)
        if qid and l2.get(qid):
            l1.add(eid)
            stats["l2_enrich"] += 1
            continue

        summary = wiki_summary(title, lang="en")
        if not summary or summary.get("type") == "disambiguation":
            stats["no_summary"] += 1
            continue

        vals = build_vals("en", title, summary, qid, None)
        # Tagga som USO om titeln innehåller undervattensindikator
        uso_keywords = ("submerged", "submarine", "underwater", "ocean", "sea",
                        "lake", "maritime", "naval", "aquatic", "utsuro", "yonaguni")
        if any(k in title.lower() for k in uso_keywords):
            notes = vals.get("research_notes", "")
            vals["research_notes"] = "[USO]\n" + notes

        if dry_run:
            yr = (vals.get("date_observed") or "????")[:4]
            uso_tag = " [USO]" if "[USO]" in vals.get("research_notes", "") else ""
            print(f"  [DRY] {eid[:65]} | {yr}{uso_tag}", flush=True)
        else:
            try:
                kw(M, uid, "uap.encounter", "create", [vals])
                l1.add(eid)
                if qid:
                    l2.add(qid, {"id": None, "encounter_id": eid,
                                 "research_notes": vals["research_notes"]})
                print(f"  [OK] {title[:65]}", flush=True)
            except Exception as e:
                print(f"  [ERR] {title[:50]}: {e}", flush=True)
                stats["errors"] += 1
                continue

    _print_stats("USO", stats)
    save_log("uso", stats)


# ---------------------------------------------------------------------------
# Util
# ---------------------------------------------------------------------------
def _print_stats(mode: str, stats: dict):
    print(f"\n{'='*60}")
    print(f"  {mode} KLAR")
    for k, v in stats.items():
        print(f"  {k:<15} {v}")
    print(f"{'='*60}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subcats",     action="store_true")
    ap.add_argument("--uap-terms",   action="store_true")
    ap.add_argument("--lists",       action="store_true")
    ap.add_argument("--wikidata",       action="store_true")
    ap.add_argument("--country-lists",  action="store_true")
    ap.add_argument("--films",           action="store_true")
    ap.add_argument("--nordic",          action="store_true")
    ap.add_argument("--uso",             action="store_true")
    ap.add_argument("--dry-run",     action="store_true")
    ap.add_argument("--lang",        default="", help="t.ex. sv,en,fr (för --subcats)")
    ap.add_argument("--reset-state", action="store_true")
    args = ap.parse_args()

    if not any([args.subcats, args.uap_terms, args.lists, args.wikidata, args.country_lists, args.films, args.nordic, args.uso]):
        ap.print_help()
        return

    if args.reset_state and SUBCATS_STATE.exists():
        SUBCATS_STATE.unlink()
        print("State nollställd.")

    lang_filter = [l.strip() for l in args.lang.split(",") if l.strip()]

    print(f"Ansluter {ODOO_URL} / {ODOO_DB}…")
    uid, M = _make_odoo()
    l1 = DeduplicatorL1(M, uid)
    l2 = DeduplicatorL2(M, uid)
    _, code_to_id = load_country_map(M, uid)

    if args.subcats:
        run_subcats(uid, M, l1, l2, code_to_id, args.dry_run, lang_filter)
    if args.uap_terms:
        run_uap_terms(uid, M, l1, l2, code_to_id, args.dry_run)
    if args.lists:
        run_lists(uid, M, l1, l2, code_to_id, args.dry_run)
    if args.wikidata:
        run_wikidata(uid, M, l1, l2, code_to_id, args.dry_run)
    if args.country_lists:
        run_country_lists(uid, M, l1, l2, code_to_id, args.dry_run)
    if args.films:
        run_films(uid, M, l1, l2, code_to_id, args.dry_run)
    if args.nordic:
        run_nordic(uid, M, l1, l2, code_to_id, args.dry_run)
    if args.uso:
        run_uso(uid, M, l1, l2, code_to_id, args.dry_run)

if __name__ == "__main__":
    main()
