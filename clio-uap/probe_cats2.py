"""
probe_cats2.py — Hitta rätt sightings-kategorier i fr/nl/ja/pl/cs/da/sr/bg
"""
import urllib.request, urllib.parse, json, time

UA = "clio-uap-research/1.0"

def search_cats(lang, term, n=8):
    url = (f"https://{lang}.wikipedia.org/w/api.php"
           f"?action=query&list=search&srsearch={urllib.parse.quote(term)}"
           f"&srnamespace=14&srlimit={n}&format=json")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return [(h["title"], h.get("size", 0)) for h in data.get("query", {}).get("search", [])]
    except:
        return []

def cat_members(lang, cat, n=8):
    url = (f"https://{lang}.wikipedia.org/w/api.php?action=query&list=categorymembers"
           f"&cmtitle={urllib.parse.quote(cat)}&cmtype=page|subcat&cmlimit={n}&format=json")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return data.get("query", {}).get("categorymembers", [])
    except:
        return []

# --- Franska ---
print("=== fr ===")
for term in ["observation OVNI", "incident OVNI", "rencontre OVNI", "OVNI"]:
    hits = search_cats("fr", term, 5)
    for title, size in hits[:3]:
        print(f"  {title}")
    time.sleep(0.5)

print()
# --- Holländska ---
print("=== nl ===")
for term in ["ufo-waarneming", "ufo incident", "onbekend vliegend object"]:
    hits = search_cats("nl", term, 5)
    for title, size in hits[:3]:
        print(f"  {title}")
    time.sleep(0.5)

print()
# --- Japanska subkategorier ---
print("=== ja - subkats under 未確認飛行物体 ===")
mems = cat_members("ja", "Category:未確認飛行物体", 20)
for m in mems:
    print(f"  ns={m['ns']} {m['title']}")
time.sleep(0.5)

print()
# --- Polska subkategorier ---
print("=== pl - subkats under Ufologia ===")
mems = cat_members("pl", "Kategoria:Ufologia", 20)
for m in mems:
    print(f"  ns={m['ns']} {m['title']}")
time.sleep(0.5)

print()
# --- Serbiska, bulgariska ---
print("=== sr - subkats ===")
mems = cat_members("sr", "Категорија:НЛО", 20)
for m in mems:
    print(f"  ns={m['ns']} {m['title']}")
time.sleep(0.5)

print()
print("=== bg - subkats ===")
mems = cat_members("bg", "Категория:НЛО", 20)
for m in mems:
    print(f"  ns={m['ns']} {m['title']}")
