#!/usr/bin/env python3
"""Import uap_sources_v1.3.csv -> res.partner (Odoo 19, db=uap).
Dedup-nyckel: uap_org_id (= uap_source_id i CSV).
"""
import csv, xmlrpc.client
from pathlib import Path

def load_env(path):
    env = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())
    return env

env  = load_env("/home/clioadmin/19.0/clio-tools/clio-uap/.env")
URL  = "http://localhost:8079"
DB   = "uap"
USER = env.get('ODOO_USER', 'fredrik@arvas.se')
PASS = env.get("ODOO_PASSWORD", "admin")

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid    = common.authenticate(DB, USER, PASS, {})
if not uid:
    raise SystemExit(f"Auth misslyckades för {USER} mot {DB}")
print(f"Autentiserad som uid={uid}")

mdl = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

CSV_PATH = "/home/clioadmin/19.0/clio-tools/clio-uap/uap_sources_v1.3.csv"

# Hämta befintliga uap_org_id -> partner-id
existing_ids = mdl.execute_kw(DB, uid, PASS, "res.partner", "search_read",
    [[["uap_org_id", "!=", False]]],
    {"fields": ["uap_org_id"], "limit": 0})
existing_map = {r["uap_org_id"]: r["id"] for r in existing_ids}
print(f"Befintliga res.partner med uap_org_id: {len(existing_map)}")

def row_to_vals(r):
    src = r["source_type"]
    is_company = src == "organization"
    if src == "person":
        name = f"{r['first_name'].strip()} {r['last_name'].strip()}".strip()
    else:
        name = (r.get("organization") or r.get("last_name") or "").strip()
    credibility = r.get("credibility_tier", "").strip()
    if credibility not in ("1", "2", "3"):
        credibility = False
    contact_type = src if src in ("person", "organization", "anonymous") else "person"
    return name, {
        "name":             name,
        "is_company":       is_company,
        "website":          r.get("website", "").strip() or False,
        "email":            r.get("email", "").strip() or False,
        "phone":            r.get("phone", "").strip() or False,
        "comment":          r.get("notes", "").strip() or False,
        "uap_org_id":       r["uap_source_id"].strip(),
        "uap_contact_type": contact_type,
        "uap_role":         r.get("role", "").strip() or False,
        "uap_credibility":  credibility,
        "uap_focus_areas":  r.get("focus_areas", "").strip() or False,
        "uap_language":     r.get("language", "").strip() or False,
        "uap_social_media": r.get("social_media", "").strip() or False,
        "uap_podcast_name": r.get("podcast_name", "").strip() or False,
        "uap_rss_feed":     r.get("rss_feed", "").strip() or False,
    }

created, updated, skipped, errors = [], [], [], []

with open(CSV_PATH, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

print(f"Importerar {len(rows)} rader...")

for i, row in enumerate(rows):
    try:
        org_id = row["uap_source_id"].strip()
        name, vals = row_to_vals(row)
        if not name:
            errors.append(f"  ERR  rad {i+2}: tomt namn (org_id={org_id})")
            continue
        if org_id in existing_map:
            # Uppdatera befintlig
            mdl.execute_kw(DB, uid, PASS, "res.partner", "write",
                [[existing_map[org_id]], vals])
            updated.append(f"  UPD  {name} (id={existing_map[org_id]})")
        else:
            new_id = mdl.execute_kw(DB, uid, PASS, "res.partner", "create", [vals])
            created.append(f"  NEW  {name} (id={new_id}, org_id={org_id})")
            existing_map[org_id] = new_id
    except Exception as e:
        errors.append(f"  ERR  rad {i+2}: {e}")

print(f"\n{'='*60}")
print(f"UAP Sources v1.3 -- Import klar")
print(f"{'='*60}")
print(f"Skapade:   {len(created)}")
print(f"Uppdaterade: {len(updated)}")
print(f"Fel:       {len(errors)}")
if errors:
    print("\nFel:")
    for e in errors: print(e)
if len(created) <= 20:
    print("\nNya poster:")
    for c in created: print(c)
print(f"{'='*60}")
