"""
rotate_passwords.py
Roterar Odoo-lösenord via ORM-kanal (docker exec odoo shell).
Körs på servern, läser hemligheter från clio-tools/.env.
Skriver aldrig lösenord till disk, processlistor eller terminal.

Usage:
    python3 rotate_passwords.py [--run] [--instance odoo19|odoo18] [--db DB] [--login LOGIN]

Default: torrkörning. Lägg till --run för skarpt läge.

Environment (i clio-tools/.env):
    ROTATE_<LABEL>_LOGIN     – login för konto att rotera
    ROTATE_<LABEL>_PASSWORD  – nytt lösenord för kontot
    ROTATE_DATABASES_19      – kommaseparerade Odoo 19-databaser
    ROTATE_DATABASES_18      – kommaseparerade Odoo 18-databaser
"""

import argparse
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ODOO19_CONTAINER = "odoo19-odoo-1"
ODOO18_CONTAINER = "odoo-odoo-1"
ODOO_CONFIG = "/etc/odoo/odoo.conf"
ODOO_BIN = "odoo"
SHELL_TIMEOUT = 90

INSTANCE_CONTAINERS = {
    "odoo19": ODOO19_CONTAINER,
    "odoo18": ODOO18_CONTAINER,
}

INSTANCE_DB_KEYS = {
    "odoo19": "ROTATE_DATABASES_19",
    "odoo18": "ROTATE_DATABASES_18",
}

ENV_FILE = Path(__file__).parent.parent / ".env"
RESULT_PREFIX = "##CLIO##"


def load_env(path: Path) -> dict:
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def parse_accounts(env: dict) -> list:
    labels = set()
    for key in env:
        if key.startswith("ROTATE_") and key.endswith("_LOGIN"):
            labels.add(key[7:-6])

    accounts = []
    for label in sorted(labels):
        pw_key = f"ROTATE_{label}_PASSWORD"
        if pw_key not in env:
            raise ValueError(f"Saknar {pw_key} i .env för label {label!r}")
        accounts.append({
            "label": label,
            "login": env[f"ROTATE_{label}_LOGIN"],
            "password": env[pw_key],
        })
    return accounts


def parse_databases(env: dict, instance: str) -> list:
    key = INSTANCE_DB_KEYS.get(instance, f"ROTATE_DATABASES_{instance.upper()}")
    raw = env.get(key, "")
    return [db.strip() for db in raw.split(",") if db.strip()]


def _run_shell(container: str, db: str, python_code: str) -> tuple:
    cmd = [
        "docker", "exec", "-i", container,
        ODOO_BIN, "--config", ODOO_CONFIG, "shell", "-d", db,
    ]
    result = subprocess.run(
        cmd,
        input=python_code,
        capture_output=True,
        text=True,
        timeout=SHELL_TIMEOUT,
    )
    return result.returncode, result.stdout, result.stderr


def _extract_result(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            return line[len(RESULT_PREFIX):].strip()
    return ""


def _set_password_script(login: str, password: str) -> str:
    return f"""
user = env['res.users'].sudo().search([('login', '=', {login!r})], limit=1)
if not user:
    print({RESULT_PREFIX!r} + ' SKIP: login not found')
else:
    user._set_password({password!r})
    env.cr.commit()
    print({RESULT_PREFIX!r} + ' OK')
"""


def _verify_script(login: str, password: str) -> str:
    return f"""
user = env['res.users'].sudo().search([('login', '=', {login!r})], limit=1)
if not user:
    print({RESULT_PREFIX!r} + ' VERIFY_FAIL: user not found')
else:
    try:
        user._check_credentials({password!r}, {{'interactive': False}})
        print({RESULT_PREFIX!r} + ' VERIFY_OK')
    except Exception as e:
        print({RESULT_PREFIX!r} + f' VERIFY_FAIL: {{str(e)[:100]}}')
"""


def process_one(container: str, instance: str, db: str, account: dict, dry_run: bool) -> dict:
    row = {
        "instance": instance,
        "db": db,
        "login": account["login"],
        "status": "",
        "detail": "",
    }

    if dry_run:
        row["status"] = "DRY_RUN"
        return row

    try:
        rc, stdout, stderr = _run_shell(
            container, db, _set_password_script(account["login"], account["password"])
        )
    except subprocess.TimeoutExpired:
        row["status"] = "FAIL"
        row["detail"] = f"Timeout efter {SHELL_TIMEOUT}s"
        return row
    except Exception as e:
        row["status"] = "FAIL"
        row["detail"] = str(e)[:200]
        return row

    result = _extract_result(stdout)

    if rc != 0 and not result:
        row["status"] = "FAIL"
        row["detail"] = stderr.strip()[:200] or f"rc={rc}"
        return row

    if result.startswith("SKIP:"):
        row["status"] = "SKIPPED"
        row["detail"] = result
        return row

    if result != "OK":
        row["status"] = "FAIL"
        row["detail"] = result or stderr.strip()[:200]
        return row

    # Verifiera
    try:
        _, vstdout, _ = _run_shell(
            container, db, _verify_script(account["login"], account["password"])
        )
    except Exception as e:
        row["status"] = "OK_UNVERIFIED"
        row["detail"] = f"Verifiering misslyckades: {e}"
        return row

    vresult = _extract_result(vstdout)
    if vresult == "VERIFY_OK":
        row["status"] = "OK"
    else:
        row["status"] = "OK_UNVERIFIED"
        row["detail"] = vresult

    return row


def print_row(row: dict) -> None:
    detail = f" — {row['detail']}" if row['detail'] else ""
    print(f"[{row['instance']}] {row['db']} / {row['login']}: {row['status']}{detail}")


def write_status_file(rows: list) -> str:
    path = f"/tmp/pw_rotation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Odoo lösenordsrotation {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n")
        for row in rows:
            detail = f" — {row['detail']}" if row['detail'] else ""
            f.write(f"[{row['instance']}] {row['db']} / {row['login']}: {row['status']}{detail}\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Odoo lösenordsrotation")
    parser.add_argument("--run", action="store_true", help="Kör skarpt (default: torrkörning)")
    parser.add_argument("--instance", choices=["odoo19", "odoo18"], help="Begränsa till instans")
    parser.add_argument("--db", help="Begränsa till en databas")
    parser.add_argument("--login", help="Begränsa till ett konto (login)")
    args = parser.parse_args()

    dry_run = not args.run

    if dry_run:
        print("TORRKÖRNING — inga lösenord ändras. Lägg till --run för skarpt läge.\n")

    if not ENV_FILE.exists():
        print(f"FEL: .env hittades inte: {ENV_FILE}", file=sys.stderr)
        sys.exit(1)

    env = load_env(ENV_FILE)
    accounts = parse_accounts(env)

    if not accounts:
        print("FEL: Inga ROTATE_*_LOGIN/PASSWORD-par hittades i .env", file=sys.stderr)
        sys.exit(1)

    if args.login:
        accounts = [a for a in accounts if a["login"] == args.login]
        if not accounts:
            print(f"FEL: Konto {args.login!r} finns inte i .env", file=sys.stderr)
            sys.exit(1)

    instances = [args.instance] if args.instance else ["odoo19", "odoo18"]

    rows = []
    for instance in instances:
        container = INSTANCE_CONTAINERS[instance]
        databases = parse_databases(env, instance)
        if args.db:
            databases = [db for db in databases if db == args.db]
        for db in databases:
            for account in accounts:
                row = process_one(container, instance, db, account, dry_run)
                rows.append(row)
                print_row(row)

    if not dry_run and rows:
        log_path = write_status_file(rows)
        print(f"\nStatusfil: {log_path}")

    counts = Counter(r["status"] for r in rows)
    print(f"\nSammanfattning: {dict(counts)}")

    if any(r["status"] == "FAIL" for r in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
