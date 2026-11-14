"""
uap_enrich.py — Berika uap.encounter med översättningar och klassificering

Kör ett lokalt Ollama-anrop per encounter som:
  1. Tar raw_description från länkade uap.report-poster
  2. Vet språket från källmappningen (ingen LLM-detektion)
  3. Returnerar JSON med översättningar (EN + SV) + klassificering + ETH-bedömning

Skriver till uap.encounter:
  description_original, description_en, description_sv, language_original,
  encounter_class, discourse_level, official_response,
  eth_origin, intelligence_indicator,
  obs_antigravity, obs_instant_accel, obs_hypersonic, obs_low_observability, obs_transmedium

Kör: python3 uap_enrich.py [--dry-run] [--max 50] [--model qwen2.5:14b] [--source GEIPAN]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xmlrpc.client
from pathlib import Path
from dotenv import load_dotenv

try:
    import requests
except ImportError:
    sys.exit("requests saknas — kör: pip install requests")

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("VIGIL_ODOO_URL", os.getenv("ODOO_URL", "http://localhost:8069"))
DB   = os.getenv("VIGIL_ODOO_DB", os.getenv("ODOO_DB", "uap"))
USER = os.getenv("VIGIL_ODOO_USER", os.getenv("ODOO_USER", ""))
PWD  = os.getenv("VIGIL_ODOO_PASSWORD", os.getenv("ODOO_PASSWORD", ""))

OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = "qwen2.5:14b"

# ---------------------------------------------------------------------------
# Källmappning: databasnamn → ISO-639-1 språkkod
# ---------------------------------------------------------------------------
SOURCE_LANG: dict[str, str] = {
    "GEIPAN":                                  "fr",
    "COBEPS — Comité Belge d'Étude des Phénomènes Spatiaux": "fr",
    "EuroUFO — COBEPS":                        "fr",
    "CENAP — Centrales Erforschungsnetz außergewöhnlicher Phänomene": "de",
    "GEP — Gesellschaft zur Erforschung von Phänomenen": "de",
    "EuroUFO — CENAP":                         "de",
    "EuroUFO — GEP":                           "de",
    "CISU — Centro Italiano Studi Ufologici":  "it",
    "EuroUFO — CISU":                          "it",
    "EuroUFO — ERENZO":                        "it",
    "EuroUFO — UFOSETI":                       "it",
    "SEFAA — Sección de Estudios de Fenómenos Aéreos Anómalos (Chile)": "es",
    "CUCO — Club Ufológico Canario":           "es",
    "EuroUFO — ASFAN":                         "es",
    "NUFORC — National UFO Reporting Center":  "en",
    "MUFON Case Management System":            "en",
    "EuroUFO — ENIGMA LABS":                   "en",
    "EuroUFO — FUFORA":                        "en",
    "EuroUFO — CTEC-STELLAR":                  "en",
    "NL-UFOM — Dutch UFO Meldpunt":            "nl",
    "BE-UFOM — Belgian UFO Meldpunt":          "nl",
    "SUFOI — Skandinavisk UFO Information":    "da",
    "EuroUFO — SUFOI":                         "da",
    "EuroUFO — TÝM ZÁŘE":                     "other",
    "EuroUFO — SRCAA ZOND":                   "other",
    "EuroUFO — UFO-SVERIGE":                   "sv",
}

LANG_NAMES = {
    "fr": "French", "de": "German", "it": "Italian", "es": "Spanish",
    "nl": "Dutch",  "da": "Danish", "en": "English", "sv": "Swedish",
    "pt": "Portuguese", "other": "Unknown",
}

VALID_LANG  = set(LANG_NAMES.keys())
VALID_CLASS = {"1", "2", "3", "4", "5"}
VALID_DISC  = {"1", "2", "3", "4", "5"}
VALID_RESP  = {"A", "B", "C", "D", "E"}
VALID_ETH   = {"0", "1", "2", "3", "4", "5"}
VALID_INT   = {"0", "1", "2", "3"}

# ---------------------------------------------------------------------------
# Odoo
# ---------------------------------------------------------------------------
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
UID    = common.authenticate(DB, USER, PWD, {})
if not UID:
    sys.exit("Odoo-autentisering misslyckades")
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, kwargs=None):
    return M.execute_kw(DB, UID, PWD, model, method, args, kwargs or {})

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a UAP (Unidentified Aerial Phenomena) analyst. Given a report description in a \
specified language, you will produce a structured JSON analysis.

--- TRANSLATION ---
Provide the original text (cleaned), an English translation, and a Swedish translation.

--- ENCOUNTER CLASSIFICATION ---
encounter_class:
  "1" = Sighting (visual observation only)
  "2" = Close Encounter (interaction / witness or vehicle reacts)
  "3" = Physical Evidence (traces, photo, radar, measurements)
  "4" = Abduction / Contact (direct contact with non-human intelligence)
  "5" = Media / Cultural Reference (debate, historical, no new incident)

discourse_level (how publicly acknowledged is this phenomenon type):
  "1" = Fringe / Unknown
  "2" = Limited Public Awareness
  "3" = Active Public Debate
  "4" = Official Acknowledgement
  "5" = Confirmed / Declassified

official_response:
  "A" = No Response
  "B" = Denial
  "C" = Acknowledgement
  "D" = Investigation
  "E" = Confirmation

--- NON-HUMAN INTELLIGENCE HYPOTHESIS ---
The central question: Does this report contain EVIDENCE (not just claims or beliefs)
that non-human intelligence of non-Earth origin is currently present on Earth?

Score eth_origin and intelligence_indicator based ONLY on what is described as
observable in the text — physical behaviour, sensor data, traces, craft performance.
A witness CLAIMING abduction or contact is NOT evidence. Score what is DESCRIBED.

eth_origin (evidence strength for non-human, non-Earth origin):
  "0" = Explained — conventional explanation confirmed, or no anomaly described
  "1" = Unexplained, but no specific ETH indicators in the description
  "2" = Craft performance described beyond known human technology (speed, maneuver, silence)
  "3" = Physical evidence OR multi-witness OR official investigation described in text
  "4" = Multiple strong indicators: anomalous materials, physics-defying performance,
        and/or corroborated by independent sources described in the text
  "5" = Reserved — do NOT assign unless text contains explicit confirmation of non-human origin
        from an authoritative source (government document, scientific analysis, etc.)

IMPORTANT: eth=3 requires at least ONE of: physical traces, radar confirmation, multiple
independent witnesses, or official documented investigation — described in the text.
eth=4-5 must NOT be assigned based solely on a witness claiming contact or abduction.

intelligence_indicator (evidence of intentional non-human intelligence):
  "0" = No indicators of intelligence — random or unexplained movement only
  "1" = Structured or controlled movement suggesting artificial (not necessarily non-human) origin
  "2" = Object demonstrably REACTS to the witness — changes course, approaches, responds
        (must be described as reaction, not coincidence)
  "3" = Described physical interaction, communication attempt, or crew/occupants directly observed
        (witness claim alone is insufficient — the interaction must be described in detail)

--- PENTAGON FIVE OBSERVABLES (AARO) ---
Score each as true/false based on whether the report describes it:
  obs_antigravity     : Levitates or moves without apparent propulsion, wings or control surfaces
  obs_instant_accel   : Sudden acceleration or direction change impossible for known craft
  obs_hypersonic      : Extreme speed without sonic boom, heat signature or visible exhaust
  obs_low_observability: Appears/disappears, evades radar, or exhibits stealth characteristics
  obs_transmedium     : Moves between air, water and/or space without transition effects

Respond ONLY with valid JSON. No explanation, no markdown, no preamble.
"""

USER_TEMPLATE = """\
Source: {source}
Language: {lang_name}
Title: {title}

Description ({lang_name}):
{description}

Return JSON:
{{
  "description_original": "cleaned original text",
  "description_en": "English translation",
  "description_sv": "Swedish translation",
  "encounter_class": "1"|"2"|"3"|"4"|"5",
  "discourse_level": "1"|"2"|"3"|"4"|"5",
  "official_response": "A"|"B"|"C"|"D"|"E",
  "eth_origin": "0"|"1"|"2"|"3"|"4"|"5",
  "intelligence_indicator": "0"|"1"|"2"|"3",
  "obs_antigravity": true|false,
  "obs_instant_accel": true|false,
  "obs_hypersonic": true|false,
  "obs_low_observability": true|false,
  "obs_transmedium": true|false
}}
"""


def ollama_enrich(source: str, lang_code: str, title: str,
                  description: str, model: str) -> dict | None:
    lang_name = LANG_NAMES.get(lang_code, "Unknown")
    user_msg  = USER_TEMPLATE.format(
        source=source,
        lang_name=lang_name,
        title=title or "(no title)",
        description=description[:3000],
    )

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model":  model,
                "format": "json",
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
    except Exception as e:
        print(f"    Ollama-fel: {e}")
        return None

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group())
            except json.JSONDecodeError:
                print(f"    JSON-parse-fel: {raw[:200]}")
                return None
        else:
            print(f"    Inget JSON i svar: {raw[:200]}")
            return None

    enc  = str(result.get("encounter_class", ""))
    disc = str(result.get("discourse_level", "1"))
    resp = str(result.get("official_response", "A"))
    eth  = str(result.get("eth_origin", "1"))
    intl = str(result.get("intelligence_indicator", "0"))

    return {
        "description_original":  (result.get("description_original") or "")[:4000],
        "description_en":        (result.get("description_en") or "")[:4000],
        "description_sv":        (result.get("description_sv") or "")[:4000],
        "encounter_class":       enc  if enc  in VALID_CLASS else False,
        "discourse_level":       disc if disc in VALID_DISC  else False,
        "official_response":     resp if resp in VALID_RESP  else False,
        "eth_origin":            eth  if eth  in VALID_ETH   else False,
        "intelligence_indicator": intl if intl in VALID_INT  else False,
        "obs_antigravity":       bool(result.get("obs_antigravity", False)),
        "obs_instant_accel":     bool(result.get("obs_instant_accel", False)),
        "obs_hypersonic":        bool(result.get("obs_hypersonic", False)),
        "obs_low_observability": bool(result.get("obs_low_observability", False)),
        "obs_transmedium":       bool(result.get("obs_transmedium", False)),
    }

# ---------------------------------------------------------------------------
# Kandidathämtning
# ---------------------------------------------------------------------------

def get_candidates(source_filter: str | None, max_items: int) -> list[dict]:
    # Steg 1: hämta encounter_ids för rapporter med raw_description (paginerat)
    print("  Hämtar rapport-encounter_ids...", flush=True)
    enc_ids_with_reports: set[int] = set()
    offset = 0
    chunk = 5000
    while True:
        rows = kw("uap.report", "search_read",
                  [[["encounter_id", "!=", False],
                    ["raw_description", "not in", [False, ""]]]],
                  {"fields": ["encounter_id"], "limit": chunk, "offset": offset})
        if not rows:
            break
        for r in rows:
            if r.get("encounter_id"):
                enc_ids_with_reports.add(r["encounter_id"][0])
        if len(rows) < chunk:
            break
        offset += chunk
    print(f"  Encounters med rapporter: {len(enc_ids_with_reports)}", flush=True)

    if not enc_ids_with_reports:
        return []

    # Steg 2: av dessa, filtrera ut de som saknar description_en eller eth_origin
    need_domain = [
        ["id", "in", list(enc_ids_with_reports)],
        "|",
        ["description_en", "in", [False, ""]],
        ["eth_origin", "in", [False, ""]],
    ]
    enc_fields = ["id", "encounter_id", "title_en", "database_id"]
    encounters = kw("uap.encounter", "search_read", [need_domain],
                    {"fields": enc_fields, "limit": max_items * 2})
    print(f"  Encounters att berika (råa): {len(encounters)}", flush=True)

    # Bygg db_cache och tillämpa source_filter i Python
    db_cache: dict[int, tuple[str, str]] = {}
    filtered_encs = []
    for enc in encounters:
        db_entry = enc.get("database_id")
        if not db_entry:
            continue
        db_id, db_name = db_entry[0], db_entry[1]
        if db_id not in db_cache:
            lang = SOURCE_LANG.get(db_name)
            db_cache[db_id] = (db_name, lang or "")
        _, lang = db_cache[db_id]
        if not lang:
            continue
        if source_filter and source_filter.lower() not in db_name.lower():
            continue
        filtered_encs.append((enc, db_name, lang))

    if not filtered_encs:
        return []

    # Steg 3: batch-hämta rapporter för alla kvalificerade encounters i ETT anrop
    qualified_ids = [enc["id"] for enc, _, _ in filtered_encs]
    print(f"  Hämtar rapporter (batch) för {len(qualified_ids)} encounters...", flush=True)

    reports_by_enc: dict[int, list[dict]] = {}
    offset = 0
    chunk = 5000
    while True:
        rrows = kw("uap.report", "search_read",
                   [[["encounter_id", "in", qualified_ids],
                     ["raw_description", "not in", [False, ""]]]],
                   {"fields": ["encounter_id", "raw_title", "raw_description"],
                    "limit": chunk, "offset": offset})
        if not rrows:
            break
        for r in rrows:
            eid_entry = r.get("encounter_id")
            if not eid_entry:
                continue
            eid = eid_entry[0]
            if eid not in reports_by_enc:
                reports_by_enc[eid] = []
            if len(reports_by_enc[eid]) < 3:
                reports_by_enc[eid].append(r)
        if len(rrows) < chunk:
            break
        offset += chunk
    print(f"  Rapporter inladdade för {len(reports_by_enc)} encounters", flush=True)

    # Steg 4: bygg kandidatlistan
    candidates = []
    for enc, db_name, lang in filtered_encs:
        reports = reports_by_enc.get(enc["id"], [])
        if not reports:
            continue
        desc_parts  = [r["raw_description"] for r in reports if r.get("raw_description")]
        title_parts = [r["raw_title"]       for r in reports if r.get("raw_title")]
        combined_desc = "\n\n".join(desc_parts).strip()
        # Detektera om beskrivning saknar riktig text
        _words = [w for w in combined_desc.split()
                  if len(w) >= 4 and not w.startswith("http")
                  and ":" not in w and "|" not in w]
        too_short = (
            len(combined_desc) < 30
            or combined_desc.lower().startswith("http")
            or combined_desc.lower().startswith("rapport pdf")
            or combined_desc.lower().startswith("pdf:")
            or combined_desc.count("http") >= len(combined_desc.split()) // 2
            or len(_words) < 3
        )
        candidates.append({
            "enc_id":    enc["id"],
            "enc_ref":   enc["encounter_id"],
            "title":     enc.get("title_en") or " | ".join(title_parts),
            "source":    db_name,
            "lang":      lang,
            "desc":      combined_desc,
            "too_short": too_short,
        })
        if len(candidates) >= max_items:
            break

    print(f"  Kandidater: {len(candidates)}", flush=True)
    return candidates

# ---------------------------------------------------------------------------
# Huvud
# ---------------------------------------------------------------------------

def classify_geipan(desc: str) -> tuple[str | None, str]:
    """Returnerar (geipan_type, description_en) för GEIPAN A/B, annars (None, "")."""
    import re
    m = re.match(r"\[GEIPAN ([ABCD])", desc)
    if not m:
        return None, ""
    gtype = m.group(1)
    # Extrahera Identification:-raden som description_en
    id_match = re.search(r"Identification:\s*(.+?)(?:\n|$)", desc)
    id_line = id_match.group(1).strip() if id_match else ""
    return gtype, f"[GEIPAN {gtype}] {id_line}" if id_line else f"[GEIPAN {gtype}]"


def run(dry_run: bool, max_items: int, model: str, source_filter: str | None):
    print(f"\n{'─'*60}")
    print("  UAP Enrichment — översättning + klassificering + ETH")
    print(f"{'─'*60}")
    print(f"  Modell  : {model}")
    print(f"  Max     : {max_items}")
    print(f"  Källa   : {source_filter or 'alla'}")
    if dry_run:
        print("  *** DRY RUN ***")

    try:
        pong = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        available = [m["name"] for m in pong.json().get("models", [])]
        if model not in available:
            print(f"\n  VARNING: modell '{model}' saknas. Tillgängliga: {available}")
            if not dry_run:
                sys.exit(1)
    except Exception as e:
        print(f"\n  VARNING: Kan inte nå Ollama ({e})")
        if not dry_run:
            sys.exit(1)

    candidates = get_candidates(source_filter, max_items)
    print(f"  Kandidater: {len(candidates)}\n")

    if not candidates:
        print("  Inga encounters att berika.")
        return

    done = errors = 0
    obs_total = [0, 0, 0, 0, 0]
    t0 = time.time()

    for i, c in enumerate(candidates, 1):
        print(f"  [{i}/{len(candidates)}] {c['enc_ref']} | {c['lang']} | {c['source'][:40]}")

        if c.get("too_short"):
            if dry_run:
                print(f"         [FÖR KORT — markeras utan Ollama]")
                done += 1
                continue
            try:
                kw("uap.encounter", "write", [[c["enc_id"]], {
                    "description_en": "[Otillräcklig beskrivning — kan ej bedömas]",
                    "eth_origin": "0",
                }])
                print(f"         [FÖR KORT — markerad eth=0]")
                done += 1
            except Exception as e:
                print(f"         Odoo-skrivfel (too_short): {e}")
                errors += 1
            continue

        # GEIPAN pre-processor: sätt ETH direkt från officiell klassificering
        gtype, gdesc = classify_geipan(c["desc"])
        if gtype in ("A", "B"):
            eth = "0" if gtype == "A" else "1"
            if dry_run:
                print(f"         [GEIPAN {gtype} — eth={eth}, hoppar Ollama]")
                done += 1
                continue
            try:
                kw("uap.encounter", "write", [[c["enc_id"]], {
                    "description_en":    gdesc or False,
                    "eth_origin":        eth,
                    "intelligence_indicator": "0",
                    "encounter_class":   "1",
                    "discourse_level":   "3",
                    "official_response": "C",
                }])
                print(f"         [GEIPAN {gtype} — eth={eth}]")
                done += 1
            except Exception as e:
                print(f"         Odoo-skrivfel (GEIPAN {gtype}): {e}")
                errors += 1
            continue

        if dry_run:
            print(f"         Titel : {c['title'][:60]}")
            print(f"         Beskr : {c['desc'][:80]}...")
            done += 1
            continue

        result = ollama_enrich(c["source"], c["lang"], c["title"], c["desc"], model)
        if result is None:
            errors += 1
            continue

        vals = {
            "language_original":     c["lang"],
            "obs_antigravity":       result["obs_antigravity"],
            "obs_instant_accel":     result["obs_instant_accel"],
            "obs_hypersonic":        result["obs_hypersonic"],
            "obs_low_observability": result["obs_low_observability"],
            "obs_transmedium":       result["obs_transmedium"],
            "observables_count":     sum([
                result["obs_antigravity"],
                result["obs_instant_accel"],
                result["obs_hypersonic"],
                result["obs_low_observability"],
                result["obs_transmedium"],
            ]),
        }
        # Skriv bara textfält när de faktiskt har innehåll — undvik att nolla befintliga värden
        if result["description_original"]:
            vals["description_original"] = result["description_original"]
        if result["description_en"]:
            vals["description_en"] = result["description_en"]
        if result["description_sv"]:
            vals["description_sv"] = result["description_sv"]
        for f in ("encounter_class", "discourse_level", "official_response",
                  "eth_origin", "intelligence_indicator"):
            if result[f]:
                vals[f] = result[f]

        try:
            kw("uap.encounter", "write", [[c["enc_id"]], vals])
            obs = sum([result["obs_antigravity"], result["obs_instant_accel"],
                       result["obs_hypersonic"], result["obs_low_observability"],
                       result["obs_transmedium"]])
            print(f"         cls={result['encounter_class']} eth={result['eth_origin']} "
                  f"int={result['intelligence_indicator']} obs={obs}/5")
            done += 1
        except Exception as e:
            print(f"         Odoo-skrivfel: {e}")
            errors += 1

    elapsed = time.time() - t0
    print(f"\n  Klara    : {done}")
    print(f"  Fel      : {errors}")
    print(f"  Tid      : {elapsed:.0f}s ({elapsed/max(done,1):.1f}s/encounter)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run",  action="store_true")
    ap.add_argument("--max",      type=int, default=50)
    ap.add_argument("--model",    default=DEFAULT_MODEL)
    ap.add_argument("--source",   default=None)
    args = ap.parse_args()
    run(args.dry_run, args.max, args.model, args.source)
