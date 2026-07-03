"""
uap_migrate.py — Tre migrationssteg för clio_uap v1.2.0

Steg 1: Flytta 3 ORG_*-poster från uap.encounter → res.partner
Steg 2: Importera 241 organisationer från CSV → res.partner
Steg 3: Migrera befintliga uap.witness → res.partner + uap.encounter.witness

Kör: python3 uap_migrate.py [--dry-run] [--step 1|2|3|all]
"""
from __future__ import annotations
import argparse, csv, os, re, sys, xmlrpc.client
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = "uapdb"
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

CSV_PATH = Path("/tmp/uap_incidents_all.csv")

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
UID    = common.authenticate(DB, USER, PWD, {})
if not UID:
    sys.exit("Odoo-autentisering misslyckades")
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, kwargs=None):
    return M.execute_kw(DB, UID, PWD, model, method, args, kwargs or {})

# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

REGION_MAP = {
    "europe":        "europe",
    "north america": "north_america",
    "south america": "south_america",
    "asia":          "asia",
    "africa":        "africa",
    "oceania":       "oceania",
    "middle east":   "middle_east",
}

ORG_TYPE_MAP = {
    "org - ufo":       "ufo_org",
    "org - govt":      "govt",
    "org - government":"govt",
    "org - scientific":"scientific",
    "org - academic":  "scientific",
    "org - civilian":  "civilian",
    "org - lobby":     "lobby",
    "org - archive":   "archive",
    "org - library":   "archive",
}

DISC_MAP = {"1":"1","2":"2","3":"3","4":"4","5":"5"}
OFF_MAP  = {"a":"A","b":"B","c":"C","d":"D","e":"E"}

_COUNTRY_CACHE: dict[str, int] = {}

def country_id(name: str) -> int | bool:
    if not name:
        return False
    if name in _COUNTRY_CACHE:
        return _COUNTRY_CACHE[name]
    res = kw("res.country", "search_read", [[["name", "=", name]]], {"fields": ["id"], "limit": 1})
    cid = res[0]["id"] if res else False
    _COUNTRY_CACHE[name] = cid
    return cid

def extract_country(notion_link: str) -> str:
    """'Sweden (https://...)' → 'Sweden'"""
    if not notion_link:
        return ""
    m = re.match(r"^([^(]+)", notion_link.strip())
    return m.group(1).strip() if m else notion_link.strip()

def extract_disc(raw: str) -> str | bool:
    """'4 - Growing Interest' → '4'"""
    if not raw:
        return False
    m = re.match(r"^(\d)", raw.strip())
    return DISC_MAP.get(m.group(1), False) if m else False

def extract_off(raw: str) -> str | bool:
    """'C - Active Investigation' → 'C'"""
    if not raw:
        return False
    m = re.match(r"^([A-Ea-e])", raw.strip())
    return OFF_MAP.get(m.group(1).lower(), False) if m else False

def extract_region(raw: str) -> str | bool:
    return REGION_MAP.get(raw.strip().lower(), False)

def partner_exists(uap_id: str) -> int | None:
    res = kw("res.partner", "search_read",
             [[["uap_encounter_id", "=", uap_id]]],
             {"fields": ["id"], "limit": 1})
    return res[0]["id"] if res else None

# ---------------------------------------------------------------------------
# Steg 1 — Flytta 3 ORG-poster från uap.encounter → res.partner
# ---------------------------------------------------------------------------
ORG_ENC_IDS = ["ORG_SWE_001", "ORG_SWE_002", "ORG_FRA_001"]

def step1_migrate_enc_orgs(dry_run: bool):
    print("\n[STEG 1] Flytta uap.encounter ORG-poster → res.partner")
    orgs = kw("uap.encounter", "search_read",
              [[["encounter_id", "in", ORG_ENC_IDS]]],
              {"fields": ["id", "encounter_id", "title_en", "title_original",
                          "country_id", "region", "discourse_level", "official_response",
                          "description_en", "research_notes", "status"], "limit": 10})
    if not orgs:
        print("  Inga ORG-poster hittades i uap.encounter — redan migrerade?")
        return

    for enc in orgs:
        uap_id = enc["encounter_id"]
        existing = partner_exists(uap_id)
        if existing:
            print(f"  {uap_id}: finns redan som partner {existing} — hoppar över")
            continue

        vals = {
            "name":                enc.get("title_en") or enc.get("title_original") or uap_id,
            "is_company":          True,
            "uap_encounter_id":    uap_id,
            "uap_org_type":        "ufo_org",
            "uap_region":          enc.get("region") or False,
            "uap_discourse_level": enc.get("discourse_level") or False,
            "uap_official_response": enc.get("official_response") or False,
            "uap_research_notes":  enc.get("research_notes") or False,
            "country_id":          enc["country_id"][0] if enc.get("country_id") else False,
            "comment":             enc.get("description_en") or False,
        }
        if dry_run:
            print(f"  [DRY] Skapar partner: {vals['name']} ({uap_id})")
        else:
            pid = kw("res.partner", "create", [vals])
            print(f"  Skapade partner: {vals['name']} ({uap_id}) → ID {pid}")
            # Ta bort från uap.encounter
            kw("uap.encounter", "unlink", [[enc["id"]]])
            print(f"    Raderade uap.encounter ID {enc['id']}")

    print("  Steg 1 klart.")

# ---------------------------------------------------------------------------
# Steg 2 — Importera 241 org från CSV → res.partner
# ---------------------------------------------------------------------------

def step2_import_csv_orgs(dry_run: bool):
    print(f"\n[STEG 2] Importerar org-poster från CSV")
    if not CSV_PATH.exists():
        sys.exit(f"CSV saknas: {CSV_PATH}")

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    org_rows = [r for r in rows if r.get("Type_Select", "").lower().startswith("org")]
    print(f"  {len(org_rows)} org-rader i CSV")

    created = skipped = errors = 0
    for r in org_rows:
        uap_id    = r.get("IncidentTextID", "").strip()
        title_en  = r.get("Title_EN", "").strip()
        title_org = r.get("Title_Original", "").strip()
        name      = title_en or title_org or uap_id
        if not name:
            errors += 1
            continue

        # Kolla om redan finns
        existing = partner_exists(uap_id) if uap_id else None
        if existing:
            skipped += 1
            continue

        country_name = extract_country(r.get("Country_Linked", ""))
        cid          = country_id(country_name) if country_name else False
        region       = extract_region(r.get("Region (chart)", "") or r.get("Region", ""))
        disc         = extract_disc(r.get("Discourse_Level", ""))
        off          = extract_off(r.get("Official_Response", ""))
        org_type_raw = r.get("Type_Select", "").strip().lower()
        org_type     = ORG_TYPE_MAP.get(org_type_raw, "ufo_org")
        website      = r.get("Source URL", "").strip() or False
        description  = r.get("Description", "").strip() or False
        notes_raw    = r.get("Research_Notes", "").strip()

        # Bygg research_notes med titel original om den finns
        notes_parts = []
        if title_org and title_org != title_en:
            notes_parts.append(f"[ORG] {title_org}")
        if notes_raw:
            notes_parts.append(notes_raw)
        if description:
            notes_parts.append(f"[BAK] {description[:500]}")
        notes = "\n".join(notes_parts) or False

        vals = {
            "name":                  name,
            "is_company":            True,
            "uap_encounter_id":      uap_id or False,
            "uap_org_type":          org_type,
            "uap_region":            region or False,
            "uap_discourse_level":   disc or False,
            "uap_official_response": off or False,
            "uap_research_notes":    notes,
            "country_id":            cid or False,
            "website":               website,
        }

        if dry_run:
            print(f"  [DRY] {uap_id}: {name[:60]} ({country_name}, {org_type})")
        else:
            try:
                pid = kw("res.partner", "create", [vals])
                created += 1
                if created % 20 == 0:
                    print(f"  ... {created} skapade")
            except Exception as e:
                print(f"  FEL {uap_id}: {e}")
                errors += 1

    if dry_run:
        print(f"\n  [DRY] Skulle skapat: ~{len(org_rows)-skipped} | Redan finns: {skipped}")
    else:
        print(f"\n  Skapade: {created} | Redan finns: {skipped} | Fel: {errors}")
    print("  Steg 2 klart.")

# ---------------------------------------------------------------------------
# Steg 3 — Migrera uap.witness → res.partner + uap.encounter.witness
# ---------------------------------------------------------------------------

def step3_migrate_witnesses(dry_run: bool):
    print("\n[STEG 3] Migrera uap.witness → res.partner + uap.encounter.witness")

    witnesses = kw("uap.witness", "search_read", [[]], {
        "fields": ["id", "name", "witness_type", "credibility", "url",
                   "status", "encounter_ids"],
        "limit": 500,
    })
    print(f"  {len(witnesses)} vittnen hittade i uap.witness")

    if not witnesses:
        print("  Inga vittnen att migrera.")
        return

    created_p = created_w = skipped = errors = 0

    for w in witnesses:
        wname = w.get("name", "").strip()
        if not wname:
            errors += 1
            continue

        # Kolla om partner redan finns (på namn, enkel heuristik)
        existing = kw("res.partner", "search_read",
                      [[["name", "=", wname], ["is_company", "=", False]]],
                      {"fields": ["id"], "limit": 1})

        if existing:
            pid = existing[0]["id"]
            skipped += 1
        else:
            p_vals = {
                "name":       wname,
                "is_company": False,
                "website":    w.get("url") or False,
                "comment":    w.get("status") or False,
            }
            if dry_run:
                pid = -1
                print(f"  [DRY] Skapar person-partner: {wname}")
            else:
                pid = kw("res.partner", "create", [p_vals])
                created_p += 1

        # Skapa uap.encounter.witness-kopplingar
        for enc_id in (w.get("encounter_ids") or []):
            enc_exists = kw("uap.encounter", "search_count", [[["id", "=", enc_id]]])
            if not enc_exists:
                continue
            already = kw("uap.encounter.witness", "search_count",
                         [[["encounter_id", "=", enc_id], ["partner_id", "=", pid]]])
            if already:
                continue
            ew_vals = {
                "encounter_id": enc_id,
                "partner_id":   pid,
                "witness_type": w.get("witness_type") or False,
                "credibility":  w.get("credibility") or False,
                "role":         "primary",
            }
            if dry_run:
                print(f"    [DRY] Kopplar {wname} → encounter {enc_id}")
            else:
                try:
                    kw("uap.encounter.witness", "create", [ew_vals])
                    created_w += 1
                except Exception as e:
                    print(f"    FEL koppling {wname}→{enc_id}: {e}")
                    errors += 1

    if dry_run:
        print(f"\n  [DRY] Skulle skapa ~{len(witnesses)} partner-poster + encounter.witness-kopplingar")
    else:
        print(f"\n  Skapade partner: {created_p} | Redan fanns: {skipped}")
        print(f"  Skapade enc.witness-kopplingar: {created_w} | Fel: {errors}")
    print("  Steg 3 klart.")

# ---------------------------------------------------------------------------
# Sammanfattning
# ---------------------------------------------------------------------------

def print_summary():
    orgs  = kw("res.partner", "search_count", [[["uap_org_type", "!=", False]]])
    dbs   = kw("uap.database", "search_count", [[]])
    enc   = kw("uap.encounter", "search_count", [[]])
    wit   = kw("uap.encounter.witness", "search_count", [[]])
    print(f"\n{'='*60}")
    print(f"  UAP-databas status efter migration:")
    print(f"  res.partner (org)          : {orgs}")
    print(f"  uap.database               : {dbs}")
    print(f"  uap.encounter              : {enc}")
    print(f"  uap.encounter.witness      : {wit}")
    print(f"{'='*60}")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--step", choices=["1","2","3","all"], default="all")
    args = ap.parse_args()

    dry = args.dry_run
    if dry:
        print("*** DRY RUN — inga ändringar sparas ***")

    if args.step in ("1", "all"):
        step1_migrate_enc_orgs(dry)
    if args.step in ("2", "all"):
        step2_import_csv_orgs(dry)
    if args.step in ("3", "all"):
        step3_migrate_witnesses(dry)

    if not dry:
        print_summary()
