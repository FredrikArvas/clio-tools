"""
uap_date_backfill.py — Backfill date_observed via lokal LLM (Qwen2.5:3b / Ollama)

Hittar encounters utan historiskt datum och ber Qwen2.5:3b extrahera
observationsåret ur title_en + research_notes.

Kör: python3 uap_date_backfill.py [--dry-run] [--max N] [--model qwen2.5:3b]
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, xmlrpc.client
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = "uapdb"
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

OLLAMA_URL = "http://localhost:11434"

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
UID    = common.authenticate(DB, USER, PWD, {})
if not UID:
    sys.exit("Odoo-autentisering misslyckades")
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, kwargs=None):
    return M.execute_kw(DB, UID, PWD, model, method, args, kwargs or {})


# ---------------------------------------------------------------------------
# Regex-försokning (billig, ingen LLM-kostnad)
# ---------------------------------------------------------------------------
_YEAR_RE = re.compile(r'\b(1[5-9]\d{2}|20[0-2]\d)\b')

def regex_year(text: str) -> int | None:
    for m in _YEAR_RE.finditer(text or ""):
        y = int(m.group(1))
        if y < 2025:
            return y
    return None


# ---------------------------------------------------------------------------
# Ollama-anrop
# ---------------------------------------------------------------------------
import urllib.request

SYSTEM_PROMPT = (
    "You are a precise date extractor. "
    "Given a UAP/UFO encounter title and research notes, extract the year the event occurred. "
    "Reply ONLY with valid JSON: {\"year\": <4-digit integer>} or {\"year\": null} if unknown. "
    "Do not guess. If the text mentions multiple years, pick the year the event happened."
)

def ollama_extract_year(title: str, notes: str, model: str) -> int | None:
    user_msg = f"Title: {title}\nNotes: {notes[:400]}"
    payload = json.dumps({
        "model":  model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        raw = body.get("message", {}).get("content", "{}")
        data = json.loads(raw)
        y = data.get("year")
        if isinstance(y, int) and 1500 < y < 2025:
            return y
    except Exception as e:
        print(f"    Ollama-fel: {e}")
    return None


def check_ollama(model: str) -> bool:
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/tags", method="GET"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        names = [m["name"] for m in data.get("models", [])]
        if any(model in n for n in names):
            return True
        print(f"Modell '{model}' saknas. Tillgängliga: {names}")
        return False
    except Exception as e:
        print(f"Ollama ej tillgänglig: {e}")
        return False


# ---------------------------------------------------------------------------
# Huvud-pipeline
# ---------------------------------------------------------------------------

def run(max_enc: int, model: str, dry_run: bool):
    # Hämta encounters utan historiskt datum
    all_enc = kw("uap.encounter", "search_read",
                 [[["title_en", "!=", False]]],
                 {"fields": ["id", "title_en", "research_notes", "date_observed"],
                  "limit": 2000})

    candidates = []
    for enc in all_enc:
        d = enc.get("date_observed")
        if d:
            try:
                if datetime.fromisoformat(str(d)).year < 2025:
                    continue
            except Exception:
                pass
        candidates.append(enc)

    print(f"Totalt: {len(candidates)} encounters utan historiskt datum")
    if max_enc:
        candidates = candidates[:max_enc]
        print(f"Begränsat till {max_enc} i detta körning")

    ollama_ok = check_ollama(model)
    if not ollama_ok:
        print("Kör enbart regex-pass (Ollama ej tillgänglig)")

    regex_hits = llm_hits = no_year = errors = 0
    t0 = time.time()

    for i, enc in enumerate(candidates, 1):
        title = enc.get("title_en") or ""
        notes = enc.get("research_notes") or ""

        # Steg 1: regex på titel + notes
        year = regex_year(title + " " + notes)
        method = "regex"

        # Steg 2: Ollama om regex misslyckades — men bara om det finns meningsfullt innehåll
        # (tom titel utan år + inga noter = LLM kan ändå inte hjälpa, skippa för prestanda)
        if year is None and ollama_ok and len(notes.strip()) > 20:
            year = ollama_extract_year(title, notes, model)
            method = "llm"

        if year is None:
            no_year += 1
            if i % 100 == 0:
                print(f"  [{i}/{len(candidates)}] {title[:50]!r} → inget år")
            continue

        date_str = f"{year}-01-01 00:00:00"
        if dry_run:
            print(f"  [DRY] {title[:55]!r} → {year} ({method})")
            if method == "regex":
                regex_hits += 1
            else:
                llm_hits += 1
        else:
            try:
                kw("uap.encounter", "write", [[enc["id"]], {"date_observed": date_str}])
                if method == "regex":
                    regex_hits += 1
                else:
                    llm_hits += 1
            except Exception as e:
                print(f"  FEL {enc['id']}: {e}")
                errors += 1

        if i % 50 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed
            eta = (len(candidates) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(candidates)}] regex={regex_hits} llm={llm_hits} "
                  f"ingen={no_year} | {rate:.1f} enc/s | ETA {eta/60:.1f} min")

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Regex-träffar : {regex_hits}")
    print(f"  LLM-träffar   : {llm_hits}")
    print(f"  Inget år      : {no_year}")
    print(f"  Fel           : {errors}")
    print(f"  Tid           : {elapsed:.1f}s")

    if not dry_run:
        dated = kw("uap.encounter", "search_count", [[["date_observed", "!=", False]]])
        total = kw("uap.encounter", "search_count", [[]])
        print(f"  Encounters med datum: {dated}/{total} ({dated*100//total}%)")
    print(f"{'='*60}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max",     type=int, default=0, help="Max encounters att bearbeta (0=alla)")
    ap.add_argument("--model",   default="qwen2.5:3b")
    args = ap.parse_args()

    if args.dry_run:
        print("*** DRY RUN ***")

    run(args.max, args.model, args.dry_run)
