"""
trigger_runner.py — clio-vigil
===============================
Körs av systemd clio-vigil-trigger.service när Odoo skriver en trigger-fil.
Läser .vigil_trigger, kör rätt pipeline-steg, skriver .vigil_status.

Trigger-fil: clio-vigil/data/.vigil_trigger  (JSON)
Status-fil:  clio-vigil/data/.vigil_status   (JSON, skrivs av denna fil)
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE        = Path(__file__).parent
TRIGGER_FILE = _HERE / "data" / ".vigil_trigger"
STATUS_FILE  = _HERE / "data" / ".vigil_status"

STEP_ARGS = {
    "run":        ["--run", "--all-domains"],
    "transcribe": ["--transcribe"],
    "summarize":  ["--summarize"],
    "index":      ["--index"],
    "digest":     ["--digest"],
    "full":       ["--full", "--all-domains"],
    "seed":       ["--seed-sources"],
    "recompute":  ["--recompute-priorities"],
}


def _write_status(payload: dict) -> None:
    try:
        STATUS_FILE.write_text(json.dumps(payload))
    except Exception as exc:
        print(f"Kunde inte skriva status-fil: {exc}", file=sys.stderr)


def main() -> int:
    if not TRIGGER_FILE.exists():
        print("Ingen trigger-fil — inget att göra.")
        return 0

    try:
        data = json.loads(TRIGGER_FILE.read_text())
    except Exception as exc:
        print(f"Kunde inte läsa trigger-fil: {exc}", file=sys.stderr)
        TRIGGER_FILE.unlink(missing_ok=True)
        return 1

    step = data.get("step", "full")
    args = STEP_ARGS.get(step)
    if args is None:
        print(f"Okänt steg: {step}", file=sys.stderr)
        TRIGGER_FILE.unlink(missing_ok=True)
        return 1

    # Radera trigger-filen innan körning (hindrar loop om service startas om)
    TRIGGER_FILE.unlink(missing_ok=True)

    triggered_by = data.get("triggered_by", "?")
    now = datetime.now(timezone.utc).isoformat()

    _write_status({
        "step":         step,
        "status":       "running",
        "started_at":   now,
        "triggered_by": triggered_by,
    })

    workdir = str(_HERE.parent)
    cmd = ["/usr/bin/python3", "clio-vigil/main.py"] + args
    print(f"[trigger_runner] {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=workdir)

    _write_status({
        "step":          step,
        "status":        "done" if result.returncode == 0 else "error",
        "returncode":    result.returncode,
        "completed_at":  datetime.now(timezone.utc).isoformat(),
        "triggered_by":  triggered_by,
    })

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
