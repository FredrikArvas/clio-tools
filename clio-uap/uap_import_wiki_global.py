"""
uap_import_wiki_global.py — Wikipedia UAP-baseline, alla länder

Samlar in UAP-rapporter från Wikipedia i tre faser:

  Fas 1 — Masterlistan
    Parsar "List of reported UFO sightings" (en.wikipedia.org).
    Strukturerade wikitabeller med datum, namn, land, beskrivning.

  Fas 2 — Kategoriträdet
    Traverserar Category:UFO sightings + alla subkategorier.
    Varje artikel = ett individuellt fall → REST summary → datum, koordinater.

  Fas 3 — Lokal Wikipedia (via Wikidata interlanguage-länkar)
    Hittar rätt kategori per språk utan hårdkodning.
    Traverserar och importerar fall dokumenterade endast lokalt.

Dedup: source_ref = "WIKI-{lang}:{normalized_title}"
State:  .wiki_global_state.json (fas/progress tracking)

Kör: python3 uap_import_wiki_global.py [--phase 1|2|3|all] [--dry-run] [--limit N]
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, unicodedata, uuid, xmlrpc.client
import urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = "uapdb"
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

STATE_FILE = Path(__file__).parent / ".wiki_global_state.json"
USER_AGENT = "clio-uap-research/1.0 (contact: research@arvas.international)"

WIKI_API     = "https://{lang}.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}"

# ---------------------------------------------------------------------------
# Regex — deterministic, inga gissningar
# ---------------------------------------------------------------------------

# Datum i wikitext: 1947-06-24 med valfri <wbr>-tag
_DATE_RE  = re.compile(r"(\d{4})-(?:<wbr>)?(\d{2})-(?:<wbr>)?(\d{2})")
# Löst år (om exakt datum saknas)
_YEAR_RE  = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b")
# Wikilink: [[Artikel]] eller [[Artikel|Visningstext]]
_WLINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]")
# Strip allt wiki-markup
_REF_RE   = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^/]*/?>", re.DOTALL)
_TPL_RE   = re.compile(r"\{\{[^}]*\}\}")
_TAG_RE   = re.compile(r"<[^>]+>")
_BOLD_RE  = re.compile(r"'{2,3}")

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
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _http_get(url: str, delay: float = 1.0) -> bytes | None:
    if delay:
        time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404, 414):
                return None
            if e.code in (429, 500, 502, 503, 504):
                if attempt == 0:
                    time.sleep(10)
                    continue
                print(f"  [WARN] HTTP {e.code}: {url[:80]}", flush=True)
                return None
            raise
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            if attempt == 0:
                time.sleep(5)
                continue
            print(f"  [WARN] nätverksfel: {e}", flush=True)
            return None
    return None


def _wiki_api(params: dict, lang: str = "en", delay: float = 1.0) -> dict | None:
    params.setdefault("format", "json")
    url = WIKI_API.format(lang=lang) + "?" + urllib.parse.urlencode(params)
    raw = _http_get(url, delay=delay)
    if raw is None:
        return None
    return json.loads(raw)


def _wiki_summary(title: str, lang: str = "en", delay: float = 1.0) -> dict | None:
    slug = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url  = WIKI_SUMMARY.format(lang=lang, slug=slug)
    raw  = _http_get(url, delay=delay)
    if raw is None:
        return None
    d = json.loads(raw)
    return d if d.get("type") not in ("disambiguation", None) else None


def strip_wiki(text: str) -> str:
    """Tar bort all wiki-markup och returnerar ren text."""
    text = _REF_RE.sub("", text)
    text = _TPL_RE.sub("", text)
    # Wikilinks: behåll visningstext
    text = _WLINK_RE.sub(lambda m: m.group(1).split("|")[-1] if "|" in m.group(0)
                          else m.group(1), text)
    text = _TAG_RE.sub("", text)
    text = _BOLD_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def norm_title(title: str) -> str:
    """Normaliserar artikeltitel för source_ref (ingen URL-encoding, inga mellanslag)."""
    return unicodedata.normalize("NFC", title.strip().replace(" ", "_"))


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"phase1_done": False, "phase2_done": False, "phase2_seen": [],
            "phase3_done": False, "phase3_seen": []}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Region-mappning (ISO-2 kod → Odoo selection key)
# ---------------------------------------------------------------------------
_CODE_TO_REGION: dict[str, str] = {
    # Europa
    **{c: "europe" for c in [
        "AD","AL","AT","BA","BE","BG","BY","CH","CY","CZ","DE","DK","EE","ES","FI",
        "FR","GB","GR","HR","HU","IE","IS","IT","LI","LT","LU","LV","MC","MD","ME",
        "MK","MT","NL","NO","PL","PT","RO","RS","RU","SE","SI","SK","SM","TR","UA",
        "VA","XK","AZ","AM","GE",
    ]},
    # Nordamerika
    **{c: "north_america" for c in [
        "CA","US","MX","GT","BZ","HN","SV","NI","CR","PA",
        "CU","JM","HT","DO","PR","TT","BB","LC","VC","GD","AG","DM","KN",
    ]},
    # Sydamerika
    **{c: "south_america" for c in [
        "CO","VE","GY","SR","BR","EC","PE","BO","PY","UY","AR","CL","FK","GF",
    ]},
    # Asien
    **{c: "asia" for c in [
        "AF","BD","BN","BT","CN","HK","ID","IN","JP","KH","KP","KR","LA","LK",
        "MM","MN","MO","MV","MY","NP","PH","PK","SG","TH","TL","TW","VN",
        "KZ","KG","TJ","TM","UZ",
    ]},
    # Afrika
    **{c: "africa" for c in [
        "AO","BF","BI","BJ","BW","CD","CF","CG","CI","CM","CV","DJ","DZ","EG",
        "ER","ET","GA","GH","GM","GN","GQ","GW","KE","KM","LR","LS","LY","MA",
        "MG","ML","MR","MU","MW","MZ","NA","NE","NG","RW","SC","SD","SL","SN",
        "SO","SS","ST","SZ","TD","TG","TN","TZ","UG","ZA","ZM","ZW",
    ]},
    # Oceanien
    **{c: "oceania" for c in [
        "AU","FJ","FM","KI","MH","MP","NC","NR","NZ","PF","PG","PW","SB","TO",
        "TV","VU","WS","CK","NU",
    ]},
    # Mellanöstern
    **{c: "middle_east" for c in [
        "AE","BH","IQ","IR","IL","JO","KW","LB","OM","QA","SA","SY","YE","PS",
    ]},
}

def _country_raw_to_region(raw: str, code_to_cid: dict) -> str | None:
    """Försöker mappa ett landsnamn/-kod till en Odoo-region."""
    if not raw:
        return None
    code = raw.strip().upper()
    # Direkt kod-matchning
    if code in _CODE_TO_REGION:
        return _CODE_TO_REGION[code]
    # Vanliga engelska namn
    _NAME_REGION: dict[str, str] = {
        "united states": "north_america", "usa": "north_america", "u.s.": "north_america",
        "united kingdom": "europe", "great britain": "europe",
        "canada": "north_america", "australia": "oceania", "new zealand": "oceania",
        "brazil": "south_america", "argentina": "south_america", "chile": "south_america",
        "france": "europe", "germany": "europe", "spain": "europe", "italy": "europe",
        "russia": "europe", "china": "asia", "japan": "asia", "india": "asia",
        "south africa": "africa", "nigeria": "africa", "kenya": "africa",
        "iran": "middle_east", "iraq": "middle_east", "israel": "middle_east",
        "saudi arabia": "middle_east", "turkey": "europe",
    }
    key = raw.strip().lower()
    for name, region in _NAME_REGION.items():
        if key == name or name in key:
            return region
    return None


# ---------------------------------------------------------------------------
# Odoo-hjälpare
# ---------------------------------------------------------------------------

def _load_odoo_lookups() -> tuple[dict, dict, int | None, int | None]:
    """Hämtar landsnamn→ID, befintliga source_refs, WIKI-databas-ID."""
    # Länder
    countries = kw("res.country", "search_read", [[]], {"fields": ["id", "name", "code"], "limit": 300})
    name_to_cid: dict[str, int] = {}
    code_to_cid: dict[str, int] = {}
    for c in countries:
        name_to_cid[c["name"].lower()] = c["id"]
        code_to_cid[c["code"].upper()]  = c["id"]
    # Befintliga source_refs (för dedup)
    existing = kw("uap.encounter", "search_read",
                  [[["source_ref", "like", "WIKI-"]]],
                  {"fields": ["source_ref"], "limit": 50000})
    existing_refs: set[str] = {e["source_ref"] for e in existing if e.get("source_ref")}
    # WIKI-databas
    dbs = kw("uap.database", "search_read",
             [[["name", "=", "Wikipedia"]]], {"fields": ["id"], "limit": 1})
    wiki_db_id = dbs[0]["id"] if dbs else None
    return name_to_cid, code_to_cid, existing_refs, wiki_db_id


def _resolve_country(raw: str, name_to_cid: dict, code_to_cid: dict) -> int | None:
    """Matchar ett landnamn/kod mot Odoo-länder utan gissningar."""
    raw = raw.strip()
    # Exakt matchning på kod
    if raw.upper() in code_to_cid:
        return code_to_cid[raw.upper()]
    # Exakt matchning på namn (case-insensitive)
    key = raw.lower()
    if key in name_to_cid:
        return name_to_cid[key]
    # Partiell: "United States" matchar "United States of America"
    for name, cid in name_to_cid.items():
        if key in name or name in key:
            return cid
    return None


def _create_encounter(vals: dict, dry_run: bool) -> bool:
    """Skapar ett encounter. Returnerar True om skapat/simulerat."""
    if dry_run:
        return True
    try:
        kw("uap.encounter", "create", [vals])
        return True
    except Exception as e:
        print(f"  [ERR] create: {e}", flush=True)
        return False


# ---------------------------------------------------------------------------
# FAS 1 — Masterlistan "List of reported UFO sightings"
# ---------------------------------------------------------------------------

MASTER_LIST_TITLE = "List of reported UFO sightings"

def _parse_master_list(wikitext: str) -> list[dict]:
    """
    Parsar wikitabelrader ur masterlistan.
    Returnerar list av dicts: {date_str, year, title, wiki_title, country_raw, location_raw, description}
    """
    rows = []
    # Tabellrader separeras av |-  (ny rad efter)
    # Kolumnordning: Date | Name | Location | Description
    lines = wikitext.split("\n")
    in_table = False
    current_cells: list[str] = []
    cell_buffer = ""

    def flush_cell():
        nonlocal cell_buffer
        c = cell_buffer.strip()
        cell_buffer = ""
        return c

    def process_row(cells: list[str]):
        """Parsar en komplett rad med 4 celler."""
        if len(cells) < 3:
            return None
        date_raw, name_raw, loc_raw = cells[0], cells[1], cells[2]
        desc_raw = cells[3] if len(cells) > 3 else ""

        # Datum
        dm = _DATE_RE.search(date_raw)
        if dm:
            date_str = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)} 00:00:00"
            year = int(dm.group(1))
        else:
            ym = _YEAR_RE.search(date_raw)
            if ym:
                year = int(ym.group(1))
                date_str = f"{year}-01-01 00:00:00"
            else:
                return None  # Ingen datum → hoppa

        # Wiki-tittel (artikel-länk om den finns)
        wl = _WLINK_RE.search(name_raw)
        wiki_title = wl.group(1).strip() if wl else None
        title_en   = strip_wiki(name_raw) or wiki_title or "Unknown"

        # Land + plats
        # Format: <span ...>Region</span>[[Country]]; [[State/City]]
        # Ta bort span-element först
        loc_clean = _TAG_RE.sub("", loc_raw)
        links = _WLINK_RE.findall(loc_raw)
        country_raw  = links[0].strip() if links else ""
        location_raw = strip_wiki(loc_clean)

        description = strip_wiki(desc_raw)[:500] if desc_raw else ""

        return {
            "date_str":    date_str,
            "year":        year,
            "title_en":    title_en.strip()[:200],
            "wiki_title":  wiki_title,
            "country_raw": country_raw,
            "location_raw": location_raw.strip()[:200],
            "description": description,
        }

    # Iterera raderna i wikitexten
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("{|") and "wikitable" in line:
            in_table = True
            current_cells = []
            cell_buffer = ""
            i += 1
            continue
        if line.startswith("|}"):
            in_table = False
            i += 1
            continue
        if not in_table:
            i += 1
            continue

        if line.startswith("|-"):
            # Ny rad — processa eventuellt buffrerat cell-innehåll
            if cell_buffer.strip():
                current_cells.append(flush_cell())
            if current_cells:
                row = process_row(current_cells)
                if row:
                    rows.append(row)
            current_cells = []
            cell_buffer = ""
        elif line.startswith("|") and not line.startswith("||"):
            # Ny cell
            if cell_buffer.strip():
                current_cells.append(flush_cell())
            cell_buffer = line[1:]  # Hoppa | -tecknet
        elif line.startswith("!"):
            pass  # Rubrikrad, ignorera
        else:
            # Fortsättning av nuvarande cell
            cell_buffer += " " + line

        i += 1

    return rows


def run_phase1(dry_run: bool, limit: int, delay: float) -> int:
    print(f"\n{'='*60}")
    print(f"  Fas 1 — Masterlistan{' [DRY RUN]' if dry_run else ''}")
    print(f"{'='*60}")

    name_to_cid, code_to_cid, existing_refs, wiki_db_id = _load_odoo_lookups()

    # Hämta wikitext
    print(f"  Hämtar wikitext för {MASTER_LIST_TITLE!r}...")
    data = _wiki_api({
        "action": "query", "titles": MASTER_LIST_TITLE,
        "prop": "revisions", "rvprop": "content", "rvslots": "main",
    }, delay=0)
    if not data:
        print("  [ERR] Kunde inte hämta wikitext"); return 0

    pages = data["query"]["pages"]
    page  = next(iter(pages.values()))
    wikitext = page["revisions"][0]["slots"]["main"]["*"]
    print(f"  Wikitext: {len(wikitext):,} tecken")

    rows = _parse_master_list(wikitext)
    print(f"  Parsade rader: {len(rows)}")

    if limit:
        rows = rows[:limit]

    created = skipped = errors = 0
    for row in rows:
        source_ref = f"WIKI-en:{norm_title(row['wiki_title'] or row['title_en'])}"

        if source_ref in existing_refs:
            skipped += 1
            continue

        country_id = _resolve_country(row["country_raw"], name_to_cid, code_to_cid)
        region = _country_raw_to_region(row["country_raw"], code_to_cid)

        vals: dict = {
            "encounter_id":    str(uuid.uuid4()),
            "title_en":        row["title_en"],
            "date_observed":   row["date_str"],
            "source_ref":      source_ref,
            "description_en":  row["description"],
        }
        if region:
            vals["region"] = region
        if country_id:
            vals["country_id"] = country_id
        if wiki_db_id:
            vals["database_id"] = wiki_db_id
        # Lägg plats i research_notes (location_en-fältet finns ej i modellen)
        loc_note = f"\n[LOC] {row['location_raw']}" if row.get("location_raw") else ""
        vals["research_notes"] = f"[SRC] Wikipedia: {MASTER_LIST_TITLE}{loc_note}"
        if row.get("wiki_title"):
            vals["research_notes"] += f"\n[ARTICLE] https://en.wikipedia.org/wiki/{urllib.parse.quote(row['wiki_title'].replace(' ','_'))}"

        if dry_run:
            if created < 5:
                print(f"  [DRY] {row['year']} | {row['title_en'][:50]} | {row['country_raw']}")
            created += 1
        else:
            if _create_encounter(vals, dry_run=False):
                existing_refs.add(source_ref)
                created += 1
                if created % 50 == 0:
                    print(f"  [{created} skapade, {skipped} skip, {errors} fel]", flush=True)
            else:
                errors += 1

        time.sleep(delay * 0.1)  # Odoo-throttle (inte Wikipedia)

    print(f"\n  Fas 1 klar: {created} skapade | {skipped} redan finns | {errors} fel")
    return created


# ---------------------------------------------------------------------------
# FAS 2 — Kategoriträdet
# ---------------------------------------------------------------------------

def _get_category_members(cat_title: str, lang: str = "en",
                           delay: float = 1.0) -> tuple[list[str], list[str]]:
    """
    Hämtar sidor och subkategorier ur en Wikipedia-kategori.
    Returnerar (page_titles, subcat_titles).

    cat_title kan antingen vara ett rent namn ("UFO sightings") eller
    ett fullständigt namn inklusive lokalt prefix ("Catégorie:Observation d'ovni").
    Om titeln innehåller ":" antas den redan ha korrekt prefix.
    """
    pages: list[str] = []
    subcats: list[str] = []
    cont = {}
    # Har titeln redan namespace-prefix (t.ex. "Catégorie:X", "Kategorie:X") → använd direkt.
    # Annars lägg till engelska "Category:" som default.
    cm_title = cat_title if ":" in cat_title else f"Category:{cat_title}"
    while True:
        params: dict = {
            "action": "query", "list": "categorymembers",
            "cmtitle": cm_title,
            "cmlimit": "500", "cmtype": "page|subcat",
        }
        params.update(cont)
        data = _wiki_api(params, lang=lang, delay=delay)
        if not data:
            break
        for m in data.get("query", {}).get("categorymembers", []):
            ns = m.get("ns", 0)
            title = m["title"]
            if ns == 14:  # Kategorins namespace — behåll hela titeln med lokalt prefix
                subcats.append(title)
            else:
                pages.append(title)
        if "continue" not in data:
            break
        cont = data["continue"]
    return pages, subcats


def _walk_category_tree(root_cat: str, lang: str = "en", delay: float = 1.0,
                         max_depth: int = 3) -> set[str]:
    """
    Traverserar kategoriträdet (BFS, max_depth nivåer).
    Returnerar set av alla unika sidtitlar.
    """
    visited_cats: set[str] = set()
    all_pages:    set[str] = set()
    queue = [(root_cat, 0)]

    while queue:
        cat, depth = queue.pop(0)
        if cat in visited_cats or depth > max_depth:
            continue
        visited_cats.add(cat)

        pages, subcats = _get_category_members(cat, lang=lang, delay=delay)
        all_pages.update(pages)
        print(f"  Kat [{depth}] {cat!r}: {len(pages)} sidor, {len(subcats)} subkat", flush=True)

        for sc in subcats:
            if sc not in visited_cats:
                queue.append((sc, depth + 1))

    return all_pages


def run_phase2(dry_run: bool, limit: int, delay: float) -> int:
    print(f"\n{'='*60}")
    print(f"  Fas 2 — Kategoriträdet{' [DRY RUN]' if dry_run else ''}")
    print(f"{'='*60}")

    name_to_cid, code_to_cid, existing_refs, wiki_db_id = _load_odoo_lookups()

    ROOT_CAT = "UFO sightings"
    print(f"  Traverserar Category:{ROOT_CAT} (djup max 3)...")
    all_pages = _walk_category_tree(ROOT_CAT, lang="en", delay=delay)
    print(f"  Totalt unika sidor i kategoriträdet: {len(all_pages)}")

    if limit:
        all_pages_list = list(all_pages)[:limit]
    else:
        all_pages_list = list(all_pages)

    created = skipped = no_date = errors = 0

    for i, title in enumerate(all_pages_list, 1):
        source_ref = f"WIKI-en:{norm_title(title)}"
        if source_ref in existing_refs:
            skipped += 1
            continue

        summary = _wiki_summary(title, lang="en", delay=delay)
        if not summary:
            skipped += 1
            continue

        extract = summary.get("extract", "")
        # Datum: försök med REST-svarets koordinater och år ur texten
        ym = _YEAR_RE.search(extract)
        if not ym:
            no_date += 1
            if i % 20 == 0:
                print(f"  [{i}/{len(all_pages_list)}] skip={skipped} nodate={no_date} "
                      f"created={created}", flush=True)
            continue

        year     = int(ym.group(1))
        date_str = f"{year}-01-01 00:00:00"
        coords   = summary.get("coordinates")

        # Land ur Wikipedia-koordinater eller kategori (bästa effort utan gissning)
        # Vi lämnar country_id tomt om vi inte kan härleda det säkert
        vals: dict = {
            "encounter_id":   str(uuid.uuid4()),
            "title_en":       summary.get("title", title)[:200],
            "date_observed":  date_str,
            "source_ref":     source_ref,
            "description_en": extract[:500],
            "research_notes": (
                f"[SRC] Wikipedia Category:UFO sightings\n"
                f"[ARTICLE] https://en.wikipedia.org/wiki/"
                f"{urllib.parse.quote(title.replace(' ', '_'))}"
            ),
        }
        if coords:
            vals["geo_lat"] = coords["lat"]
            vals["geo_lng"] = coords["lon"]
        if wiki_db_id:
            vals["database_id"] = wiki_db_id

        if dry_run:
            if created < 5:
                print(f"  [DRY] {year} | {title[:55]}")
            created += 1
        else:
            if _create_encounter(vals, dry_run=False):
                existing_refs.add(source_ref)
                created += 1
                if created % 20 == 0:
                    print(f"  [{i}/{len(all_pages_list)}] created={created} "
                          f"skip={skipped} nodate={no_date}", flush=True)
            else:
                errors += 1

    print(f"\n  Fas 2 klar: {created} skapade | {skipped} skip | {no_date} ingen datum | {errors} fel")
    return created


# ---------------------------------------------------------------------------
# FAS 3 — Lokal Wikipedia (via Wikidata interlanguage-länkar)
# ---------------------------------------------------------------------------

def _get_local_category(en_cat_title: str, target_lang: str,
                         delay: float = 1.0) -> str | None:
    """
    Hittar lokal-wiki-ekvivalenten för en engelsk kategori
    via Wikidata sitelinks. Inga gissningar på kategorinamn.
    """
    # 1. Hämta Wikidata-ID för den engelska kategorin
    data = _wiki_api({
        "action": "query",
        "titles": f"Category:{en_cat_title}",
        "prop": "pageprops",
        "ppprop": "wikibase_item",
    }, lang="en", delay=delay)
    if not data:
        return None
    pages = data.get("query", {}).get("pages", {})
    page  = next(iter(pages.values()), {})
    qid   = page.get("pageprops", {}).get("wikibase_item")
    if not qid:
        return None

    # 2. Hämta sitelinks från Wikidata
    wd_url = (f"https://www.wikidata.org/w/api.php?"
              f"action=wbgetentities&ids={qid}&props=sitelinks&format=json")
    raw = _http_get(wd_url, delay=delay)
    if not raw:
        return None
    wd = json.loads(raw)
    sitelinks = wd.get("entities", {}).get(qid, {}).get("sitelinks", {})

    site_key = f"{target_lang}wiki"
    local = sitelinks.get(site_key, {}).get("title")
    if local:
        # Stripp "Kategori:", "Catégorie:", etc.
        return re.sub(r"^[^:]+:", "", local).strip()
    return None


# Direktkarta för kategorier som INTE har Wikidata-länk till Category:UFO sightings
# Verifierade manuellt via kategoriträdssökning
_DIRECT_CATS: dict[str, str] = {
    "fr": "Catégorie:Observation d'ovni",   # förälder, subkats per land
    "ja": "Category:未確認飛行物体",           # flat, specifika fall finns
    "pl": "Kategoria:Obserwacje UFO",        # bekräftad: Battle of LA, Kelly-Hopkinsville etc.
    "sr": "Категорија:НЛО",                 # Roswell, Shag Harbour, Varginha etc.
    "da": "Kategori:Ufo",                   # dansk kategori
    "cs": "Kategorie:UFO",                  # tjeckisk
    "hu": "Kategória:UFO",                  # ungersk
    "bg": "Категория:НЛО",                  # bulgarisk
    "sk": "Kategória:UFO",                  # slovakisk
    "sl": "Kategorija:Neznani leteči predmeti",  # slovensk
    "bs": "Kategorija:NLO",                 # bosnisk
    "mk": "Категорија:НЛО",                 # makedonisk
    # Funna via discovery-sweep
    "hr": "Kategorija:NLO",                 # kroatisk
    "my": "ကဏ္ဍ:အမျိုးအမည်မသိ ယာဉ်ပျံများ",  # burmesisk
    "jv": "Kategori:UFO",                   # javanesisk
    "kk": "Санат:Уфология",                 # kazakisk
    "kn": "ವರ್ಗ:UFOಗಳು",                   # kannada
    "nan": "Lūi-pia̍t:Ufo-ha̍k",            # min nan (taiwanesisk)
    "simple": "Category:UFOs",              # simple english
}


def run_phase3(dry_run: bool, limit: int, delay: float,
               target_langs: list[str] | None = None) -> int:
    print(f"\n{'='*60}")
    print(f"  Fas 3 — Lokal Wikipedia{' [DRY RUN]' if dry_run else ''}")
    print(f"{'='*60}")

    if target_langs is None:
        target_langs = ["sv", "no", "fi", "es", "fr", "de", "pt", "it",
                        "nl", "pl", "ru", "ja", "zh", "ar", "da",
                        "sr", "cs", "hu", "bg", "sk", "sl", "bs", "mk"]

    name_to_cid, code_to_cid, existing_refs, wiki_db_id = _load_odoo_lookups()

    ROOT_EN = "UFO sightings"
    total_created = 0

    for lang in target_langs:
        print(f"\n  --- Språk: {lang} ---")
        # Försök Wikidata-länk först, fall back på direktkarta
        local_cat = _get_local_category(ROOT_EN, lang, delay=delay)
        if not local_cat:
            local_cat = _DIRECT_CATS.get(lang)
        if not local_cat:
            print(f"  Ingen lokal kategori hittad för {lang!r}")
            continue
        print(f"  Lokal kategori: {local_cat!r}")

        all_pages = _walk_category_tree(local_cat, lang=lang, delay=delay, max_depth=2)
        print(f"  Sidor att processa: {len(all_pages)}")

        pages_list = list(all_pages)[:limit] if limit else list(all_pages)
        created = skipped = no_date = 0

        for title in pages_list:
            source_ref = f"WIKI-{lang}:{norm_title(title)}"
            if source_ref in existing_refs:
                skipped += 1
                continue

            summary = _wiki_summary(title, lang=lang, delay=delay)
            if not summary:
                skipped += 1
                continue

            extract = summary.get("extract", "")
            ym = _YEAR_RE.search(extract)
            if not ym:
                no_date += 1
                continue

            year     = int(ym.group(1))
            date_str = f"{year}-01-01 00:00:00"
            coords   = summary.get("coordinates")

            vals: dict = {
                "encounter_id":   str(uuid.uuid4()),
                "title_en":       summary.get("title", title)[:200],
                "date_observed":  date_str,
                "source_ref":     source_ref,
                "description_en": extract[:500],
                "research_notes": (
                    f"[SRC] Wikipedia ({lang}) {local_cat}\n"
                    f"[ARTICLE] https://{lang}.wikipedia.org/wiki/"
                    f"{urllib.parse.quote(title.replace(' ', '_'))}"
                ),
            }
            if coords:
                vals["geo_lat"] = coords["lat"]
                vals["geo_lng"] = coords["lon"]
            if wiki_db_id:
                vals["database_id"] = wiki_db_id

            if dry_run:
                if created < 3:
                    print(f"  [DRY/{lang}] {year} | {title[:55]}")
                created += 1
            else:
                if _create_encounter(vals, dry_run=False):
                    existing_refs.add(source_ref)
                    created += 1
                else:
                    pass

        print(f"  {lang}: {created} skapade | {skipped} skip | {no_date} ingen datum")
        total_created += created

    print(f"\n  Fas 3 totalt: {total_created} skapade")
    return total_created


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Wikipedia UAP-baseline — alla länder"
    )
    ap.add_argument("--phase",   default="all",
                    help="Vilken fas: 1, 2, 3 eller all (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit",   type=int, default=0,
                    help="Max antal encounters per fas (0=obegränsat)")
    ap.add_argument("--delay",   type=float, default=1.0,
                    help="Sekunder mellan Wikipedia-anrop (default 1.0)")
    ap.add_argument("--langs",   nargs="*",
                    help="Fas 3: specifika språkkoder (default: alla prioritetsspråk)")
    ap.add_argument("--show-state", action="store_true")
    args = ap.parse_args()

    if args.show_state:
        s = load_state()
        print(json.dumps(s, indent=2))
        sys.exit(0)

    if args.dry_run:
        print("*** DRY RUN — inga ändringar skrivs till Odoo ***\n")

    phases = {"1", "2", "3", "all"}
    if args.phase not in phases:
        ap.error(f"--phase måste vara 1, 2, 3 eller all")

    state = load_state()
    total = 0

    if args.phase in ("1", "all"):
        n = run_phase1(args.dry_run, args.limit, args.delay)
        total += n
        if not args.dry_run:
            state["phase1_done"] = True
            save_state(state)

    if args.phase in ("2", "all"):
        n = run_phase2(args.dry_run, args.limit, args.delay)
        total += n
        if not args.dry_run:
            state["phase2_done"] = True
            save_state(state)

    if args.phase in ("3", "all"):
        n = run_phase3(args.dry_run, args.limit, args.delay, args.langs)
        total += n
        if not args.dry_run:
            state["phase3_done"] = True
            save_state(state)

    print(f"\n{'='*60}")
    print(f"  Totalt skapade: {total}")
    print(f"{'='*60}")
