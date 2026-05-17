#!/usr/bin/env python3
"""
migrate_notion_to_odoo.py -- Migrerar Arvas Familjebibliotek fran Notion till Odoo 19

Laser:
  Bokregister (Notion DB 94906f71-ee0f-4ff8-8c4b-28e822f6e670)
    Falt: Titel, Forfattare, Forfattare_Enamn, Forfattare_Fnamn, ISBN, Forlag, Ar, Sprak, Format
  Betyg (Notion DB 41009da8-a1e7-48e2-9ed9-7f3c9406ef93)
    Falt: BOK-ID, Person, Betyg, Anteckning, Datum last

For rattning av betyg kravs bokid_cache.json (fran clio-library/import_books.py).
Utan cache-filen importeras bara bocker.

Skriver:
  library.book   (Odoo)
  library.rating (Odoo)

Miljoevariabler (laddas fran clio-tools/.env):
  NOTION_TOKEN         -- Notion integration token
  ODOO_ADMIN_PASSWORD  -- Odoo admin-loesenord (eller ange via prompt)

Anvandning:
  python migrate_notion_to_odoo.py --dry-run
  python migrate_notion_to_odoo.py --odoo-db aiab19
  python migrate_notion_to_odoo.py --odoo-db aiab19 --books-only
  python migrate_notion_to_odoo.py --odoo-db aiab19 --ratings-only
  python migrate_notion_to_odoo.py --list-persons
"""

import argparse
import json
import logging
import os
import re
import time
import urllib.request
import urllib.error
import xmlrpc.client
from pathlib import Path


# --- ENV ----------------------------------------------------------------------
def _load_dotenv():
    for candidate in [
        Path(__file__).parent.parent / ".env",
        Path("/home/clioadmin/clio-tools/.env"),
        Path(__file__).parent / ".env",
        Path.home() / ".env",
    ]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val


_load_dotenv()


# --- CONFIG -------------------------------------------------------------------
NOTION_API     = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
BOKREGISTER_DB = "94906f71-ee0f-4ff8-8c4b-28e822f6e670"
BETYG_DB       = "41009da8-a1e7-48e2-9ed9-7f3c9406ef93"

ODOO_URL  = "http://localhost:8079"
ODOO_USER = "admin"

# Mappa Notion person-namn -> Odoo login.
# Kor --list-persons for att se vilka namn som finns i Notion.
PERSON_MAP = {
    "Fredrik": "admin",
    "Ulrika":  "ulrika",
    "Alice":   "alice",
    "Johan":   "johan",
}

HERE     = Path(__file__).parent
LOG_FILE = HERE / "migrate_notion_to_odoo.log"
CACHE_FILE = HERE / "bokid_cache.json"


# --- LOGGING ------------------------------------------------------------------
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", "%H:%M:%S")
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(ch)
    logger.addHandler(fh)


# --- NOTION API ---------------------------------------------------------------
def notion_request(method, path, token, body=None):
    url  = f"{NOTION_API}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization":  f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type":   "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        logging.error("Notion %s %s: HTTP %d %s", method, path, e.code, e.read().decode()[:200])
        return {}


def notion_query_all(token, db_id):
    pages, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        result = notion_request("POST", f"/databases/{db_id}/query", token, body)
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        time.sleep(0.15)
    return pages


def prop_text(page, name):
    p = page.get("properties", {}).get(name, {})
    t = p.get("type", "")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in p.get("title", [])).strip()
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in p.get("rich_text", [])).strip()
    return ""


def prop_select(page, name):
    p = page.get("properties", {}).get(name, {})
    return (p.get("select") or {}).get("name", "")


def prop_number(page, name):
    p = page.get("properties", {}).get(name, {})
    return p.get("number")


def prop_date(page, name):
    p = page.get("properties", {}).get(name, {})
    d = p.get("date") or {}
    return d.get("start", "")   # format "2024-03-15"


# --- BOKID-CACHE --------------------------------------------------------------
def load_bokid_cache():
    if CACHE_FILE.exists():
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        # Inverterad: BOK-ID -> normalized_key
        return {v: k for k, v in data.items()}
    return {}


def normalize_key(titel, forfattare):
    t = re.sub(r"[^\w\s]", "", titel.lower()).strip()
    a = re.sub(r"[^\w\s]", "", forfattare.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    a = re.sub(r"\s+", " ", a)
    return f"{t}||{a}"


# --- NOTION DATA --------------------------------------------------------------
def fetch_books(token):
    """Hamtar bocker fran Notion Bokregister. Faltnamn med svenska tecken."""
    logging.info("Hamtar bocker fran Notion Bokregister...")
    pages = notion_query_all(token, BOKREGISTER_DB)
    logging.info("  %d sidor hamtade", len(pages))

    books = []
    for page in pages:
        # Faltnamn matchar exakt Notion-schemat (med svenska tecken)
        titel = prop_text(page, "Titel")
        if not titel:
            continue
        author = prop_text(page, "Författare")   # Forfattare
        books.append({
            "notion_id":   page["id"],
            "name":        titel,
            "author":      author,
            "author_last": prop_text(page, "Författare_Enamn"),
            "author_first":prop_text(page, "Författare_Fnamn"),
            "isbn":        prop_text(page, "ISBN"),
            "year":        prop_number(page, "År") or 0,    # Ar
            "publisher":   prop_text(page, "Förlag"),       # Forlag
            "language":    prop_select(page, "Språk"),      # Sprak
            "format":      prop_select(page, "Format"),
            "norm_key":    normalize_key(titel, author),
        })
    logging.info("  %d giltiga bocker", len(books))
    return books


def fetch_ratings(token):
    """Hamtar betyg fran Notion Betyg."""
    logging.info("Hamtar betyg fran Notion Betyg...")
    pages = notion_query_all(token, BETYG_DB)
    logging.info("  %d sidor hamtade", len(pages))

    ratings = []
    for page in pages:
        bok_id  = prop_text(page, "BOK-ID")
        person  = prop_select(page, "Person")
        betyg   = prop_number(page, "Betyg")
        if not bok_id or not person or betyg is None:
            continue
        ratings.append({
            "bok_id":    bok_id,
            "person":    person,
            "rating":    int(betyg),
            "notes":     prop_text(page, "Anteckning"),
            "date_read": prop_date(page, "Datum läst"),  # Datum last
        })
    logging.info("  %d giltiga betyg", len(ratings))
    return ratings


def list_persons(token):
    pages = notion_query_all(token, BETYG_DB)
    persons = {}
    for page in pages:
        p = prop_select(page, "Person")
        if p:
            persons[p] = persons.get(p, 0) + 1
    return persons


# --- ODOO XML-RPC -------------------------------------------------------------
def odoo_connect(db, password):
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(db, ODOO_USER, password, {})
    if not uid:
        raise RuntimeError(f"Odoo-autentisering misslyckades for db={db} user={ODOO_USER}")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    logging.info("Ansluten till Odoo %s (uid=%d)", db, uid)
    return uid, models, db, password


def odoo_search_read(models, db, uid, pwd, model, domain, fields):
    return models.execute_kw(db, uid, pwd, model, "search_read", [domain], {"fields": fields})


def odoo_create(models, db, uid, pwd, model, vals):
    return models.execute_kw(db, uid, pwd, model, "create", [vals])


# --- IMPORT BOCKER ------------------------------------------------------------
def import_books(models, db, uid, pwd, books, dry_run):
    logging.info("\n-- Importerar bocker till Odoo --")

    existing = odoo_search_read(models, db, uid, pwd, "library.book", [], ["name", "author"])
    existing_keys = {normalize_key(r["name"], r.get("author") or ""): r["id"] for r in existing}
    logging.info("  %d bocker finns redan i Odoo", len(existing_keys))

    # Returnerar norm_key -> Odoo book_id for rattning
    norm_key_to_odoo_id = dict(existing_keys)

    created = skipped = errors = 0

    for book in books:
        nk = book["norm_key"]

        if nk in existing_keys:
            norm_key_to_odoo_id[nk] = existing_keys[nk]
            skipped += 1
            continue

        vals = {
            "name":         book["name"],
            "author":       book["author"] or False,
            "author_last":  book["author_last"] or False,
            "author_first": book["author_first"] or False,
            "isbn":         book["isbn"] or False,
            "publisher":    book["publisher"] or False,
            "year":         int(book["year"]) if book["year"] else 0,
            "language":     book["language"] or False,
            "format":       book["format"] or False,
        }

        if dry_run:
            logging.info("  DRY: skulle skapat %s", book["name"][:60])
            created += 1
            continue

        try:
            new_id = odoo_create(models, db, uid, pwd, "library.book", vals)
            norm_key_to_odoo_id[nk] = new_id
            logging.info("  Skapad: id=%d  %s", new_id, book["name"][:55])
            created += 1
        except Exception as e:
            logging.error("  FEL vid skapande av '%s': %s", book["name"], e)
            errors += 1

    logging.info("  Bocker: skapad=%d, hoppade=%d, fel=%d", created, skipped, errors)
    return norm_key_to_odoo_id


# --- IMPORT BETYG -------------------------------------------------------------
def import_ratings(models, db, uid, pwd, ratings, norm_key_to_odoo_id, bokid_cache, dry_run):
    logging.info("\n-- Importerar betyg till Odoo --")

    if not bokid_cache:
        logging.warning("  bokid_cache.json saknas -- kan inte losa BOK-ID till boktitlar")
        logging.warning("  Kopiera bokid_cache.json fran lokal clio-library-katalog till servern")
        logging.warning("  Betyg hoppas over.")
        return

    users = odoo_search_read(models, db, uid, pwd, "res.users", [], ["login", "name"])
    user_by_login = {u["login"]: u["id"] for u in users}
    user_by_name  = {u["name"]:  u["id"] for u in users}

    existing_ratings = odoo_search_read(
        models, db, uid, pwd, "library.rating", [], ["book_id", "user_id"]
    )
    existing_pairs = {(r["book_id"][0], r["user_id"][0]) for r in existing_ratings}
    logging.info("  %d betyg finns redan i Odoo", len(existing_pairs))

    created = skipped = errors = unmapped = no_book = 0
    unknown_persons = set()

    for r in ratings:
        bok_id = r["bok_id"]
        person = r["person"]

        # Losa BOK-ID till normalized_key via cache
        norm_key = bokid_cache.get(bok_id)
        if not norm_key:
            logging.debug("  BOK-ID %s finns inte i cache", bok_id)
            no_book += 1
            continue

        odoo_book_id = norm_key_to_odoo_id.get(norm_key)
        if not odoo_book_id:
            logging.warning("  Bok med BOK-ID=%s (nyckel=%s) finns inte i Odoo", bok_id, norm_key[:40])
            no_book += 1
            continue

        # Losa person -> Odoo user
        odoo_login = PERSON_MAP.get(person)
        odoo_uid_person = None
        if odoo_login:
            odoo_uid_person = user_by_login.get(odoo_login) or user_by_name.get(odoo_login)
        if not odoo_uid_person:
            odoo_uid_person = user_by_name.get(person)
        if not odoo_uid_person:
            if person not in unknown_persons:
                logging.warning("  Person '%s' hittades inte i Odoo -- lagg till i PERSON_MAP", person)
                unknown_persons.add(person)
            unmapped += 1
            continue

        pair = (odoo_book_id, odoo_uid_person)
        if pair in existing_pairs:
            skipped += 1
            continue

        if dry_run:
            logging.info("  DRY: %s -> book_id=%d user_id=%d betyg=%d",
                         person, odoo_book_id, odoo_uid_person, r["rating"])
            created += 1
            continue

        try:
            create_vals = {
                "book_id": odoo_book_id,
                "user_id": odoo_uid_person,
                "rating":  r["rating"],
                "notes":   r["notes"] or False,
            }
            if r.get("date_read"):
                create_vals["date_read"] = r["date_read"]
            odoo_create(models, db, uid, pwd, "library.rating", create_vals)
            existing_pairs.add(pair)
            created += 1
        except Exception as e:
            logging.error("  FEL vid betyg %s/%s: %s", bok_id, person, e)
            errors += 1

    logging.info("  Betyg: skapad=%d, hoppade=%d, ingen-bok=%d, omappade=%d, fel=%d",
                 created, skipped, no_book, unmapped, errors)
    if unknown_persons:
        logging.warning("  Okanda personer (uppdatera PERSON_MAP): %s",
                        ", ".join(sorted(unknown_persons)))


# --- MAIN ---------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Migrera familjebiblioteket fran Notion till Odoo 19"
    )
    parser.add_argument("--dry-run",      action="store_true",
                        help="Validera utan att skriva till Odoo")
    parser.add_argument("--odoo-db",      default="aiab19",
                        help="Odoo-databas (default: aiab19)")
    parser.add_argument("--books-only",   action="store_true",
                        help="Importera bara bocker")
    parser.add_argument("--ratings-only", action="store_true",
                        help="Importera bara betyg (krav bokid_cache.json)")
    parser.add_argument("--list-persons", action="store_true",
                        help="Lista person-namn i Notion Betyg och avsluta")
    args = parser.parse_args()

    setup_logging()

    notion_token = os.environ.get("NOTION_TOKEN", "")
    if not notion_token:
        logging.error("NOTION_TOKEN saknas -- lagg till i clio-tools/.env")
        return

    if args.list_persons:
        persons = list_persons(notion_token)
        print("\nPerson-namn i Notion Betyg:")
        for name, count in sorted(persons.items(), key=lambda x: -x[1]):
            mapped = PERSON_MAP.get(name, "(EJ MAPPAD)")
            print(f"  {name}: {count} betyg -> Odoo login: {mapped}")
        return

    # Lad bokid_cache for rattning
    bokid_cache = load_bokid_cache()
    if bokid_cache:
        logging.info("bokid_cache.json laddad: %d BOK-ID -> normalized_key", len(bokid_cache))
    else:
        logging.warning("bokid_cache.json saknas -- rattning importeras ej")
        logging.warning("  Kopiera fran lokal clio-library/ till: %s", CACHE_FILE)

    # Hamta Notion-data
    books   = fetch_books(notion_token)
    ratings = [] if args.books_only else fetch_ratings(notion_token)

    if args.dry_run:
        logging.info("\nDRY-RUN: ansluter inte till Odoo")
        logging.info("  %d bocker att importera", len(books))
        if not args.books_only:
            logging.info("  %d betyg att importera (krav cache-fil)", len(ratings))
            persons = {r["person"] for r in ratings}
            unmapped = [p for p in persons if p not in PERSON_MAP]
            if unmapped:
                logging.warning("  Omappade personer: %s", ", ".join(sorted(unmapped)))
        return

    odoo_password = os.environ.get("ODOO_ADMIN_PASSWORD", "")
    if not odoo_password:
        import getpass
        odoo_password = getpass.getpass(f"Odoo admin-loesenord for {args.odoo_db}: ")

    uid, models_proxy, db, pwd = odoo_connect(args.odoo_db, odoo_password)

    norm_key_to_odoo_id = {}
    if not args.ratings_only:
        norm_key_to_odoo_id = import_books(models_proxy, db, uid, pwd, books, args.dry_run)
    else:
        existing = odoo_search_read(models_proxy, db, uid, pwd, "library.book", [], ["name", "author"])
        for r in existing:
            nk = normalize_key(r["name"], r.get("author") or "")
            norm_key_to_odoo_id[nk] = r["id"]
        logging.info("Hamtade %d befintliga bocker fran Odoo", len(norm_key_to_odoo_id))

    if not args.books_only:
        import_ratings(models_proxy, db, uid, pwd, ratings, norm_key_to_odoo_id, bokid_cache, args.dry_run)

    logging.info("\nMigrering klar.")


if __name__ == "__main__":
    main()
