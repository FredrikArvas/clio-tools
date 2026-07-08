#!/usr/bin/env python3
"""
uap_build_v13.py
Fas 1: Lagger till data_source-kolumn i v1.2 (befintliga -> "manual_clio")
Fas 2: Skoerd av Wikipedia-kategorier, manga sprak, via curl
Fas 3: Dedup + ID-generering -> uap_sources_v1.3.csv
"""
import csv, json, re, subprocess, time, unicodedata, urllib.parse
from pathlib import Path

SRC  = Path("/home/clioadmin/19.0/clio-tools/clio-uap/uap_sources_v1.2.csv")
DEST = Path("/home/clioadmin/19.0/clio-tools/clio-uap/uap_sources_v1.3.csv")
FIELDS = ["uap_source_id","source_type","first_name","last_name","role",
          "organization","website","podcast_name","rss_feed","focus_areas",
          "language","country","city","credibility_tier","social_media",
          "email","phone","notes","data_source"]

UA = "Mozilla/5.0 (compatible; UAP-Research-Bot/1.3; +https://arvas.international)"

def slugify(s, maxlen=16):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]", "", s)
    return s[:maxlen]

def make_id(src_type, first, last, org, seq):
    if src_type == "person":
        slug = slugify(last + first)
    else:
        name = org or last or ""
        short = re.split(r"[ \-]", name)[0].strip()
        slug = slugify(short)
    prefix = "UAP-PRS" if src_type == "person" else "UAP-ORG"
    return "{}-{}-{:04d}".format(prefix, slug, seq)

def curl_json(url):
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", "12", "-A", UA, url],
            capture_output=True, text=True
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {}
        return json.loads(r.stdout)
    except Exception:
        return {}

def fetch_category_members(lang, category):
    members = []
    cont_param = ""
    while True:
        base = "https://{}.wikipedia.org/w/api.php".format(lang)
        params = {
            "action": "query", "list": "categorymembers",
            "cmtitle": category, "cmlimit": "500",
            "cmtype": "page", "cmnamespace": "0", "format": "json"
        }
        if cont_param:
            params["cmcontinue"] = cont_param
        url = base + "?" + urllib.parse.urlencode(params)
        data = curl_json(url)
        batch = data.get("query", {}).get("categorymembers", [])
        members.extend(batch)
        cont = data.get("continue", {})
        if "cmcontinue" not in cont:
            break
        cont_param = cont["cmcontinue"]
        time.sleep(0.25)
    return members

def parse_name(title):
    name = re.sub(r"\s*\(.*?\)", "", title).strip()
    name = re.sub(r"\s+", " ", name)
    # Hantera "Efternamn, Fornamn"-format
    if "," in name:
        parts = name.split(",", 1)
        return parts[1].strip(), parts[0].strip()
    parts = name.split()
    if not parts:
        return "", title
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]

COUNTRY_CAT_MAP = [
    ("American", "USA"), ("United States", "USA"),
    ("British", "UK"), ("English", "UK"), ("Scottish", "UK"), ("Welsh", "UK"),
    ("French", "France"), ("German", "Germany"), ("Austrian", "Austria"),
    ("Swiss", "Switzerland"), ("Belgian", "Belgium"), ("Dutch", "Netherlands"),
    ("Swedish", "Sweden"), ("Norwegian", "Norway"), ("Danish", "Denmark"),
    ("Finnish", "Finland"), ("Icelandic", "Iceland"),
    ("Australian", "Australia"), ("New Zealand", "New Zealand"),
    ("Canadian", "Canada"), ("Brazilian", "Brazil"), ("Mexican", "Mexico"),
    ("Argentine", "Argentina"), ("Chilean", "Chile"), ("Peruvian", "Peru"),
    ("Colombian", "Colombia"), ("Uruguayan", "Uruguay"), ("Venezuelan", "Venezuela"),
    ("Italian", "Italy"), ("Spanish", "Spain"), ("Portuguese", "Portugal"),
    ("Russian", "Russia"), ("Soviet", "Russia"), ("Polish", "Poland"),
    ("Czech", "Czech Republic"), ("Slovak", "Slovakia"),
    ("Hungarian", "Hungary"), ("Romanian", "Romania"), ("Bulgarian", "Bulgaria"),
    ("Ukrainian", "Ukraine"), ("Latvian", "Latvia"), ("Lithuanian", "Lithuania"),
    ("Japanese", "Japan"), ("Chinese", "China"), ("Indian", "India"),
    ("South Korean", "South Korea"), ("Korean", "South Korea"),
    ("Israeli", "Israel"), ("Iranian", "Iran"), ("Turkish", "Turkey"),
    ("South African", "South Africa"), ("Greek", "Greece"),
    ("Croatian", "Croatia"), ("Serbian", "Serbia"),
    ("Puerto Rican", "USA"),
]

def get_en_country(en_title):
    """Hamtar land fran engelska Wikipedia via categories pa personsidan."""
    base = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query", "prop": "categories",
        "titles": en_title, "cllimit": "50", "format": "json"
    }
    url = base + "?" + urllib.parse.urlencode(params)
    data = curl_json(url)
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    cats = [c["title"] for c in page.get("categories", [])]
    for cat in cats:
        for pat, cname in COUNTRY_CAT_MAP:
            if pat in cat:
                return cname
    return None

def get_en_title(lang, title):
    """Hamtar engelska Wikipedia-titeln for en icke-engelsk artikel."""
    base = "https://{}.wikipedia.org/w/api.php".format(lang)
    params = {
        "action": "query", "prop": "langlinks",
        "titles": title, "lllang": "en",
        "lllimit": "1", "format": "json"
    }
    url = base + "?" + urllib.parse.urlencode(params)
    data = curl_json(url)
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    lls = page.get("langlinks", [])
    if lls:
        return lls[0].get("*") or lls[0].get("title")
    return None

# ---- Kategorier att skorda ----
# (lang, kategori, roll, default_country)
CATEGORIES = [
    # Engelska — karnkategorier
    ("en", "Category:Ufologists",                                     "researcher", None),
    ("en", "Category:UFO_writers",                                    "author",     None),
    ("en", "Category:American_UFO_writers",                           "author",     "USA"),
    ("en", "Category:UFO_conspiracy_theorists",                       "researcher", None),
    ("en", "Category:Paranormal_investigators",                       "researcher", None),
    ("en", "Category:People_associated_with_the_Roswell_UFO_incident","witness",    "USA"),
    ("en", "Category:Alien_abduction_claimants",                      "witness",    None),
    ("en", "Category:People_associated_with_Area_51",                 "researcher", "USA"),
    # Franska Wikipedia
    ("fr", "Catégorie:Ufologue",                                      "researcher", None),
    # Spanska Wikipedia
    ("es", "Categoría:Ufólogos",                                      "researcher", None),
    # Portugisiska Wikipedia
    ("pt", "Categoria:Ufólogos",                                      "researcher", None),
    # Hollandska Wikipedia
    ("nl", "Categorie:Ufoloog",                                       "researcher", None),
    # Ryska Wikipedia (URL-encodat)
    ("ru", "Категория:Уфологи",                                       "researcher", None),
    # Svenska Wikipedia
    ("sv", "Kategori:Ufologer",                                       "researcher", "Sweden"),
    # Tyska Wikipedia
    ("de", "Kategorie:Ufologie",                                      "researcher", None),
    # Italienska Wikipedia
    ("it", "Categoria:Ufologia",                                      "researcher", None),
    # Norska Wikipedia
    ("no", "Kategori:Ufologer",                                       "researcher", "Norway"),
    # Polska Wikipedia
    ("pl", "Kategoria:Ufologia",                                      "researcher", None),
    # Finska Wikipedia
    ("fi", "Luokka:Ufologit",                                         "researcher", "Finland"),
    # Japanska Wikipedia
    ("ja", "Category:UFO研究者",                                       "researcher", "Japan"),
]

# ---- Fas 1: Las v1.2 ----
print("=== Fas 1: Laser v1.2.csv ===")
existing_rows = []
existing_ids  = set()
existing_slugs= set()
max_seq = 0

with open(SRC, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        row["data_source"] = "manual_clio"
        existing_rows.append(row)
        existing_ids.add(row["uap_source_id"])
        try:
            seq_val = int(row["uap_source_id"].rsplit("-", 1)[-1])
            max_seq = max(max_seq, seq_val)
        except ValueError:
            pass
        slug = slugify(row.get("first_name","") + row.get("last_name","") + row.get("country",""))
        existing_slugs.add(slug)

print("  Befintliga: {} poster, max_seq={}".format(len(existing_rows), max_seq))

# ---- Fas 2: Wikipedia-skoerd ----
print("\n=== Fas 2: Wikipedia-skoerd ===")
new_rows = []
seq = max_seq
yield_log = []

for (lang, category, default_role, default_country) in CATEGORIES:
    print("  [{}] {} ...".format(lang, category), flush=True)
    members = fetch_category_members(lang, category)
    added = 0

    for m in members:
        title = m["title"]
        # Skippa listsidor, begreppsartiklar och kortare titlar
        if re.match(r"^(List|Lista|Lijst|Liste|Список|Luettelo)", title):
            continue
        # Skippa om titeln ser ut som ett begrepp snarare an person
        if any(x in title for x in ["UFO", "Roswell", "Area 51", "phenomenon", "incident", "wave", "sighting"]):
            continue

        first, last = parse_name(title)
        if not last or len(last) < 2:
            continue

        # Land
        country = default_country
        if not country:
            if lang == "en":
                country = get_en_country(title)
            else:
                en_title = get_en_title(lang, title)
                if en_title:
                    country = get_en_country(en_title)
                    time.sleep(0.15)
            time.sleep(0.15)

        # Dedup
        dedup_slug = slugify(first + last + (country or ""))
        if dedup_slug in existing_slugs:
            continue
        # Extra dedup: bara fornamn+efternamn utan land (fa inte in samma person fran flera kategorier)
        name_slug = slugify(first + last)
        if name_slug in existing_slugs:
            continue

        existing_slugs.add(dedup_slug)
        existing_slugs.add(name_slug)
        seq += 1
        uap_id = make_id("person", first, last, None, seq)
        wiki_url = "https://{}.wikipedia.org/wiki/{}".format(
            lang, urllib.parse.quote(title.replace(" ", "_"))
        )
        focus = "aerial;disclosure" if default_role in ("researcher","author") else "aerial"
        row = {
            "uap_source_id":    uap_id,
            "source_type":      "person",
            "first_name":       first,
            "last_name":        last,
            "role":             default_role,
            "organization":     "",
            "website":          wiki_url,
            "podcast_name":     "",
            "rss_feed":         "",
            "focus_areas":      focus,
            "language":         lang,
            "country":          country or "",
            "city":             "",
            "credibility_tier": "2",
            "social_media":     "",
            "email":            "",
            "phone":            "",
            "notes":            "Wikipedia [{}]: {}".format(lang, title),
            "data_source":      "wikipedia_" + lang,
        }
        new_rows.append(row)
        added += 1

    yield_log.append((lang, category, len(members), added))
    time.sleep(0.3)

# ---- Fas 3: Skriv v1.3.csv ----
print("\n=== Fas 3: Skriver v1.3.csv ===")
all_rows = existing_rows + new_rows

with open(DEST, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(all_rows)

print("\n" + "="*60)
print("UAP Sources v1.3 -- Byggrapport")
print("="*60)
print("Befintliga (v1.2):   {}".format(len(existing_rows)))
print("Nya (Wikipedia):     {}".format(len(new_rows)))
print("Totalt:              {}".format(len(all_rows)))
print("Sista seq:           {}".format(seq))
print("\nYield per kalla:")
total_fetched = total_added = 0
for lang, cat, fetched, added in yield_log:
    short = cat.split(":")[-1]
    print("  [{}] {:40s} fetched={:4d}  nya={:4d}".format(lang, short, fetched, added))
    total_fetched += fetched
    total_added   += added
print("  " + "-"*55)
print("  TOTALT{:42s} fetched={:4d}  nya={:4d}".format("", total_fetched, total_added))
print("="*60)
print("Skrivet: {}".format(DEST))
