"""
uap_import_geipan.py — GEIPAN (CNES) case importer

Hämtar UAP-fall från den franska rymdmyndigheten CNES/GEIPAN.
Deduplicering via source_ref-fältet på uap.encounter ("GEIPAN:{case_id}").
Sidfönster-logik: state-fil trackar nästa sida att hämta, så varje
nattlig körning bearbetar ett begränsat antal sidor och avancerar
räknaren. En fullständig cykel (alla ~559 sidor) tar ~56 nätter vid
10 sidor/natt.

Kör: python3 uap_import_geipan.py [--dry-run] [--pages N] [--class D D1 D2]
     python3 uap_import_geipan.py --reset-state          # börja om från sida 0
     python3 uap_import_geipan.py --migrate-source-ref   # sätt source_ref på gamla poster
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.request, urllib.parse, uuid, xmlrpc.client
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = "uapdb"
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

GEIPAN_BASE   = "https://www.cnes-geipan.fr"
GEIPAN_SEARCH = GEIPAN_BASE + "/fr/recherche/cas"
GEIPAN_CASE   = GEIPAN_BASE + "/fr/cas/{}"
USER_AGENT    = "clio-uap-research/1.0 (contact: research@arvas.international)"

# Taxonomy IDs för klassificeringar på GEIPAN
CLASS_IDS = {"A": "11", "B": "12", "C": "13", "D": "14", "D1": "15", "D2": "16"}

# GEIPAN-klassificering → credibility-kommentar
CLASS_NOTES = {
    "A":  "GEIPAN klass A: identifierat fenomen",
    "B":  "GEIPAN klass B: troligen identifierat",
    "C":  "GEIPAN klass C: otillräckligt underlag",
    "D":  "GEIPAN klass D: oidentifierat fenomen",
    "D1": "GEIPAN klass D1: oidentifierat, god datakvalitet",
    "D2": "GEIPAN klass D2: oidentifierat, lägre datakvalitet",
}

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


def get_or_create_database() -> int:
    """Hämtar eller skapar uap.database-posten för GEIPAN."""
    existing = kw("uap.database", "search_read",
                  [[["name", "=", "GEIPAN"]]],
                  {"fields": ["id"], "limit": 1})
    if existing:
        return existing[0]["id"]
    db_id = kw("uap.database", "create", [{
        "name":        "GEIPAN",
        "db_url":      "https://www.cnes-geipan.fr",
        "description": (
            "Groupe d'Études et d'Informations sur les Phénomènes Aérospatiaux "
            "Non identifiés — CNES (Frankrike). Officiell statlig UAP-utredningsenhet."
        ),
    }])
    print(f"  Skapade uap.database: GEIPAN (id={db_id})")
    return db_id


def get_france_id() -> int:
    """Hämtar res.country-ID för Frankrike."""
    countries = kw("res.country", "search_read",
                   [[["code", "=", "FR"]]],
                   {"fields": ["id"], "limit": 1})
    if not countries:
        sys.exit("Frankrike (FR) hittades inte i res.country")
    return countries[0]["id"]


# ---------------------------------------------------------------------------
# State-hantering (sidfönster)
# ---------------------------------------------------------------------------

STATE_FILE = Path(__file__).parent / ".geipan_state.json"

def load_state() -> dict:
    """Läser state-fil. Returnerar defaults om filen saknas."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"next_page": 0, "total_pages": None, "total_imported": 0, "last_run": None}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))

def print_state() -> None:
    s = load_state()
    print("State-fil:", STATE_FILE)
    for k, v in s.items():
        print(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# Migrering — sätt source_ref på befintliga GEIPAN-poster
# ---------------------------------------------------------------------------

def migrate_source_ref(db_id: int) -> None:
    """Sätter source_ref på gamla GEIPAN-poster som saknar det."""
    missing = kw("uap.encounter", "search_read",
                 [[["database_id", "=", db_id], ["source_ref", "=", False]]],
                 {"fields": ["id", "title_en"], "limit": 10000})
    print(f"  Poster utan source_ref: {len(missing)}")
    updated = 0
    for enc in missing:
        m = re.search(r"GEIPAN-([\w-]+)", enc.get("title_en") or "")
        if m:
            ref = f"GEIPAN:{m.group(1)}"
            kw("uap.encounter", "write", [[enc["id"]], {"source_ref": ref}])
            updated += 1
    print(f"  Uppdaterade: {updated}")


# ---------------------------------------------------------------------------
# HTTP-hjälpfunktioner
# ---------------------------------------------------------------------------

def _fetch(url: str, delay: float = 0.0) -> str | None:
    """Hämtar HTML-sida som sträng. Returnerar None vid fel."""
    if delay:
        time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404):
                return None
            raise
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            if attempt == 0:
                time.sleep(5)
                continue
            print(f"  [WARN] nätverksfel: {e}")
            return None
    return None


# ---------------------------------------------------------------------------
# Paginering — hämta alla case-URLer
# ---------------------------------------------------------------------------

def fetch_case_urls(
    classifications: list[str],
    start_page: int = 0,
    max_pages: int | None = None,
    delay: float = 1.0,
) -> tuple[list[str], int]:
    """
    Hämtar case-URLer för angivna klassificeringar, börjar från start_page.

    Returnerar (urls, sista_hämtade_sida+1) — dvs nästa sida att hämta.
    Om vi nått sista sidan returneras 0 (wrap-around).
    """
    class_params = "&".join(
        f"field_classification_des_cas_target_id[]={CLASS_IDS[c]}"
        for c in classifications
        if c in CLASS_IDS
    )

    urls: list[str] = []
    page = start_page
    pages_fetched = 0

    while True:
        if max_pages is not None and pages_fetched >= max_pages:
            break

        search_url = f"{GEIPAN_SEARCH}?{class_params}&page=%2C{page}"
        html = _fetch(search_url, delay=delay if pages_fetched > 0 else 0.0)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")
        links = soup.find_all("a", href=re.compile(r"/fr/cas/[\w-]+"))
        if not links:
            break

        for link in links:
            path = link["href"].split("?")[0]
            full = GEIPAN_BASE + path
            if full not in urls:
                urls.append(full)

        pages_fetched += 1
        page += 1

        # Sista sidan? Returnera 0 (nästa körning börjar om från start)
        next_li = soup.find("li", class_="pager__item--next")
        if not next_li:
            return urls, 0   # wrap-around

    return urls, page   # nästa sida att hämta


# ---------------------------------------------------------------------------
# Case-parsering
# ---------------------------------------------------------------------------

def parse_case(url: str, delay: float = 1.0) -> dict | None:
    """Hämtar och tolkar ett enskilt GEIPAN-case. Returnerar dict med fält."""
    html = _fetch(url, delay=delay)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Extrahera text från hela sidan (strippad)
    full_text = soup.get_text(separator=" ", strip=True)

    # Case-ID ur URL
    case_id = url.rstrip("/").split("/")[-1]   # e.g. "2023-12-51504"

    # Plocka ut cas-blocket via samlad regex på det specifika mönstret i GEIPAN-sidor:
    # "COMMUNE (DEP_CODE) DD.MM.YYYY Date d'observation DD/MM/YYYY Région X Département Y Classification Z"
    cas_m = re.search(
        r"([A-ZÀÂÉÈÊËÎÏÔÙÛÜÇ][A-Z0-9À-Ÿ\s'\-]+?)\s*"   # COMMUNE
        r"\(\d{2,3}\)\s*\d{2}\.\d{2}\.\d{4}\s*"           # (code) DD.MM.YYYY
        r"Date d.observation\s*([\d/]+)\s*"                # Date d'observation DD/MM/YYYY
        r"R.gion\s+([^C]+?)\s*"                            # Région X
        r"D.partement\s+([^C]+?)\s*"                       # Département Y
        r"Classification\s+(D1|D2|D|A|B|C)\b",            # Classification Z
        full_text, re.IGNORECASE
    )
    if cas_m:
        commune        = cas_m.group(1).strip().title()
        date_obs_raw   = cas_m.group(2).strip()
        region_fr      = cas_m.group(3).strip()
        departement    = cas_m.group(4).strip()
        classification = cas_m.group(5).upper()
        date_parsed    = _parse_date(date_obs_raw)
        location       = f"{commune}, {departement}"
    else:
        # Fallback: extrahera separat
        date_obs       = _extract_labeled(full_text, "Date d'observation")
        date_parsed    = _parse_date(date_obs)
        classification = None
        region_fr      = _extract_labeled(full_text, "Région")
        departement    = _extract_labeled(full_text, "Département")
        location       = departement  # minimalt fallback
        # Klassificering via kontextuell regex
        cm = re.search(r"Département\s+(\S+)\s+Classification\s+(D1|D2|D|A|B|C)\b", full_text)
        if cm:
            departement    = cm.group(1).strip()
            classification = cm.group(2).upper()
        # Kommunnamn: leta efter STORE_BOKSTÄVER (dept_code) DD.MM.YYYY
        comm_m = re.search(r"([A-ZÀÂÉÈÊ\-]{3,}(?:\s+[A-ZÀÂÉÈÊ\-]+)*)\s*\(\d{2,3}\)\s*\d{2}\.\d{2}\.\d{4}", full_text)
        if comm_m:
            commune    = comm_m.group(1).strip().title()
            location   = f"{commune}, {departement}" if departement else commune

    # Städa location
    location = _clean_location(location)

    # Étrangeté och Consistance
    strangeness  = _extract_float(full_text, "Etrangeté") or _extract_float(full_text, "Étrangeté")
    consistency  = _extract_float(full_text, "Consistance")

    # Résumé
    resume = _extract_section(full_text, "Résumé", stop_words=["Desc", "Description", "Analyse"])

    # Typ av fenomen
    phenomenon = _extract_labeled(full_text, "Type de phénomène")

    # Bygg research_notes
    notes_parts = [f"[GEIPAN] Case ID: {case_id}"]
    if classification:
        notes_parts.append(CLASS_NOTES.get(classification, f"GEIPAN klass: {classification}"))
    if strangeness is not None:
        notes_parts.append(f"Étrangeté: {strangeness:.2f}")
    if consistency is not None:
        notes_parts.append(f"Consistance: {consistency:.2f}")
    if phenomenon:
        notes_parts.append(f"Type: {phenomenon}")
    if resume:
        notes_parts.append(f"Résumé: {resume}")
    notes = "\n".join(notes_parts)

    return {
        "case_id":        case_id,
        "date_parsed":    date_parsed,
        "classification": classification,
        "region_fr":      region_fr,
        "departement":    departement,
        "location":       location,
        "strangeness":    strangeness,
        "consistency":    consistency,
        "resume":         resume,
        "notes":          notes,
        "url":            url,
    }


def _clean_location(loc: str | None) -> str | None:
    """Tar bort navigationstext och stopp-ord som läcker in i location-strängen."""
    if not loc:
        return None
    # Ta bort allt efter kända stopp-ord
    for stop in ["Classification", "Date de", "Type de", "Phénomène"]:
        idx = loc.find(stop)
        if idx > 0:
            loc = loc[:idx]
    # Ta bort kända navigationsprefixer
    loc = re.sub(r"(?i)^(Recherche[^,]*\s+)", "", loc)
    loc = re.sub(r"(?i)^(Arrow[^,]*\s+)", "", loc)
    return loc.strip(" ,") or None


def _extract_labeled(text: str, label: str) -> str | None:
    """Extraherar värdet som följer direkt efter en label i ren text."""
    idx = text.find(label)
    if idx < 0:
        return None
    after = text[idx + len(label):idx + len(label) + 200].strip()
    # Ta första "meningsfulla" blocket (upp till nästa kända label)
    m = re.match(r"^([^\n]{1,100})", after)
    return m.group(1).strip() if m else None


def _extract_float(text: str, label: str) -> float | None:
    """Extraherar ett decimaltal som följer efter en label."""
    idx = text.find(label)
    if idx < 0:
        return None
    after = text[idx + len(label):idx + len(label) + 30]
    m = re.search(r"(\d+[.,]\d+)", after)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _extract_section(text: str, label: str, stop_words: list[str]) -> str | None:
    """Extraherar ett textstycke som börjar vid label och slutar vid stop_words."""
    idx = text.find(label)
    if idx < 0:
        return None
    start = idx + len(label)
    end = len(text)
    for sw in stop_words:
        sw_idx = text.find(sw, start)
        if 0 < sw_idx < end:
            end = sw_idx
    snippet = text[start:end].strip()
    return snippet[:1000] if snippet else None


def _parse_date(date_str: str | None) -> str | None:
    """Omvandlar DD/MM/YYYY till Odoo datetime-format."""
    if not date_str:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)} 00:00:00"
    return None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(
    classifications: list[str],
    pages_per_run:   int,
    delay:           float,
    dry_run:         bool,
):
    state     = load_state()
    start_pg  = state.get("next_page", 0)

    print(f"\n{'='*60}")
    print(f"  GEIPAN Importer  {'[DRY RUN] ' if dry_run else ''}")
    print(f"  Klassificeringar : {', '.join(classifications)}")
    print(f"  Sidor denna körning: {pages_per_run} (från sida {start_pg})")
    print(f"  Delay: {delay}s")
    print(f"{'='*60}")

    db_id     = get_or_create_database()
    france_id = get_france_id()
    print(f"  GEIPAN db_id={db_id}, France country_id={france_id}")

    # --- Deduplicering via source_ref (indexerat fält) ---
    existing_raw = kw("uap.encounter", "search_read",
                      [[["database_id", "=", db_id], ["source_ref", "!=", False]]],
                      {"fields": ["source_ref"], "limit": 50000})
    existing_refs: set[str] = {enc["source_ref"] for enc in existing_raw}
    print(f"  Befintliga GEIPAN-poster (source_ref): {len(existing_refs)}")

    # --- Hämta case-URLer för detta sidfönster ---
    print(f"\n  Hämtar sidor {start_pg}–{start_pg + pages_per_run - 1}...")
    case_urls, next_page = fetch_case_urls(
        classifications,
        start_page=start_pg,
        max_pages=pages_per_run,
        delay=delay,
    )
    wrapped = next_page == 0 and start_pg > 0
    print(f"  Hittade {len(case_urls)} case-URLer "
          f"| nästa sida: {next_page}{'  (wrap → börjar om)' if wrapped else ''}")

    created = skipped = errors = 0
    t0 = time.time()

    for i, url in enumerate(case_urls, 1):
        case_id = url.rstrip("/").split("/")[-1]
        ref     = f"GEIPAN:{case_id}"

        if ref in existing_refs:
            skipped += 1
            continue

        data = parse_case(url, delay=delay)
        if not data:
            errors += 1
            continue

        if dry_run:
            print(f"\n  [DRY] {case_id}")
            print(f"        Date:   {data['date_parsed']}")
            print(f"        Class:  {data['classification']}")
            print(f"        Loc:    {data['location']}")
            print(f"        Étr:    {data['strangeness']} | Con: {data['consistency']}")
            print(f"        Résumé: {(data['resume'] or '')[:80]!r}")
            created += 1
        else:
            try:
                vals: dict = {
                    "encounter_id":         str(uuid.uuid4()),
                    "source_ref":           ref,
                    "title_en":             f"GEIPAN-{case_id}",
                    "title_original":       f"GEIPAN cas {case_id}",
                    "description_original": data["resume"] or "",
                    "language_original":    "fr",
                    "database_id":          db_id,
                    "country_id":           france_id,
                    "region":               "europe",
                    "official_response":    "D",
                    "discourse_level":      "4",
                    "research_notes":       data["notes"],
                    "status":               "pending",
                }
                if data["date_parsed"]:
                    vals["date_observed"] = data["date_parsed"]
                if data["location"]:
                    vals["location"] = data["location"]

                kw("uap.encounter", "create", [vals])
                created += 1
                existing_refs.add(ref)

                if i % 10 == 0:
                    elapsed = time.time() - t0
                    rate    = i / elapsed if elapsed > 0 else 0
                    eta     = (len(case_urls) - i) / rate if rate > 0 else 0
                    print(f"  [{i}/{len(case_urls)}] skapade={created} "
                          f"skip={skipped} fel={errors} | "
                          f"ETA {eta/60:.1f}min", flush=True)

            except Exception as e:
                print(f"  FEL {case_id}: {e}")
                errors += 1

    elapsed = time.time() - t0

    # --- Spara state ---
    if not dry_run:
        state["next_page"]      = next_page
        state["last_run"]       = datetime.now().isoformat(timespec="seconds")
        state["total_imported"] = state.get("total_imported", 0) + created
        save_state(state)

    print(f"\n{'='*60}")
    print(f"  Skapade       : {created}")
    print(f"  Hoppade       : {skipped} (redan importerade)")
    print(f"  Fel           : {errors}")
    print(f"  Tid           : {elapsed:.1f}s")
    print(f"  Nästa sida    : {next_page} {'(wrap-around)' if wrapped else ''}")
    if not dry_run:
        total_geipan = kw("uap.encounter", "search_count",
                          [[["database_id", "=", db_id]]])
        print(f"  Totalt GEIPAN : {total_geipan}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run",          action="store_true")
    ap.add_argument("--pages",            type=int, default=10,
                    help="Antal sidor att hämta per körning (default 10, ~60 cases)")
    ap.add_argument("--delay",            type=float, default=1.5,
                    help="Sekunder mellan anrop (default 1.5)")
    ap.add_argument("--class",            dest="classifications",
                    nargs="+",
                    default=["A", "B", "C", "D", "D1", "D2"],
                    choices=list(CLASS_IDS.keys()),
                    help="GEIPAN-klassificeringar (default: alla)")
    ap.add_argument("--reset-state",      action="store_true",
                    help="Nollställ state-fil och börja om från sida 0")
    ap.add_argument("--show-state",       action="store_true",
                    help="Visa nuvarande state och avsluta")
    ap.add_argument("--migrate-source-ref", action="store_true",
                    help="Sätt source_ref på befintliga GEIPAN-poster utan det")
    args = ap.parse_args()

    if args.show_state:
        print_state()
        sys.exit(0)

    if args.reset_state:
        save_state({"next_page": 0, "total_pages": None, "total_imported": 0, "last_run": None})
        print("State nollställd — nästa körning börjar från sida 0.")
        sys.exit(0)

    if args.migrate_source_ref:
        db_id = get_or_create_database()
        print(f"Migrerar source_ref för GEIPAN db_id={db_id}...")
        migrate_source_ref(db_id)
        sys.exit(0)

    if args.dry_run:
        print("*** DRY RUN ***")

    run(args.classifications, args.pages, args.delay, args.dry_run)
