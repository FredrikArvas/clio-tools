#!/usr/bin/env python3
"""Testimport av uap_sources CSV -> res.partner (uap-db, Odoo 19). 5 testrader."""
import csv
import xmlrpc.client
from pathlib import Path

def load_env(path):
    env = {}
    try:
        for line in Path(path).read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass
    return env

env = load_env("/home/clioadmin/19.0/clio-tools/.env")

URL  = "http://localhost:8079"
DB   = "uap"
USER = "clio-bot@arvas.international"
PASS = env.get("ODOO_PASSWORD", "admin")

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid    = common.authenticate(DB, USER, PASS, {})
if not uid:
    raise SystemExit(f"Auth misslyckades for {USER} mot {DB}")
print(f"Autentiserad som uid={uid}")

mdl = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

CSV_PATH = "/home/clioadmin/19.0/clio-tools/clio-uap/uap_sources_v1.0.csv"

TEST_NAMES = {
    "Leslie Kean",
    "Clas Svahn",
    "AFU — Archives for the Unexplained",
    "GEIPAN",
    "David Grusch",
}

def partner_exists(name, website):
    domain = [("website", "=", website)] if website else [("name", "=", name)]
    ids = mdl.execute_kw(DB, uid, PASS, "res.partner", "search", [domain], {"limit": 1})
    return ids[0] if ids else None

def row_to_vals(r):
    src = r["source_type"]
    is_company = src == "organization"
    if src == "person":
        name = f"{r['first_name'].strip()} {r['last_name'].strip()}".strip()
    else:
        name = (r["organization"] or r["last_name"] or "").strip()
    vals = {
        "name":             name,
        "is_company":       is_company,
        "website":          r["website"].strip() or False,
        "email":            r["email"].strip() or False,
        "phone":            r["phone"].strip() or False,
        "comment":          r["notes"].strip() or False,
        "uap_contact_type": src if src in ("person","organization","anonymous") else "person",
        "uap_role":         r["role"].strip() or False,
        "uap_credibility":  r["credibility_tier"].strip() or False,
        "uap_focus_areas":  r["focus_areas"].strip() or False,
        "uap_language":     r["language"].strip() or False,
        "uap_social_media": r["social_media"].strip() or False,
        "uap_podcast_name": r["podcast_name"].strip() or False,
        "uap_rss_feed":     r["rss_feed"].strip() or False,
    }
    return name, vals

created = []
skipped = []

with open(CSV_PATH, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        src = row["source_type"]
        if src == "person":
            full_name = f"{row['first_name'].strip()} {row['last_name'].strip()}".strip()
        else:
            full_name = (row["organization"] or row["last_name"] or "").strip()
        if full_name not in TEST_NAMES:
            continue
        name, vals = row_to_vals(row)
        existing = partner_exists(name, vals["website"])
        if existing:
            skipped.append(f"  SKIP  {name} (id={existing})")
            continue
        new_id = mdl.execute_kw(DB, uid, PASS, "res.partner", "create", [vals])
        created.append(f"  OK    {name} (id={new_id})")

print(f"\n{'='*50}")
print(f"UAP Contacts -- Testimport")
print(f"{'='*50}")
print(f"Skapade ({len(created)}):")
for c in created: print(c)
print(f"\nHoppade over ({len(skipped)}):")
for s in skipped: print(s)
print(f"{'='*50}\n")
