"""
probe_wiki_langs.py — Söker UFO-kategorier i Wikipedia-utgåvor
som inte täcks av Wikidata-sitelänkarna.
"""
import urllib.request, urllib.parse, json, time

UA = "clio-uap-research/1.0 (contact: research@arvas.international)"

def search_cats(lang, terms):
    for term in terms:
        url = (f"https://{lang}.wikipedia.org/w/api.php"
               f"?action=query&list=search&srsearch={urllib.parse.quote(term)}"
               f"&srnamespace=14&srlimit=3&format=json")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            hits = data.get("query", {}).get("search", [])
            if hits:
                return [(h["title"], h.get("snippet", "")[:60]) for h in hits[:2]]
        except Exception:
            pass
        time.sleep(0.5)
    return []

# Prioriterade språk vi saknar (grovt sorterade efter Wikipedia-storlek)
targets = [
    "fr", "nl", "ja", "pl", "cs", "sv", "hu", "ca",
    "he", "da", "sr", "bg", "hr", "sk", "ms", "sl",
    "lt", "gl", "eu", "nn", "th", "hi", "bn", "ur",
    "bs", "mk", "af", "is", "lb", "cy", "ga",
]

terms_map = {
    "fr": ["OVNI", "observation OVNI"],
    "nl": ["UFO", "ufo waarneming"],
    "ja": ["UFO目撃", "未確認飛行物体"],
    "pl": ["UFO", "obserwacje UFO"],
    "cs": ["UFO", "pozorování UFO"],
    "sv": ["UFO", "ufo-observation"],
    "hu": ["UFO", "ufóészlelés"],
    "ca": ["OVNI", "avistament OVNI"],
    "he": ["עב\"ם", "UFO"],
    "da": ["UFO", "ufo-observation"],
    "sr": ["НЛО", "UFO"],
    "bg": ["НЛО", "UFO"],
    "hr": ["UFO", "NLO"],
    "sk": ["UFO", "NLO"],
    "ms": ["UFO", "penampakan UFO"],
    "sl": ["NLP", "UFO"],
    "lt": ["NSO", "UFO"],
    "gl": ["OVNI", "UFO"],
    "eu": ["OEZ", "UFO"],
    "nn": ["UFO"],
    "th": ["ยูเอฟโอ", "UFO"],
    "hi": ["यूएफओ", "UFO"],
    "bn": ["UFO"],
    "ur": ["UFO"],
    "bs": ["NLO", "UFO"],
    "mk": ["НЛО", "UFO"],
    "af": ["UFO"],
    "is": ["UFO"],
    "lb": ["UFO"],
    "cy": ["UFO"],
    "ga": ["UFO"],
}

print(f"Söker kategorier i {len(targets)} Wikipedia-utgåvor...")
print()

found_langs = []
for lang in targets:
    terms = terms_map.get(lang, ["UFO"])
    hits = search_cats(lang, terms)
    if hits:
        print(f"  {lang}: HITTAD — {hits[0][0]}")
        found_langs.append((lang, hits[0][0]))
    else:
        print(f"  {lang}: ingen träff")
    time.sleep(1.0)

print()
print(f"Totalt med UFO-kategorier: {len(found_langs)}")
for lang, cat in found_langs:
    print(f"  {lang}: {cat}")
