"""
run_full_ssf.py — Hämtar rfNumber + scrapar kontakter + pushar till Odoo per klubb.

För varje klubb:
  1. API-anrop till SiteVision → rfNumber + kontaktuppgifter
  2. Klubb med hemsida: scrapa den direkt (naturlig variabel paus)
  3. Klubb utan hemsida: kort random delay (1.0–3.0 s)
  4. Push direkt till Odoo ssf
  5. Progress sparas till progress_full.json var 10:e klubb

Avbruten körning återupptas från progress_full.json.
"""
import requests, time, json, random, re, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clio_odoo import connect

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    import anthropic
    HAS_CLAUDE = True
except ImportError:
    HAS_CLAUDE = False

BASE       = "https://varmland.skidor.com"
PAGE_ID    = "106.7756e3f1866cb6688ddfef1"
PORTLET_ID = "12.2543d89518e56b1f3e21c10d"
API        = f"{BASE}/appresource/{PAGE_ID}/{PORTLET_ID}"
SSF_DB     = "ssf"
PROGRESS   = Path(__file__).parent / "progress_full.json"
PAGE_DELAY = 4.0

FREE_DOMAINS = {
    "gmail.com", "hotmail.com", "hotmail.se", "yahoo.com", "yahoo.se",
    "live.com", "live.se", "outlook.com", "outlook.se", "telia.com",
    "tele2.se", "comhem.se", "bredband.net", "spray.se", "home.se",
    "swipnet.se", "msn.com", "icloud.com", "me.com", "mac.com",
    "glocalnet.net", "tiscali.se", "passagen.se",
}

CONTACT_PATHS = [
    "/styrelse", "/om-oss/styrelse", "/kontakt", "/kontakta-oss",
    "/om-oss", "/om-klubben", "/foreningen", "/om-foreningen",
    "/organisation", "/",
]

CLAUDE_PROMPT = (
    "Du är ett verktyg för att extrahera kontaktpersoner ur text från en idrottsklubb.\n"
    "Extrahera ALLA personer med namn och roll som nämns i texten nedan.\n"
    "Returnera ENBART ett JSON-objekt:\n"
    '{"kontakter": [{"namn": "...", "roll": "...", "epost": "...", "telefon": "..."}]}\n'
    "Om ett fält saknas, sätt det till null.\n"
    "Roller ska vara på svenska (Ordförande, Sekreterare, Kassör, Ledamot, etc.).\n"
    "Inkludera BARA faktiska personer med namn.\n\nText:\n"
)


# ── HTTP-helpers ─────────────────────────────────────────────────────────────

def _api_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (clio-ssf-klubb/1.0)",
        "Referer": BASE + "/distrikt/varmland/kontakta-oss-klubbar/hitta-klubb",
    })
    s.get(BASE + "/distrikt/varmland/kontakta-oss-klubbar/hitta-klubb", timeout=10)
    return s


def _get_api(session, url, params, retries=4):
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 429 or r.status_code >= 500:
                wait = 2 ** (attempt + 3)
                print(f"  HTTP {r.status_code} — backoff {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            wait = 2 ** (attempt + 3)
            print(f"  Nätverksfel: {e} — väntar {wait}s")
            time.sleep(wait)
    raise RuntimeError("Misslyckades efter max retries")


def _free_domain(email):
    if not email or "@" not in email:
        return True
    domain = email.split("@")[1].lower().strip()
    return any(domain == d or domain.endswith("." + d) for d in FREE_DOMAINS)


# ── Webscraping ──────────────────────────────────────────────────────────────

def _fetch_text_inner(url, session):
    if HAS_TRAFILATURA:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_links=False, include_tables=True)
            if text and len(text) > 100:
                return text
    r = session.get(url, timeout=10)
    if r.status_code == 200:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)[:5000]
    return None


def _fetch_text(url, session, timeout=8):
    """Hämtar text med hård timeout — trafilatura saknar inbyggd timeout.
    shutdown(wait=False) så att hangande trådar inte blockerar huvudloopen."""
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        future = ex.submit(_fetch_text_inner, url, session)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            future.cancel()
            return None
    except Exception:
        return None
    finally:
        ex.shutdown(wait=False)


def _extract_with_claude(text):
    if not HAS_CLAUDE:
        return []
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": CLAUDE_PROMPT + text[:4000]}],
        )
        raw = msg.content[0].text.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group()).get("kontakter", [])
    except Exception as e:
        print(f"    Claude-fel: {e}")
    return []


def scrape_club_site(base_url, web_session):
    best_text = ""
    best_url  = ""
    for path in CONTACT_PATHS:
        url  = urljoin(base_url, path)
        text = _fetch_text(url, web_session)
        if text and len(text) > len(best_text):
            best_text = text
            best_url  = url
            if "styrelse" in path or len(best_text) > 500:
                break
    if not best_text:
        return []
    kontakter = _extract_with_claude(best_text) if HAS_CLAUDE else []
    for k in kontakter:
        k["kalla_url"] = best_url
    return kontakter


# ── Sidladdning ──────────────────────────────────────────────────────────────

def fetch_all_raw(api_session):
    r = _get_api(api_session, f"{API}/search",
                 {"query": "", "districtId": "", "municipality": "", "subSport": "", "page": "0"})
    data        = r.json()["organisations"]
    total_pages = data["totalPages"]
    total       = data["totalElements"]
    clubs_raw   = list(data["organisations"])
    print(f"Totalt {total} klubbar över {total_pages} sidor")
    for page in range(1, total_pages):
        time.sleep(PAGE_DELAY)
        r = _get_api(api_session, f"{API}/search",
                     {"query": "", "districtId": "", "municipality": "", "subSport": "", "page": str(page)})
        clubs_raw.extend(r.json()["organisations"]["organisations"])
        print(f"  Sida {page + 1}/{total_pages}: {len(clubs_raw)} hämtade")
    return clubs_raw


# ── Odoo-helpers ─────────────────────────────────────────────────────────────

def _odoo_upsert_club(Partner, tag_id, uuid, rf, name, email, homepage):
    vals = {
        "ref":         rf,
        "email":       email or "",
        "website":     homepage or "",
        "category_id": [(4, tag_id)],
    }
    rows = Partner.search_read([("ref", "=", uuid), ("is_company", "=", True)], ["id"])
    if not rows:
        rows = Partner.search_read([("ref", "=", rf),   ("is_company", "=", True)], ["id"])
    if not rows:
        rows = Partner.search_read([("name", "=", name), ("is_company", "=", True)], ["id"])
    if rows:
        pid = rows[0]["id"]
        Partner.write([pid], vals)
        return pid
    return None


def _odoo_upsert_persons(Partner, tag_id, pid, kontakter):
    count = 0
    for k in kontakter:
        namn = (k.get("namn") or "").strip()
        if not namn:
            continue
        pvals = {
            "name":       namn,
            "is_company": False,
            "parent_id":  pid,
            "function":   k.get("roll") or "",
            "email":      k.get("epost") or "",
            "phone":      k.get("telefon") or "",
        }
        ex = Partner.search_read(
            [("name", "=", namn), ("parent_id", "=", pid), ("is_company", "=", False)], ["id"])
        if ex:
            Partner.write([ex[0]["id"]], pvals)
        else:
            Partner.create(pvals).id
            count += 1
    return count


# ── Huvudloop ────────────────────────────────────────────────────────────────

def run(clubs_raw, api_session, existing=None):
    done    = dict(existing or {})
    already = len(done)
    if already:
        print(f"  Återupptar: {already} av {len(clubs_raw)} redan behandlade")

    to_do       = [c for c in clubs_raw if c["id"] not in done]
    total       = len(clubs_raw)
    web_session = requests.Session()
    web_session.headers.update({"User-Agent": "Mozilla/5.0 (clio-ssf-klubb/1.0)"})

    print(f"Ansluter till Odoo {SSF_DB}...")
    env      = connect(db=SSF_DB)
    Partner  = env["res.partner"]
    TagModel = env["res.partner.category"]
    tags     = TagModel.search_read([("name", "=", "SSF-Klubb")], ["id"])
    tag_id   = tags[0]["id"] if tags else TagModel.create({"name": "SSF-Klubb"})

    stats = {"updated": 0, "persons": 0, "missing": 0}

    for i, c in enumerate(to_do, 1):
        uuid = c["id"]
        name = c.get("name", "?")
        try:
            # 1. Detalj från API
            r   = _get_api(api_session, f"{API}/organisation", {"organisationId": uuid})
            det = r.json().get("organisation", {})
            rf  = det.get("rfNumber", "")

            contacts = det.get("contactDetails", [])
            email    = next((x["value"] for x in contacts if x.get("type") == "EMAIL"), "")
            homepage = next((x["value"] for x in contacts if x.get("type") == "HOMEPAGE"), "")
            if homepage and not homepage.startswith("http"):
                homepage = "https://" + homepage

            domain = None
            if homepage:
                domain = urlparse(homepage).netloc or homepage
            elif email and not _free_domain(email):
                domain = email.split("@")[1]
                homepage = f"https://{domain}"

            has_site = bool(domain and not _free_domain(email or ""))

            # 2. Scrapa hemsida (naturlig paus) eller random delay
            kontakter = []
            if has_site:
                print(f"  [{already + i}/{total}] {name} → scrapar {homepage}")
                kontakter = scrape_club_site(homepage, web_session)
                print(f"    {len(kontakter)} kontakter, rfNumber={rf or '(saknas)'}")
            else:
                delay = random.uniform(1.0, 3.0)
                print(f"  [{already + i}/{total}] {name} (ingen hemsida, {delay:.1f}s)")
                time.sleep(delay)

            # 3. Push direkt till Odoo
            if rf:
                pid = _odoo_upsert_club(Partner, tag_id, uuid, rf, name, email, homepage)
                if pid:
                    stats["updated"] += 1
                    stats["persons"] += _odoo_upsert_persons(Partner, tag_id, pid, kontakter)
                else:
                    stats["missing"] += 1
            else:
                stats["missing"] += 1

            done[uuid] = {
                "rfNumber": rf, "name": name,
                "email": email, "homepage": homepage,
                "kontakter": kontakter,
            }

            if i % 10 == 0:
                PROGRESS.write_text(json.dumps(done, ensure_ascii=False, indent=2))
                print(f"  --- [{already + i}/{total}] sparat | klubbar={stats['updated']} personer={stats['persons']} ---")

        except Exception as e:
            print(f"  FEL {name}: {e} — fortsätter")

    PROGRESS.write_text(json.dumps(done, ensure_ascii=False, indent=2))
    print(f"\n=== Slutresultat ===")
    print(f"Klubbar uppdaterade: {stats['updated']}")
    print(f"Personer skapade:    {stats['persons']}")
    print(f"Ej hittade/rf:       {stats['missing']}")
    return done


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    existing = {}
    if PROGRESS.exists():
        existing = json.loads(PROGRESS.read_text())
        print(f"Hittade progress-fil: {len(existing)} klubbar behandlade")

    api_session = _api_session()

    print("Steg 1: Hämtar klubblista...")
    clubs_raw = fetch_all_raw(api_session)

    remaining = len(clubs_raw) - len(existing)
    print(f"\nSteg 2: Behandlar {remaining} klubbar — scrapar + pushar till Odoo per klubb...")
    run(clubs_raw, api_session, existing)

    print("\nKlart!")
