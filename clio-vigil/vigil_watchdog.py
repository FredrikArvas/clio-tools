#!/usr/bin/env python3
"""
Clio-Vigil watchdog — övervakar tjänster, startar om vid fel (max 3 ggr/dag), mailar larm.

Kör via systemd timer var 10:e minut.
State sparas i /home/clioadmin/logs/vigil_watchdog_state.json.
"""

import configparser
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path("/home/clioadmin/19.0/clio-tools/clio-agent-mail")
CLIO_TOOLS = Path("/home/clioadmin/19.0/clio-tools")
STATE_FILE = Path("/home/clioadmin/logs/vigil_watchdog_state.json")
LOG_FILE = Path("/home/clioadmin/logs/vigil_watchdog.log")
MAX_RESTARTS = 3
MAIL_ACCOUNT = "clio"
MAIL_TO = "fredrik@arvas.se"

SERVICES = [
    "clio-vigil.service",
    "clio-vigil-uap.service",
    "clio-vigil-download.service",
]


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def service_active_state(service: str) -> str:
    result = subprocess.run(
        ["systemctl", "show", service, "--property=ActiveState", "--value"],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def service_last_log(service: str, lines: int = 15) -> str:
    result = subprocess.run(
        ["journalctl", "-u", service, f"-n{lines}", "--no-pager", "--output=short"],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def send_email(subject: str, body: str):
    try:
        sys.path.insert(0, str(BASE_DIR))
        from dotenv import load_dotenv
        load_dotenv(CLIO_TOOLS / ".env")
        load_dotenv(BASE_DIR / ".env", override=True)

        from smtp_client import send_email as _send

        config = configparser.ConfigParser(interpolation=None)
        config.read(str(BASE_DIR / "clio.config"), encoding="utf-8")

        for key in config.get("mail", "accounts").split(","):
            key = key.strip()
            val = os.environ.get(f"IMAP_PASSWORD_{key.upper()}")
            if val:
                config.set("mail", f"imap_password_{key}", val)

        _send(
            config=config,
            from_account_key=MAIL_ACCOUNT,
            to_addr=MAIL_TO,
            subject=subject,
            body=body,
        )
        log(f"Mail skickat: {subject}")
    except Exception as e:
        log(f"MAIL-FEL: {e}")


def reset_failed(service: str):
    subprocess.run(["systemctl", "reset-failed", service], capture_output=True)


def start_service(service: str) -> bool:
    result = subprocess.run(["systemctl", "start", service], capture_output=True)
    return result.returncode == 0


def main():
    state = load_state()
    today = str(date.today())
    changed = False

    for service in SERVICES:
        svc = state.setdefault(service, {
            "count": 0,
            "daily_reset": today,
            "last_fail": None,
            "gave_up": False,
        })

        # Nollställ räknaren varje ny dag
        if svc.get("daily_reset") != today:
            svc["count"] = 0
            svc["daily_reset"] = today
            svc["gave_up"] = False
            changed = True

        active = service_active_state(service)

        if active != "failed":
            log(f"OK  {service} ({active})")
            continue

        # Tjänsten är i failed-state
        svc["last_fail"] = datetime.now().isoformat()
        count = svc["count"]

        if svc.get("gave_up"):
            log(f"SKIP {service} — redan gett upp idag ({count} omstarter)")
            continue

        if count < MAX_RESTARTS:
            svc["count"] += 1
            changed = True
            log(f"FAIL {service} — startar om ({svc['count']}/{MAX_RESTARTS})")

            reset_failed(service)
            ok = start_service(service)
            new_state = service_active_state(service)
            recent_log = service_last_log(service)

            send_email(
                f"[Vigil-watchdog] {service} failade — omstart {svc['count']}/{MAX_RESTARTS}",
                f"Tjänsten {service} var i 'failed' state.\n\n"
                f"Omstartsförsök {svc['count']}/{MAX_RESTARTS}: {'OK' if ok else 'MISSLYCKADES'}\n"
                f"Ny status: {new_state}\n\n"
                f"--- Senaste logg ---\n{recent_log}"
            )
        else:
            svc["gave_up"] = True
            changed = True
            log(f"GER UPP {service} — {MAX_RESTARTS} omstarter nådda, manuell åtgärd krävs")
            recent_log = service_last_log(service)
            send_email(
                f"[Vigil-watchdog] ⚠️ {service} — GER UPP efter {MAX_RESTARTS} omstarter",
                f"Tjänsten {service} har failat {MAX_RESTARTS} gånger idag.\n\n"
                f"Inga fler automatiska omstarter görs idag.\n"
                f"Manuell inspektion krävs!\n\n"
                f"Kör: systemctl status {service}\n"
                f"      journalctl -u {service} -n 50\n\n"
                f"--- Senaste logg ---\n{recent_log}"
            )

    if changed:
        save_state(state)


if __name__ == "__main__":
    main()
