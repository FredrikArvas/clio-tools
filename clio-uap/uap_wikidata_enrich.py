"""
uap_wikidata_enrich.py — Sprint E
Hämtar Wikidata Q-nummer för alla WIKI-encounters via Wikipedia API,
sätter wikidata_id och wiki_edition_count, samt kopplar series_id.
"""
import xmlrpc.client
import requests
import time
import json
from collections import defaultdict
from dotenv import load_dotenv
import os

load_dotenv("/home/clioadmin/clio-tools/.env")
URL  = os.environ["ODOO_URL"]
DB   = "uapdb"
USER = os.environ["ODOO_USER"]
PW   = os.environ["ODOO_PASSWORD"]

uid    = xmlrpc.client.ServerProxy(URL + "/xmlrpc/2/common").authenticate(DB, USER, PW, {})
models = xmlrpc.client.ServerProxy(URL + "/xmlrpc/2/object")

def odoo(model, method, args, kw=None):
    return models.execute_kw(DB, uid, PW, model, method, args, kw or {})

# --- 1. Hämta alla WIKI-encounters ---
wiki = odoo("uap.encounter", "search_read",
    [[["source_ref", "like", "WIKI-"]]],
    {"fields": ["id", "encounter_id", "source_ref", "wikidata_id"], "limit": 0})

print(f"WIKI-encounters: {len(wiki)}")

# --- 2. Hämta Q-nummer per encounter ---
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "UAPTracker/1.0 (https://arvas.international; clio@arvas.international) uap_wikidata_enrich.py"
})

def clean_title(title):
    """Rensa bort Wikipedia-syntaxskräp som [[...|...]] och #anchors."""
    import re
    # [[Artikel#Sektion|Visningstext]] → Artikel
    m = re.match(r'\[\[([^#|\]]+)', title)
    if m:
        return m.group(1).strip()
    # Vanlig titel — ta bort #-anchor
    return title.split("#")[0].strip()

def get_qid(lang, title):
    """Hämtar Wikidata Q-nummer från Wikipedia API."""
    title = clean_title(title)
    if not title:
        return None
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "pageprops",
        "ppprop": "wikibase_item",
        "titles": title.replace("_", " "),
        "format": "json",
        "redirects": 1,
    }
    try:
        r = SESSION.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                return qid
    except Exception as e:
        print(f"  FEL {lang}:{title}: {e}")
    return None

# Cache: undvik dubbelanrop för samma artikel
cache = {}
results = {}  # encounter odoo_id → qid

total = len(wiki)
for i, enc in enumerate(wiki):
    src = enc.get("source_ref", "") or ""
    # Format: WIKI-{lang}:{article}
    if not src.startswith("WIKI-") or ":" not in src:
        continue
    rest = src[5:]  # ta bort "WIKI-"
    lang, title = rest.split(":", 1)

    cache_key = f"{lang}:{title}"
    if cache_key not in cache:
        qid = get_qid(lang, title)
        cache[cache_key] = qid
        time.sleep(0.15)  # ~7 req/s, snäll mot Wikipedia
    else:
        qid = cache[cache_key]

    results[enc["id"]] = qid

    if (i + 1) % 50 == 0:
        hits = sum(1 for q in results.values() if q)
        print(f"  {i+1}/{total} — Q-träffar: {hits}")

# --- 3. Spara wikidata_id till Odoo ---
print("\nSparar wikidata_id...")
no_qid = 0
for enc_id, qid in results.items():
    if qid:
        odoo("uap.encounter", "write", [[enc_id], {"wikidata_id": qid}])
    else:
        no_qid += 1

print(f"Sparade: {len(results) - no_qid} med Q-ID, {no_qid} utan.")

# --- 4. Räkna wiki_edition_count per Q-ID ---
print("\nBeräknar wiki_edition_count...")
qid_to_ids = defaultdict(list)
for enc_id, qid in results.items():
    if qid:
        qid_to_ids[qid].append(enc_id)

multi = {q: ids for q, ids in qid_to_ids.items() if len(ids) > 1}
print(f"Q-IDs med >1 edition: {len(multi)}")
print("Top 10:")
for q, ids in sorted(multi.items(), key=lambda x: -len(x[1]))[:10]:
    # Hämta titlar för visning
    titles = odoo("uap.encounter", "search_read",
        [[["id", "in", ids]]], {"fields": ["title_en"], "limit": 5})
    print(f"  {q} ({len(ids)}x): {titles[0].get('title_en','?')}")

# Sätt wiki_edition_count för alla
for qid, ids in qid_to_ids.items():
    count = len(ids)
    odoo("uap.encounter", "write", [ids, {"wiki_edition_count": count}])

print("\nKlar!")

# --- 5. Sammanfattning ---
enriched = odoo("uap.encounter", "search_count",
    [[["wikidata_id", "!=", False], ["source_ref", "like", "WIKI-"]]])
print(f"WIKI-encounters med wikidata_id: {enriched}/{total}")

# Spara cache lokalt för debugging
with open("/tmp/wikidata_cache.json", "w") as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)
print("Cache sparad: /tmp/wikidata_cache.json")
