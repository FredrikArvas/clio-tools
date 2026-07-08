#!/usr/bin/env python3
"""Migrering uap: Odoo 18 uapdb -> Odoo 19 uap."""

import xmlrpc.client
import sys
import os
from pathlib import Path

# --- Anslutningar ---
SRC_URL  = "http://localhost:8069"
SRC_DB   = "uapdb"
DST_URL  = "http://localhost:8079"
DST_DB   = "uap"

env = {}
for ef in ["/home/clioadmin/18.0/clio-tools/.env", "/home/clioadmin/19.0/clio-tools/.env"]:
    try:
        for line in Path(ef).read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k, v)
    except FileNotFoundError:
        pass

SRC_USER = env.get("ODOO_USER", "")
SRC_PASS = env.get("ODOO_PASSWORD", "")
DST_USER = "clio-bot@arvas.international"
DST_PASS = env.get("ODOO_PASSWORD", "")

def connect(url, db, user, pwd):
    uid = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common").authenticate(db, user, pwd, {})
    if not uid:
        print(f"FAIL: kunde inte ansluta till {db} som {user}")
        sys.exit(1)
    m = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return uid, m

def read_all(m, db, uid, pwd, model, fields, batch=200):
    ids = m.execute_kw(db, uid, pwd, model, "search", [[]])
    records = []
    for i in range(0, len(ids), batch):
        chunk = m.execute_kw(db, uid, pwd, model, "read", [ids[i:i+batch]], {"fields": fields})
        records.extend(chunk)
    return records

print("Ansluter...")
src_uid, src = connect(SRC_URL, SRC_DB, SRC_USER, SRC_PASS)
dst_uid, dst = connect(DST_URL, DST_DB, DST_USER, DST_PASS)
print(f"  Kalla {SRC_DB} (uid={src_uid}) och {DST_DB} (uid={dst_uid})")

# === 1. uap.source ===
print("\n[1/4] uap.source...")
src_sources = read_all(src, SRC_DB, src_uid, SRC_PASS, "uap.source",
    ["source_id", "name", "source_type", "tier", "url", "published_date", "language"])
src_id_map = {}  # old_id -> new_id
for rec in src_sources:
    old_id = rec["id"]
    vals = {k: v for k, v in rec.items()
            if k not in ("id", "display_name") and v not in (False, None, "")}
    new_id = dst.execute_kw(DST_DB, dst_uid, DST_PASS, "uap.source", "create", [vals])
    src_id_map[old_id] = new_id
print(f"  {len(src_id_map)} sources migrerade")

# === 2. uap.witness ===
print("\n[2/4] uap.witness...")
src_witnesses = read_all(src, SRC_DB, src_uid, SRC_PASS, "uap.witness",
    ["name", "witness_type", "credibility", "status", "url", "language"])
wit_id_map = {}
for rec in src_witnesses:
    old_id = rec["id"]
    vals = {k: v for k, v in rec.items()
            if k not in ("id", "display_name") and v not in (False, None, "")}
    new_id = dst.execute_kw(DST_DB, dst_uid, DST_PASS, "uap.witness", "create", [vals])
    wit_id_map[old_id] = new_id
print(f"  {len(wit_id_map)} witnesses migrerade")

# === 3. uap.encounter ===
print("\n[3/4] uap.encounter (2 763 poster, kan ta en stund)...")
enc_fields = ["encounter_id", "encounter_guid", "date_observed", "location",
              "title_en", "title_original", "description_en", "description_sv",
              "description_original", "language_original", "encounter_class",
              "discourse_level", "official_response", "status", "research_notes",
              "neo4j_node_id", "country_id", "source_ids", "witness_ids"]
src_encounters = read_all(src, SRC_DB, src_uid, SRC_PASS, "uap.encounter", enc_fields)
enc_id_map = {}
skipped = 0
for i, rec in enumerate(src_encounters):
    old_id = rec["id"]
    vals = {}
    for k in ["encounter_id", "encounter_guid", "date_observed", "location",
              "title_en", "title_original", "description_en", "description_sv",
              "description_original", "language_original", "encounter_class",
              "discourse_level", "official_response", "status", "research_notes",
              "neo4j_node_id"]:
        v = rec.get(k)
        if v not in (False, None, ""):
            vals[k] = v

    # country_id: [id, name] -> id i dst (res.country är globalt, samma id)
    if rec.get("country_id"):
        vals["country_id"] = rec["country_id"][0]

    # source_ids: lista av gamla id -> nya id
    new_src_ids = [src_id_map[sid] for sid in rec.get("source_ids", []) if sid in src_id_map]
    if new_src_ids:
        vals["source_ids"] = [(6, 0, new_src_ids)]

    # witness_ids: lista av gamla id -> nya id
    new_wit_ids = [wit_id_map[wid] for wid in rec.get("witness_ids", []) if wid in wit_id_map]
    if new_wit_ids:
        vals["witness_ids"] = [(6, 0, new_wit_ids)]

    try:
        new_id = dst.execute_kw(DST_DB, dst_uid, DST_PASS, "uap.encounter", "create", [vals])
        enc_id_map[old_id] = new_id
    except Exception as e:
        skipped += 1
        print(f"  SKIP encounter {rec.get('encounter_id','?')}: {e}")

    if (i + 1) % 200 == 0:
        print(f"  {i+1}/{len(src_encounters)} encounters klara...")

print(f"  {len(enc_id_map)} encounters migrerade, {skipped} skippade")

# === 4. uap.verification ===
print("\n[4/4] uap.verification...")
ver_fields = ["name", "change_date", "changed_by", "field_name",
              "original_value", "updated_value", "reason",
              "source_link", "verification_status", "encounter_id"]
src_verifs = read_all(src, SRC_DB, src_uid, SRC_PASS, "uap.verification", ver_fields)
ver_ok = 0
for rec in src_verifs:
    old_enc_id = rec.get("encounter_id")
    if not old_enc_id:
        continue
    old_enc_id = old_enc_id[0] if isinstance(old_enc_id, list) else old_enc_id
    new_enc_id = enc_id_map.get(old_enc_id)
    if not new_enc_id:
        continue
    vals = {"encounter_id": new_enc_id}
    for k in ["name", "change_date", "changed_by", "field_name",
              "original_value", "updated_value", "reason", "source_link", "verification_status"]:
        v = rec.get(k)
        if v not in (False, None, ""):
            vals[k] = v
    try:
        dst.execute_kw(DST_DB, dst_uid, DST_PASS, "uap.verification", "create", [vals])
        ver_ok += 1
    except Exception as e:
        print(f"  SKIP verification: {e}")

print(f"  {ver_ok} verifications migrerade")

# === Sammanfattning ===
print("\n=== KLAR ===")
for model in ["uap.source", "uap.witness", "uap.encounter", "uap.verification"]:
    cnt = dst.execute_kw(DST_DB, dst_uid, DST_PASS, model, "search_count", [[]])
    print(f"  {model}: {cnt}")
