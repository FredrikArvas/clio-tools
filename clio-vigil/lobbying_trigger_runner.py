"""
lobbying_trigger_runner.py — clio-vigil
=========================================
Körs av systemd clio-lobbying-trigger.service när Odoo skriver en lobbying trigger-fil.
Läser .lobbying_trigger, kör rätt pipeline-steg, skriver .lobbying_status.

Trigger-fil: clio-vigil/data/.lobbying_trigger  (JSON)
Status-fil:  clio-vigil/data/.lobbying_status   (JSON)

Payload-format:
  extract_journalists:
    {"action": "extract_journalists", "domain": "ufo", "triggered_by": "admin"}

  build_profiles:
    {"action": "build_profiles", "domain": "ufo", "triggered_by": "admin"}

  pitch:
    {"action": "pitch", "event_text": "...", "domain": "ufo",
     "event_odoo_id": 42, "triggered_by": "admin"}
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE         = Path(__file__).parent
TRIGGER_FILE  = _HERE / "data" / ".lobbying_trigger"
STATUS_FILE   = _HERE / "data" / ".lobbying_status"
MAIN_PY       = _HERE.parent / "clio-vigil" / "main.py"


def _write_status(payload: dict) -> None:
    try:
        STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        print(f"Kunde inte skriva status-fil: {exc}", file=sys.stderr)


def _run(args: list[str], triggered_by: str, event_odoo_id: int | None = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    _write_status({
        "status":        "running",
        "started_at":    now,
        "triggered_by":  triggered_by,
        "event_odoo_id": event_odoo_id,
    })

    cmd = ["/usr/bin/python3", str(MAIN_PY)] + args
    print(f"[lobbying_runner] {' '.join(cmd[:6])}…")
    result = subprocess.run(cmd, cwd=str(_HERE.parent))

    _write_status({
        "status":        "done" if result.returncode == 0 else "error",
        "returncode":    result.returncode,
        "completed_at":  datetime.now(timezone.utc).isoformat(),
        "triggered_by":  triggered_by,
        "event_odoo_id": event_odoo_id,
    })
    return result.returncode


def main() -> int:
    if not TRIGGER_FILE.exists():
        print("Ingen lobbying trigger-fil — inget att göra.")
        return 0

    try:
        data = json.loads(TRIGGER_FILE.read_text())
    except Exception as exc:
        print(f"Kunde inte läsa trigger-fil: {exc}", file=sys.stderr)
        TRIGGER_FILE.unlink(missing_ok=True)
        return 1

    TRIGGER_FILE.unlink(missing_ok=True)

    action         = data.get("action", "")
    domain         = data.get("domain", "")
    triggered_by   = data.get("triggered_by", "?")
    event_odoo_id  = data.get("event_odoo_id")
    event_text     = data.get("event_text", "")

    domain_args = ["--domain", domain] if domain else []

    if action == "extract_journalists":
        return _run(["--extract-journalists"] + domain_args, triggered_by)

    elif action == "build_profiles":
        return _run(["--build-profiles"] + domain_args, triggered_by)

    elif action == "pitch":
        if not event_text:
            print("Saknar event_text i trigger-fil.", file=sys.stderr)
            return 1
        args = ["--pitch", event_text] + domain_args
        if event_odoo_id:
            args += ["--event-id", str(event_odoo_id)]
        return _run(args, triggered_by, event_odoo_id)

    else:
        print(f"Okänd action: {action}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
