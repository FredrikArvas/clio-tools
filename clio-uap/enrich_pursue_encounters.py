#!/usr/bin/env python3
"""
enrich_pursue_encounters.py — Berika PURSUE-encounters med ETH + observables

Läser description_en direkt från uap.encounter (inga uap.report-poster krävs).
Bevarar: discourse_level=5, official_response=E (skrivs aldrig över).
Uppdaterar: eth_origin, intelligence_indicator, obs_*, observables_count,
            description_sv, encounter_class (om Ollama ger bättre svar).

Körning:
  cd ~/19.0/clio-tools
  python3 clio-uap/enrich_pursue_encounters.py --dry-run
  python3 clio-uap/enrich_pursue_encounters.py
  python3 clio-uap/enrich_pursue_encounters.py --max 20   # testa delmängd
"""
from __future__ import annotations

import argparse
import json
import os
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

URL  = os.getenv("VIGIL_ODOO_URL",      os.getenv("ODOO_URL",      "http://localhost:8069"))
DB   = os.getenv("VIGIL_ODOO_DB",       os.getenv("ODOO_DB",       "uap"))
USER = os.getenv("VIGIL_ODOO_USER",     os.getenv("ODOO_USER",     ""))
PWD  = os.getenv("VIGIL_ODOO_PASSWORD", os.getenv("ODOO_PASSWORD", ""))

OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = "qwen2.5:3b"

PURSUE_DB_ID  = 39   # uap_database.id för PURSUE
SOURCE_NAME   = "PURSUE — US Government UAP Initiative (war.gov)"

# ---------------------------------------------------------------------------
# Validering
# ---------------------------------------------------------------------------
VALID_CLASS = {"1", "2", "3", "4", "5"}
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
# Ollama-prompt (PURSUE-anpassad)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a UAP (Unidentified Aerial Phenomena) analyst working with declassified \
US government documents from the PURSUE initiative. All documents are in English \
and are officially released by the US government (discourse_level and official_response \
are already set — do NOT assess them).

Your task: given the document description, assess the ETH hypothesis and Pentagon \
Five Observables, and refine the encounter classification.

--- ENCOUNTER CLASSIFICATION ---
encounter_class:
  "1" = Sighting (visual observation only)
  "2" = Close Encounter (interaction / witness or vehicle reacts / FD-302 interview report)
  "3" = Physical Evidence (traces, photo, film, radar, measurements, physical analysis)
  "4" = Abduction / Contact (direct contact with non-human intelligence)
  "5" = Media / Cultural Reference (analysis memo, rendering, administrative, no new incident)

--- EXTRATERRESTRIAL HYPOTHESIS ---
eth_origin (how strongly does this document support extraterrestrial origin):
  "0" = Explained — conventional explanation confirmed or document is purely administrative
  "1" = Unexplained, but no ETH indicators
  "2" = Performance anomalies beyond known human technology
  "3" = Multi-sensor + officially investigated + conventional explanations ruled out
  "4" = Strong ETH indicators (anomalous materials, physics-defying, official acknowledgement)
  "5" = Confirmed non-human origin

intelligence_indicator (signs of intentional non-human intelligence or life):
  "0" = No indicators of intelligence
  "1" = Structured or controlled movement suggesting artificial origin
  "2" = Reactive behaviour — responds to observer, apparent purposeful intent
  "3" = Direct interaction, communication, or crew/occupants observed

--- PENTAGON FIVE OBSERVABLES (AARO) ---
Score each as true/false based on whether the document describes it:
  obs_antigravity     : Levitates or moves without apparent propulsion, wings or control surfaces
  obs_instant_accel   : Sudden acceleration or direction change impossible for known craft
  obs_hypersonic      : Extreme speed without sonic boom, heat signature or visible exhaust
  obs_low_observability: Appears/disappears, evades radar, or exhibits stealth characteristics
  obs_transmedium     : Moves between air, water and/or space without transition effects

Respond ONLY with valid JSON. No explanation, no markdown, no preamble.
"""

USER_TEMPLATE = """\
Source: {source}
Title: {title}

Document description (English):
{description}

Return JSON:
{{
  "description_sv": "Swedish summary of this document (2-3 sentences)",
  "encounter_class": "1"|"2"|"3"|"4"|"5",
  "eth_origin": "0"|"1"|"2"|"3"|"4"|"5",
  "intelligence_indicator": "0"|"1"|"2"|"3",
  "obs_antigravity": true|false,
  "obs_instant_accel": true|false,
  "obs_hypersonic": true|false,
  "obs_low_observability": true|false,
  "obs_transmedium": true|false
}}
"""

# ---------------------------------------------------------------------------
# Ollama-anrop
# ---------------------------------------------------------------------------

def ollama_enrich(title: str, description: str, model: str) -> dict | None:
    user_msg = USER_TEMPLATE.format(
        source=SOURCE_NAME,
        title=title or "(no title)",
        description=description[:3000],
    )

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                "options": {"temperature": 0.1, "num_predict": 400},
            },
            timeout=120,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"         Ollama-fel: {e}")
        return None

    raw = resp.json().get("message", {}).get("content", "")
    # Extrahera JSON-block
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start < 0 or end <= start:
        print(f"         Ingen JSON i svar: {raw[:100]}")
        return None

    try:
        data = json.loads(raw[start:end])
    except json.JSONDecodeError as e:
        print(f"         JSON-parse-fel: {e} | rådata: {raw[:150]}")
        return None

    # Validera och sanera
    result = {
        "description_sv":       str(data.get("description_sv") or ""),
        "encounter_class":      str(data.get("encounter_class") or ""),
        "eth_origin":           str(data.get("eth_origin") or ""),
        "intelligence_indicator": str(data.get("intelligence_indicator") or ""),
        "obs_antigravity":      bool(data.get("obs_antigravity")),
        "obs_instant_accel":    bool(data.get("obs_instant_accel")),
        "obs_hypersonic":       bool(data.get("obs_hypersonic")),
        "obs_low_observability":bool(data.get("obs_low_observability")),
        "obs_transmedium":      bool(data.get("obs_transmedium")),
    }

    if result["encounter_class"] not in VALID_CLASS:
        result["encounter_class"] = ""
    if result["eth_origin"] not in VALID_ETH:
        result["eth_origin"] = ""
    if result["intelligence_indicator"] not in VALID_INT:
        result["intelligence_indicator"] = ""

    return result

# ---------------------------------------------------------------------------
# Hämta kandidater
# ---------------------------------------------------------------------------

def get_candidates(max_items: int) -> list[dict]:
    """Hämta PURSUE-encounters som saknar ETH-berikelse (eth_origin='0' eller null)."""
    domain = [
        ["database_id", "=", PURSUE_DB_ID],
        "|",
        ["eth_origin", "in", [False, "", "0"]],
        ["intelligence_indicator", "in", [False, "", "0"]],
    ]
    fields = ["id", "encounter_id", "title_en", "description_en",
              "encounter_class", "eth_origin"]
    recs = kw("uap.encounter", "search_read", [domain],
              {"fields": fields, "limit": max_items or 500, "order": "id asc"})
    print(f"  Hittade {len(recs)} encounters att berika", flush=True)
    return recs

# ---------------------------------------------------------------------------
# Huvudlogik
# ---------------------------------------------------------------------------

def run(dry_run: bool, max_items: int, model: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  PURSUE Enrichment — ETH + Observables + SV-sammanfattning")
    print(f"{'─'*60}")
    print(f"  Modell      : {model}")
    print(f"  Max         : {max_items or 'alla'}")
    print(f"  Databas-id  : {PURSUE_DB_ID}")
    print(f"  Odoo URL    : {URL}")
    print(f"  Odoo DB     : {DB}")
    if dry_run:
        print("  *** DRY RUN ***")

    # Kontrollera Ollama
    try:
        pong = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        available = [m["name"] for m in pong.json().get("models", [])]
        if model not in available:
            print(f"\n  VARNING: modell '{model}' saknas. Tillgängliga: {available}")
            if not dry_run:
                sys.exit(1)
        else:
            print(f"  Ollama OK — modell '{model}' tillgänglig")
    except Exception as e:
        print(f"\n  VARNING: Kan inte nå Ollama ({e})")
        if not dry_run:
            sys.exit(1)

    candidates = get_candidates(max_items)
    if not candidates:
        print("  Inga encounters att berika — alla klara!")
        return

    print(f"  Bearbetar {len(candidates)} encounters...\n")

    done = errors = skipped = 0
    eth_dist: dict[str, int] = {}
    obs_counts = [0] * 5
    t0 = time.time()

    for i, enc in enumerate(candidates, 1):
        enc_id  = enc["id"]
        enc_ref = enc.get("encounter_id", "?")
        title   = enc.get("title_en") or ""
        desc    = enc.get("description_en") or ""

        print(f"  [{i:3d}/{len(candidates)}] {enc_ref} | {title[:55]}")

        if not desc or len(desc.strip()) < 30:
            print(f"           [HOPPAR — för kort/ingen description_en]")
            skipped += 1
            continue

        if dry_run:
            print(f"           Beskr: {desc[:80]}…")
            done += 1
            continue

        result = ollama_enrich(title, desc, model)
        if result is None:
            errors += 1
            continue

        # Bygg skrivvals — BEVARA discourse_level=5 och official_response=E
        vals: dict = {
            "obs_antigravity":        result["obs_antigravity"],
            "obs_instant_accel":      result["obs_instant_accel"],
            "obs_hypersonic":         result["obs_hypersonic"],
            "obs_low_observability":  result["obs_low_observability"],
            "obs_transmedium":        result["obs_transmedium"],
            "observables_count":      sum([
                result["obs_antigravity"],
                result["obs_instant_accel"],
                result["obs_hypersonic"],
                result["obs_low_observability"],
                result["obs_transmedium"],
            ]),
        }
        if result["eth_origin"]:
            vals["eth_origin"] = result["eth_origin"]
        if result["intelligence_indicator"]:
            vals["intelligence_indicator"] = result["intelligence_indicator"]
        if result["encounter_class"]:
            vals["encounter_class"] = result["encounter_class"]
        if result["description_sv"]:
            vals["description_sv"] = result["description_sv"]

        try:
            kw("uap.encounter", "write", [[enc_id], vals])
            eth = result.get("eth_origin", "?")
            obs = vals["observables_count"]
            eth_dist[eth] = eth_dist.get(eth, 0) + 1
            if result["obs_antigravity"]:    obs_counts[0] += 1
            if result["obs_instant_accel"]:  obs_counts[1] += 1
            if result["obs_hypersonic"]:     obs_counts[2] += 1
            if result["obs_low_observability"]: obs_counts[3] += 1
            if result["obs_transmedium"]:    obs_counts[4] += 1
            print(f"           eth={eth} | ii={result.get('intelligence_indicator','?')} | obs={obs} | class={result.get('encounter_class','?')}")
            done += 1
        except Exception as e:
            print(f"           Odoo-skrivfel: {e}")
            errors += 1

        # Progress var 50:e
        if i % 50 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (len(candidates) - i) / rate if rate > 0 else 0
            print(f"\n  --- [{i}/{len(candidates)}] {elapsed:.0f}s gångna | {rate:.1f}/s | ~{remaining:.0f}s kvar ---\n")

    # Sammanfattning
    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"PURSUE enrichment klar  [{elapsed:.0f}s]")
    print(f"{'='*60}")
    print(f"  Bearbetade:  {done}")
    print(f"  Hoppade:     {skipped}")
    print(f"  Fel:         {errors}")
    if eth_dist:
        print(f"\n  ETH-fördelning: {dict(sorted(eth_dist.items()))}")
        print(f"  Observables: AG={obs_counts[0]} IA={obs_counts[1]} "
              f"HS={obs_counts[2]} LO={obs_counts[3]} TM={obs_counts[4]}")
    if dry_run:
        print("\n  ** DRY RUN — inget skrevs till Odoo **")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Berika PURSUE uap.encounter med ETH + observables via Ollama."
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=0,
                    help="Max antal encounters (0=alla)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Ollama-modell (default: {DEFAULT_MODEL})")
    args = ap.parse_args()
    run(args.dry_run, args.max, args.model)


if __name__ == "__main__":
    main()
