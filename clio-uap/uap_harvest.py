"""
uap_harvest.py — Orchestrator for UAP-incidentinsamling

Kalla:
  python3 uap_harvest.py [--sources geipan nuforc wiki] [--dry-run] [--limit N]

Sources:
  geipan  — GEIPAN (Frankrike, officiell, ~3 368 fall, Excel-export)
  nuforc  — NUFORC (global, ~80k fall, GitHub CSV)
  wiki    — Wikipedia (36+ sprak, via uap_import_wiki_global.py)

State:
  uap_harvest_state.json (senaste korning, antal skapade, eventuella fel per kalla)

Kors som systemd timer, t.ex. sondagsnatt 03:00.
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "uap_harvest_state.json"
LOG_DIR    = Path(__file__).parent / "logs"
LOG_FILE   = LOG_DIR / "harvest.log"

ALL_SOURCES = ["geipan", "nuforc", "wiki", "eufo", "cobeps"]

SCRIPTS = {
    "geipan": Path(__file__).parent / "uap_import_geipan.py",
    "nuforc": Path(__file__).parent / "uap_import_nuforc.py",
    "wiki":   Path(__file__).parent / "uap_import_wiki_global.py",
    "eufo":  Path(__file__).parent / "uap_import_eufo.py",
    "cobeps": Path(__file__).parent / "uap_import_cobeps.py",
    "sefaa":  Path(__file__).parent / "uap_import_sefaa.py",
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ---------------------------------------------------------------------------
# Korkalla
# ---------------------------------------------------------------------------

def run_source(name: str, dry_run: bool, limit: int | None, extra_args: list[str]) -> dict:
    script = SCRIPTS.get(name)
    if not script or not script.exists():
        return {"status": "error", "msg": f"Skript saknas: {script}"}

    cmd = [sys.executable, str(script)]
    if dry_run:
        cmd.append("--dry-run")
    if limit:
        cmd += ["--limit", str(limit)]

    # Wiki global: korra alla faser
    if name == "wiki":
        cmd += ["--phase", "all"]

    cmd += extra_args

    log(f"START {name}: {' '.join(cmd)}")
    t0 = time.time()

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(script.parent),
    )
    elapsed = time.time() - t0

    if result.returncode == 0:
        log(f"OK    {name} ({elapsed:.0f}s)")
        # Extrahera "Skapade : N" ur stdout
        import re
        m = re.search(r"Skapade\s*:\s*(\d+)", result.stdout)
        created = int(m.group(1)) if m else None
        return {"status": "ok", "elapsed_s": int(elapsed), "created": created}
    else:
        log(f"FEL   {name}: {result.stderr[-500:]}")
        return {"status": "error", "elapsed_s": int(elapsed),
                "msg": result.stderr[-500:]}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="UAP harvest orchestrator")
    ap.add_argument("--sources", nargs="+", default=ALL_SOURCES,
                    choices=ALL_SOURCES,
                    help="Vilka kallor att korra (default: alla)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit",   type=int, default=None,
                    help="Max poster per kalla")
    ap.add_argument("--status",  action="store_true",
                    help="Visa senaste harvest-status")
    args = ap.parse_args()

    state = load_state()

    if args.status:
        if not state:
            print("Ingen harvest-historik hittad.")
        else:
            print(json.dumps(state, indent=2, ensure_ascii=False))
        return

    run_ts = datetime.now().isoformat(timespec="seconds")
    log(f"=== UAP Harvest korjar {'(DRY RUN) ' if args.dry_run else ''}{run_ts} ===")
    log(f"    Kallor: {', '.join(args.sources)}")

    results = {}
    for src in args.sources:
        results[src] = run_source(src, args.dry_run, args.limit, [])
        time.sleep(2)  # Kort paus mellan kallor

    # Uppdatera state
    state["last_run"] = run_ts
    state["last_results"] = results
    state.setdefault("history", []).append({
        "ts": run_ts, "sources": args.sources, "results": results
    })
    state["history"] = state["history"][-10:]  # Behall senaste 10
    save_state(state)

    log("=== Harvest klar ===")
    for src, res in results.items():
        status = res.get("status", "?")
        created = res.get("created")
        elapsed = res.get("elapsed_s", 0)
        log(f"  {src:8s}: {status} | skapade={created} | {elapsed}s")

    # Felkod så att systemd markerar körningen som misslyckad
    failed = [src for src, res in results.items() if res.get("status") != "ok"]
    if failed:
        log(f"  Misslyckade kallor: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
