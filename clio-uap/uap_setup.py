"""
uap_setup.py — Backfill region för befintliga encounters + importera org-poster.

Kör: cd ~/clio-tools/clio-uap && python3 uap_setup.py
"""
from __future__ import annotations
import os, sys, xmlrpc.client
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = "uapdb"
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
UID    = common.authenticate(DB, USER, PWD, {})
if not UID:
    sys.exit("Odoo-autentisering misslyckades")
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, kwargs=None):
    return M.execute_kw(DB, UID, PWD, model, method, args, kwargs or {})

# ---------------------------------------------------------------------------
# Land → Region-karta
# ---------------------------------------------------------------------------
COUNTRY_REGION = {
    # Europa
    "Sweden": "europe", "France": "europe", "Germany": "europe",
    "United Kingdom": "europe", "Spain": "europe", "Italy": "europe",
    "Norway": "europe", "Denmark": "europe", "Finland": "europe",
    "Belgium": "europe", "Netherlands": "europe", "Switzerland": "europe",
    "Austria": "europe", "Portugal": "europe", "Poland": "europe",
    "Russia": "europe", "Greece": "europe", "Czech Republic": "europe",
    "Hungary": "europe", "Romania": "europe", "Bulgaria": "europe",
    "Serbia": "europe", "Croatia": "europe", "Slovakia": "europe",
    "Slovenia": "europe", "Estonia": "europe", "Latvia": "europe",
    "Lithuania": "europe", "Ukraine": "europe",
    # Nordamerika
    "United States": "north_america", "Canada": "north_america",
    "Mexico": "north_america",
    # Sydamerika
    "Brazil": "south_america", "Argentina": "south_america",
    "Chile": "south_america", "Peru": "south_america",
    "Colombia": "south_america", "Venezuela": "south_america",
    "Bolivia": "south_america", "Uruguay": "south_america",
    "Ecuador": "south_america", "Paraguay": "south_america",
    # Asien
    "Japan": "asia", "China": "asia", "India": "asia",
    "South Korea": "asia", "Taiwan": "asia", "Philippines": "asia",
    "Indonesia": "asia", "Thailand": "asia", "Vietnam": "asia",
    "Malaysia": "asia", "Pakistan": "asia", "Afghanistan": "asia",
    "Kazakhstan": "asia",
    # Afrika
    "South Africa": "africa", "Nigeria": "africa", "Kenya": "africa",
    "Ethiopia": "africa", "Egypt": "africa", "Morocco": "africa",
    "Tanzania": "africa", "Zimbabwe": "africa",
    # Oceanien
    "Australia": "oceania", "New Zealand": "oceania",
    "Papua New Guinea": "oceania",
    # Mellanöstern
    "Israel": "middle_east", "Iran": "middle_east", "Iraq": "middle_east",
    "Saudi Arabia": "middle_east", "Turkey": "middle_east",
    "United Arab Emirates": "middle_east", "Jordan": "middle_east",
    "Lebanon": "middle_east", "Syria": "middle_east",
}

# ---------------------------------------------------------------------------
# 1. Backfill region baserat på country_id
# ---------------------------------------------------------------------------
print("\n[1/3] Backfill region för befintliga encounters...")

# Hämta alla länder
countries = {r["id"]: r["name"] for r in kw(
    "res.country", "search_read", [[]], {"fields": ["id", "name"]}
)}

# Hämta alla encounters med country_id men utan region
encounters = kw("uap.encounter", "search_read",
    [[["country_id", "!=", False]]],
    {"fields": ["id", "country_id", "region"], "limit": 2000}
)

updated = 0
skipped = 0
for enc in encounters:
    if enc.get("region"):
        skipped += 1
        continue
    country_name = enc["country_id"][1] if enc["country_id"] else ""
    region = COUNTRY_REGION.get(country_name)
    if region:
        kw("uap.encounter", "write", [[enc["id"]], {"region": region}])
        updated += 1

print(f"  Uppdaterade: {updated} | Redan satta: {skipped} | Inget land: {len(encounters)-updated-skipped}")

# ---------------------------------------------------------------------------
# 2. Importera org-poster
# ---------------------------------------------------------------------------
print("\n[2/3] Importerar org-poster från Notion...")

def country_id(name):
    res = kw("res.country", "search_read", [[["name", "=", name]]], {"fields": ["id"], "limit": 1})
    return res[0]["id"] if res else False

ORGS = [
    {
        "encounter_id":   "ORG_SWE_001",
        "title_en":       "UFO-Sverige — Sweden's National UFO Research Organization",
        "title_original": "Riksorganisationen UFO-Sverige",
        "description_en": (
            "UFO-Sverige is Sweden's national nonprofit UFO research organization, founded in 1970 "
            "as an umbrella group for local UFO societies and individual enthusiasts. The organization "
            "focuses on collecting and investigating UFO reports from the public using a science-oriented, "
            "critical but open-minded approach. It conducts field investigator training, publishes findings "
            "in its journals and online, and emphasizes documenting unexplained aerial phenomena without "
            "political or religious affiliation. UFO-Sverige cooperates closely with the AFU archive in Norrköping "
            "and receives roughly 250 reports per year."
        ),
        "description_sv": (
            "UFO-Sverige är Sveriges nationella ideella ufoorganisation, grundad 1970 som paraplyorganisation "
            "för lokala ufogrupper och enskilda intresserade. Organisationen fokuserar på att samla in och "
            "undersöka uforapporter från allmänheten med ett vetenskapligt inriktat, kritiskt men öppet "
            "förhållningssätt. Den utbildar fältundersökare, publicerar resultat i tidskrifter och på nätet "
            "samt samarbetar nära med AFU-arkivet i Norrköping."
        ),
        "record_type":    "org",
        "encounter_class": False,
        "discourse_level": "3",
        "official_response": "B",
        "status":         "verified",
        "country_id":     country_id("Sweden"),
        "region":         "europe",
        "location":       "Sweden (national organization)",
        "language_original": "sv",
        "research_notes": (
            "[ORG] UFO-Sverige, grundad 1970. Rikstäckande ideell organisation.\n"
            "[BAK] Sveriges enda uttalat vetenskapsinriktade ufoorganisation.\n"
            "[UTB] Samlar och utreder UFO-rapporter; utbildar fältundersökare; ~250 rapporter/år.\n"
            "[OFF] B - Acknowledgment Only (civil organisation, ej statlig).\n"
            "[SRC] https://www.ufo.se/index.php/english"
        ),
    },
    {
        "encounter_id":   "ORG_SWE_002",
        "title_en":       "Archives for the Unexplained (AFU) — Swedish UFO and Anomalies Archive",
        "title_original": "Archives for the Unexplained (Arkivet för UFO-forskning)",
        "description_en": (
            "Archives for the Unexplained (AFU) is a nonprofit foundation and archive in Norrköping, Sweden, "
            "dedicated to collecting materials on UFOs, Forteana, cryptozoology, paranormal phenomena, and folklore. "
            "Founded in 1973, AFU manages UFO-Sverige's report archive and has built one of the world's largest "
            "specialized UFO research libraries, including around 20,000 Swedish UFO observation reports and copies "
            "of approximately 2,000 open UFO investigations by the Swedish Armed Forces since 1946. "
            "AFU operates through volunteers and private donations and serves as an international research resource."
        ),
        "description_sv": (
            "Archives for the Unexplained (AFU) är en ideell stiftelse och ett arkiv i Norrköping som samlar "
            "material om ufo, ufologi, forteana, kryptozoologi, paranormala fenomen och folklore. "
            "AFU grundades 1973 och förvaltar UFO-Sveriges rapportarkiv med ~20 000 svenska ufoobservationsrapporter "
            "och kopior av ~2 000 öppna utredningar från Försvarsmakten sedan 1946."
        ),
        "record_type":    "archive",
        "encounter_class": False,
        "discourse_level": "2",
        "official_response": "B",
        "status":         "verified",
        "country_id":     country_id("Sweden"),
        "region":         "europe",
        "location":       "Norrköping, Östergötland, Sweden",
        "language_original": "sv",
        "research_notes": (
            "[ORG] AFU — Archives for the Unexplained, grundad 1973, Norrköping.\n"
            "[BAK] Världens största specialiserade ufoforskningsbibliotek. ~20 000 svenska fall.\n"
            "[UTB] Förvaltar UFO-Sveriges rapportarkiv; militärfiler (spökraketer 1946).\n"
            "[OFF] B - Acknowledgment Only (civil arkivorganisation).\n"
            "[SRC] https://en.wikipedia.org/wiki/Archives_for_the_Unexplained"
        ),
    },
    {
        "encounter_id":   "ORG_FRA_001",
        "title_en":       "GEIPAN — French CNES Official UAP Investigation Unit",
        "title_original": "GEIPAN — Groupe d'Étude et d'Information sur les Phénomènes Aérospatiaux Non-identifiés",
        "description_en": (
            "GEIPAN is a technical department within the French space agency CNES, created in 1977 to collect, "
            "analyze, investigate, publish and archive reports of unidentified aerospace phenomena from civilians "
            "and authorities in France. The unit applies standardized scientific methods and publishes investigation "
            "files on its public website. GEIPAN is the successor to GEPAN (1977) and SEPRA (1988) and maintains "
            "a large database of civilian and military UAP observations. It represents one of the few official "
            "state-backed UAP investigation programs with public transparency in the Western world."
        ),
        "description_sv": (
            "GEIPAN är en teknisk avdelning inom den franska rymdorganisationen CNES, bildad 1977 för att samla in, "
            "analysera, undersöka, publicera och arkivera rapporter om oidentifierade rymd- och flygfenomen. "
            "Enheten publicerar utredningsakter öppet och är ett av få officiella statliga UAP-program i västvärlden."
        ),
        "record_type":    "org",
        "encounter_class": False,
        "discourse_level": "4",
        "official_response": "E",
        "status":         "verified",
        "country_id":     country_id("France"),
        "region":         "europe",
        "location":       "Toulouse, Occitanie, France",
        "language_original": "fr",
        "research_notes": (
            "[ORG] GEIPAN — statligt UAP-program inom CNES, Frankrike. Grundat 1977.\n"
            "[BAK] Successor till GEPAN (1977) och SEPRA (1988). Officiellt program med öppen publicering.\n"
            "[UTB] Samlar civila och militära rapporter; publicerar utredningar på cnes-geipan.fr.\n"
            "[OFF] E - Policy/Legislative Action: statligt program inrättat via CNES-beslut.\n"
            "[INT] Ett av få officiella statliga UAP-program med öppen publicering i västvärlden.\n"
            "[SRC] https://www.cnes-geipan.fr/en/missions-methodes-et-resultats"
        ),
    },
]

imported = 0
skipped_orgs = 0
for org in ORGS:
    existing = kw("uap.encounter", "search_read",
        [[["encounter_id", "=", org["encounter_id"]]]],
        {"fields": ["id"], "limit": 1}
    )
    if existing:
        print(f"  Finns redan: {org['encounter_id']}")
        skipped_orgs += 1
        continue
    rid = kw("uap.encounter", "create", [org])
    print(f"  Importerad: {org['encounter_id']} → Odoo ID {rid}")
    imported += 1

print(f"\n  Importerade: {imported} | Redan finns: {skipped_orgs}")

# ---------------------------------------------------------------------------
# 3. Sammanfattning
# ---------------------------------------------------------------------------
total = kw("uap.encounter", "search_count", [[]])
orgs_count = kw("uap.encounter", "search_count", [[["record_type", "in", ["org", "archive"]]]])
with_region = kw("uap.encounter", "search_count", [[["region", "!=", False]]])
print(f"\n[3/3] Status i uapdb:")
print(f"  Totalt encounters : {total}")
print(f"  Org/archive-poster: {orgs_count}")
print(f"  Med region satt   : {with_region}")
print("\nKlar.")
