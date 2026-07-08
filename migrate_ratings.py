#!/usr/bin/env python3
"""
Arvas Familjebibliotek — Betygsmigration Notion → Odoo
Rekonstruerar BOK-ID-mappning från Notion Bokregistrets created_time-ordning.

Användning:
  ODOO_ADMIN_PASSWORD=admin python3 migrate_ratings.py --odoo-db aiab19 --dry-run
  ODOO_ADMIN_PASSWORD=admin python3 migrate_ratings.py --odoo-db aiab19
"""

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.request
import xmlrpc.client
from pathlib import Path

NOTION_API     = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
BOKREGISTER_DB = "94906f71-ee0f-4ff8-8c4b-28e822f6e670"
BETYG_DB       = "41009da8-a1e7-48e2-9ed9-7f3c9406ef93"

PERSON_MAP = {
    "Fredrik": "fredrik@arvas.se",
    "Ulrika":  "ulrika",
    "Alice":   "alice",
    "Johan":   "johan",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()],
)


def load_notion_token():
    for p in [
        Path("/home/clioadmin/clio-tools/.env"),
        Path("/home/clioadmin/clio-tools-19/.env"),
        Path(__file__).parent / ".env",
    ]:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("NOTION_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"')
    return os.environ.get("NOTION_TOKEN", "")


def notion_query(db_id, token, sorts=None):
    """Hämtar alla sidor från en Notion-databas."""
    pages, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        if sorts:
            body["sorts"] = sorts
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{NOTION_API}/databases/{db_id}/query",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        time.sleep(0.2)
    return pages


def prop_text(page, field):
    prop = page.get("properties", {}).get(field, {})
    ptype = prop.get("type", "")
    if ptype == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    if ptype == "number":
        v = prop.get("number")
        return v  # return raw number
    if ptype == "date":
        d = prop.get("date")
        return d.get("start", "") if d else ""
    return ""


def normalize_key(titel, forfattare):
    def clean(s):
        s = re.sub(r"[^\w\s]", "", s.lower()).strip()
        return re.sub(r"\s+", " ", s)
    return f"{clean(titel)}||{clean(forfattare or '')}"


def build_bokid_cache(token):
    """
    Hämtar Bokregister sorterat på created_time ASC och tilldelar BOK-IDn i ordning.
    Returnerar:
      - bok_id_to_normkey: {"BOK-0001": "kapten grants barn||jules verne", ...}
      - normkey_to_position: för debug
    """
    logging.info("Hämtar Bokregister från Notion (sorterat på created_time)...")
    pages = notion_query(
        BOKREGISTER_DB, token,
        sorts=[{"timestamp": "created_time", "direction": "ascending"}],
    )
    logging.info("  %d böcker hämtade", len(pages))

    bok_id_to_normkey = {}
    for i, page in enumerate(pages):
        titel = prop_text(page, "Titel")
        forfattare = prop_text(page, "Författare") or ""
        if not titel:
            continue
        bok_id = f"BOK-{i+1:04d}"
        nk = normalize_key(titel, forfattare)
        bok_id_to_normkey[bok_id] = nk

    logging.info("  Byggt cache: %d BOK-ID → normalized_key", len(bok_id_to_normkey))
    return bok_id_to_normkey


def fetch_betyg(token):
    logging.info("Hämtar Betyg från Notion...")
    pages = notion_query(BETYG_DB, token)
    ratings = []
    for page in pages:
        bok_id  = prop_text(page, "BOK-ID")
        person  = prop_text(page, "Person")
        betyg   = prop_text(page, "Betyg")  # number
        datum   = prop_text(page, "Datum läst")
        not_   = prop_text(page, "Anteckning")
        if bok_id and person and betyg is not None:
            ratings.append({
                "bok_id":  bok_id,
                "person":  person,
                "betyg":   int(betyg) if betyg else None,
                "datum":   datum or False,
                "anteckning": not_ or False,
            })
    logging.info("  %d giltiga betyg hämtade", len(ratings))
    return ratings


def odoo_connect(url, db, password):
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, "admin", password, {})
    if not uid:
        logging.error("Odoo-autentisering misslyckades")
        sys.exit(1)
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return uid, models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--odoo-db",  default="aiab19")
    parser.add_argument("--odoo-url", default="http://localhost:8079")
    parser.add_argument("--dry-run",  action="store_true")
    args = parser.parse_args()

    token = load_notion_token()
    if not token:
        logging.error("NOTION_TOKEN hittades inte")
        sys.exit(1)

    odoo_pwd = os.environ.get("ODOO_ADMIN_PASSWORD", "admin")
    uid, models = odoo_connect(args.odoo_url, args.odoo_db, odoo_pwd)

    # ── 1. Bygg BOK-ID → normkey från Notion skapad_tid-ordning ──────────────
    bok_id_to_normkey = build_bokid_cache(token)

    # ── 2. Hämta Odoo-böcker: normkey → book.id ───────────────────────────────
    logging.info("Hämtar böcker från Odoo...")
    odoo_books = models.execute_kw(
        args.odoo_db, uid, odoo_pwd,
        "library.book", "search_read",
        [[]],
        {"fields": ["id", "name", "author"]},
    )
    normkey_to_odoo_id = {}
    for b in odoo_books:
        nk = normalize_key(b["name"], b.get("author") or "")
        normkey_to_odoo_id[nk] = b["id"]
    logging.info("  %d böcker i Odoo", len(normkey_to_odoo_id))

    # ── 3. Hämta Odoo-användare: login → user.id ──────────────────────────────
    odoo_users = models.execute_kw(
        args.odoo_db, uid, odoo_pwd,
        "res.users", "search_read",
        [[]],
        {"fields": ["id", "login"]},
    )
    login_to_uid = {u["login"]: u["id"] for u in odoo_users}

    # ── 4. Hämta Betyg ────────────────────────────────────────────────────────
    ratings = fetch_betyg(token)

    # ── 5. Hämta befintliga betyg i Odoo (undvik duplikat) ────────────────────
    existing_raw = models.execute_kw(
        args.odoo_db, uid, odoo_pwd,
        "library.rating", "search_read",
        [[]],
        {"fields": ["book_id", "user_id"]},
    )
    existing_pairs = {(r["book_id"][0], r["user_id"][0]) for r in existing_raw}
    logging.info("  %d betyg redan i Odoo", len(existing_pairs))

    # ── 6. Skapa betyg ────────────────────────────────────────────────────────
    created = skipped = no_book = no_user = no_cache = 0

    for r in ratings:
        bok_id = r["bok_id"]
        person = r["person"]

        # BOK-ID → normkey via rekonstruerad cache
        normkey = bok_id_to_normkey.get(bok_id)
        if not normkey:
            no_cache += 1
            logging.debug("  %s: BOK-ID finns ej i rekonstruerad cache", bok_id)
            continue

        # normkey → Odoo book_id
        book_id = normkey_to_odoo_id.get(normkey)
        if not book_id:
            no_book += 1
            logging.debug("  %s: Ingen matchande bok i Odoo (nyckel=%s)", bok_id, normkey[:40])
            continue

        # Person → Odoo user_id
        login = PERSON_MAP.get(person)
        if not login:
            no_user += 1
            logging.warning("  Okänd person: %s", person)
            continue
        user_id = login_to_uid.get(login)
        if not user_id:
            no_user += 1
            logging.warning("  Login %s finns ej i Odoo", login)
            continue

        # Duplikatkontroll
        if (book_id, user_id) in existing_pairs:
            skipped += 1
            continue

        if args.dry_run:
            logging.info("  [DRY-RUN] %s | %s | betyg=%s | book_id=%s | user_id=%s",
                         bok_id, person, r["betyg"], book_id, user_id)
            created += 1
            continue

        vals = {
            "book_id": book_id,
            "user_id": user_id,
            "rating":  r["betyg"] or 3,
            "notes":   r["anteckning"] or False,
        }
        if r["datum"]:
            vals["date_read"] = r["datum"]

        models.execute_kw(
            args.odoo_db, uid, odoo_pwd,
            "library.rating", "create", [vals],
        )
        existing_pairs.add((book_id, user_id))
        created += 1

    logging.info("")
    logging.info("── Sammanfattning ──────────────────────────────")
    logging.info("  Skapade:          %d", created)
    logging.info("  Hoppade (duplikat): %d", skipped)
    logging.info("  Ej i cache:       %d  (BOK-ID > antal böcker)", no_cache)
    logging.info("  Ej i Odoo:        %d  (titel ej matchad)", no_book)
    logging.info("  Okänd person:     %d", no_user)
    logging.info("Migrering klar.")


if __name__ == "__main__":
    main()
