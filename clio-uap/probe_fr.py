"""Verify French parent category and find exact names for direct import."""
import urllib.request, urllib.parse, json, time

UA = "clio-uap-research/1.0"

def cat_members(lang, cat, n=10):
    url = (f"https://{lang}.wikipedia.org/w/api.php?action=query&list=categorymembers"
           f"&cmtitle={urllib.parse.quote(cat)}&cmtype=page|subcat&cmlimit={n}&format=json")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return data.get("query", {}).get("categorymembers", [])
    except Exception as e:
        return []

# Försök hitta föräldern till "Observation d'ovni au Canada"
print("=== fr: Observation d'ovni (förälderkategori?) ===")
mems = cat_members("fr", "Catégorie:Observation d'ovni", 15)
if mems:
    for m in mems:
        print(f"  ns={m['ns']} {m['title']}")
else:
    print("  TOM/SAKNAS")

time.sleep(1)

# Kolla kollektiv-kategorin
print()
print("=== fr: Observation collective d'ovni ===")
mems = cat_members("fr", "Catégorie:Observation collective d'ovni", 10)
for m in mems:
    print(f"  ns={m['ns']} {m['title']}")

time.sleep(1)

# Kolla Canada-kategorin
print()
print("=== fr: Observation d'ovni au Canada ===")
mems = cat_members("fr", "Catégorie:Observation d'ovni au Canada", 10)
for m in mems:
    print(f"  ns={m['ns']} {m['title']}")

time.sleep(1)

# Kolla France-kategorin
print()
print("=== fr: Observation d'ovni en France ===")
mems = cat_members("fr", "Catégorie:Observation d'ovni en France", 10)
for m in mems:
    print(f"  ns={m['ns']} {m['title']}")

time.sleep(1)

# Kolla Ufologie-kategorin (toppnivå)
print()
print("=== fr: Ufologie (subkats?) ===")
mems = cat_members("fr", "Catégorie:Ufologie", 15)
for m in mems:
    print(f"  ns={m['ns']} {m['title']}")
