"""
rotate_passwords.py
Roterar Odoo-lösenord via ORM-kanal (docker exec odoo shell). Byggd för Odoo 19
(fungerar även mot Odoo 18, samma API för write/password och _check_credentials).
Körs på servern, läser hemligheter från clio-tools/.env.
Skriver aldrig lösenord till disk, processlistor eller terminal — skriptkoden
med lösenordet skickas till odoo shell via stdin.

Usage:
    python3 rotate_passwords.py [--run] [--instance odoo19|odoo18] [--db DB] [--login LOGIN]

Default: torrkörning. Torrkörningen slår upp (läsande) om varje konto finns i
varje databas och rapporterar WOULD_CHANGE eller SKIPPED. Lägg till --run för
skarpt läge.

Environment (i clio-tools/.env):
    ROTATE_<LABEL>_LOGIN     – login för konto att rotera
    ROTATE_<LABEL>_PASSWORD  – nytt lösenord för kontot
    ROTATE_DATABASES_19      – kommaseparerade Odoo 19-databaser
    ROTATE_DATABASES_18      – kommaseparerade Odoo 18-databaser

Status per rad:
    OK             – bytt och verifierat
    OK_UNVERIFIED  – bytt, men verifieringen misslyckades (se detalj)
    SKIPPED        – kontot finns inte i databasen (inget ändrat)
    WOULD_CHANGE   – torrkörning: kontot finns och skulle bytas
    FAIL           – fel (databas saknas, container nere, ORM-fel …)
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

# Fraser i Odoos stderr som betyder att databasen inte finns.
DB_MISSING_MARKERS = ("does not exist", "database not found")


# ── Configuration ──────────────────────────────────────────────────────────────

def load_env(path: Path) -> dict:
    env = {}
    with open(path, encoding="utf-8-sig") as f:
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
        if not env[f"ROTATE_{label}_LOGIN"]:
            raise ValueError(f"ROTATE_{label}_LOGIN är tom i .env")
        if not env[pw_key]:
            raise ValueError(f"{pw_key} är tom i .env")
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


# ── Odoo shell ─────────────────────────────────────────────────────────────────

def _run_shell(container: str, db: str, python_code: str) -> tuple:
    # Odoo 19: underkommandot ska stå först (odoo shell --config ...).
    cmd = [
        "docker", "exec", "-i", container,
        ODOO_BIN, "shell", "--config", ODOO_CONFIG, "-d", db, "--no-http",
    ]
    result = subprocess.run(
        cmd,
        input=python_code,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=SHELL_TIMEOUT,
    )
    return result.returncode, result.stdout, result.stderr


def _extract_result(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            return line[len(RESULT_PREFIX):].strip()
    return ""


def _summarize_stderr(stderr: str) -> str:
    """Plocka den informativa raden ur Odoos stderr i stället för startbruset."""
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    if not lines:
        return ""
    for ln in reversed(lines):
        if any(tok in ln for tok in ("Error", "error:", "Exception", "does not exist")):
            return ln[:200]
    return lines[-1][:200]


def _is_db_missing(stderr: str) -> bool:
    low = stderr.lower()
    return any(m in low for m in DB_MISSING_MARKERS)


# Gemensam uppslagning. active_test=False så att arkiverade konton hittas
# (ett arkiverat konto med läckt lösenord kan återaktiveras — det ska roteras).
_LOOKUP = """
Users = env['res.users'].sudo().with_context(active_test=False)
user = Users.search([('login', '=', {login!r})], limit=1)
"""


def _lookup_script(login: str) -> str:
    """Läsande uppslagning för torrkörning. Innehåller inget lösenord."""
    return f"""
try:
{_indent(_LOOKUP.format(login=login))}
    if not user:
        print({RESULT_PREFIX!r} + ' SKIP: kontot finns inte')
    else:
        note = '' if user.active else ' (arkiverat)'
        print({RESULT_PREFIX!r} + ' FOUND id=' + str(user.id) + note)
except Exception as e:
    print({RESULT_PREFIX!r} + ' FAIL: ' + type(e).__name__ + ': ' + str(e)[:200])
"""


def _set_password_script(login: str, password: str) -> str:
    # Odoo 19: _set_password() tar inga argument — skriv via fältet 'password'
    # så att ORM:en hashar (pbkdf2) korrekt.
    return f"""
try:
{_indent(_LOOKUP.format(login=login))}
    if not user:
        print({RESULT_PREFIX!r} + ' SKIP: kontot finns inte')
    else:
        user.write({{'password': {password!r}}})
        env.cr.commit()
        note = '' if user.active else ' (arkiverat)'
        print({RESULT_PREFIX!r} + ' OK' + note)
except Exception as e:
    env.cr.rollback()
    print({RESULT_PREFIX!r} + ' FAIL: ' + type(e).__name__ + ': ' + str(e)[:200])
"""


def _verify_script(login: str, password: str) -> str:
    # Odoo 18+/19: _check_credentials(credential: dict, env: dict) och den
    # kontrollerar self.env.user — därför with_user(user), inte sudo().
    return f"""
try:
{_indent(_LOOKUP.format(login=login))}
    if not user:
        print({RESULT_PREFIX!r} + ' VERIFY_FAIL: kontot finns inte')
    else:
        credential = {{'login': {login!r}, 'password': {password!r}, 'type': 'password'}}
        user.with_user(user)._check_credentials(credential, {{'interactive': False}})
        print({RESULT_PREFIX!r} + ' VERIFY_OK')
except Exception as e:
    print({RESULT_PREFIX!r} + ' VERIFY_FAIL: ' + type(e).__name__ + ': ' + str(e)[:100])
"""


def _indent(code: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + ln if ln.strip() else ln for ln in code.strip("\n").splitlines())


# ── Processing ─────────────────────────────────────────────────────────────────

def _shell_call(row: dict, container: str, db: str, code: str):
    """Kör odoo shell. Returnerar resultatsträngen, eller None om row satts till FAIL."""
    try:
        rc, stdout, stderr = _run_shell(container, db, code)
    except subprocess.TimeoutExpired:
        row["status"] = "FAIL"
        row["detail"] = f"Timeout efter {SHELL_TIMEOUT}s"
        return None
    except Exception as e:
        row["status"] = "FAIL"
        row["detail"] = f"{type(e).__name__}: {str(e)[:200]}"
        return None

    result = _extract_result(stdout)
    if result:
        return result

    row["status"] = "FAIL"
    if _is_db_missing(stderr):
        row["detail"] = f"databasen {db!r} finns inte"
    else:
        row["detail"] = _summarize_stderr(stderr) or f"inget resultat från odoo shell (rc={rc})"
    return None


def process_one(container: str, instance: str, db: str, account: dict, dry_run: bool) -> dict:
    row = {
        "instance": instance,
        "db": db,
        "login": account["login"],
        "status": "",
        "detail": "",
    }

    if dry_run:
        result = _shell_call(row, container, db, _lookup_script(account["login"]))
        if result is None:
            return row
        if result.startswith("SKIP:"):
            row["status"] = "SKIPPED"
            row["detail"] = result[5:].strip()
        elif result.startswith("FOUND"):
            row["status"] = "WOULD_CHANGE"
            row["detail"] = result[5:].strip()
        else:
            row["status"] = "FAIL"
            row["detail"] = result
        return row

    result = _shell_call(row, container, db, _set_password_script(account["login"], account["password"]))
    if result is None:
        return row

    if result.startswith("SKIP:"):
        row["status"] = "SKIPPED"
        row["detail"] = result[5:].strip()
        return row

    if not result.startswith("OK"):
        row["status"] = "FAIL"
        row["detail"] = result
        return row

    note = result[2:].strip()

    # Verifiera
    vrow = dict(row)
    vresult = _shell_call(vrow, container, db, _verify_script(account["login"], account["password"]))
    if vresult == "VERIFY_OK":
        row["status"] = "OK"
        row["detail"] = note
    else:
        row["status"] = "OK_UNVERIFIED"
        row["detail"] = vresult if vresult is not None else f"verifiering: {vrow['detail']}"

    return row


# ── Output ─────────────────────────────────────────────────────────────────────

def format_row(row: dict) -> str:
    detail = f" — {row['detail']}" if row['detail'] else ""
    return f"[{row['instance']}] {row['db']} / {row['login']}: {row['status']}{detail}"


def write_status_file(rows: list) -> str:
    path = f"/tmp/pw_rotation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Odoo lösenordsrotation {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n")
        for row in rows:
            f.write(format_row(row) + "\n")
    return path


def warn_missing_logins(rows: list) -> list:
    """Konton som inte hittades i NÅGON av de körda databaserna (troligen fel login i .env)."""
    by_login = {}
    for r in rows:
        by_login.setdefault(r["login"], []).append(r["status"])
    return [login for login, sts in by_login.items() if sts and all(s == "SKIPPED" for s in sts)]


# ── Main ───────────────────────────────────────────────────────────────────────

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
    try:
        accounts = parse_accounts(env)
    except ValueError as e:
        print(f"FEL: {e}", file=sys.stderr)
        sys.exit(1)

    if not accounts:
        print("FEL: Inga ROTATE_*_LOGIN/PASSWORD-par hittades i .env", file=sys.stderr)
        sys.exit(1)

    if args.login:
        accounts = [a for a in accounts if a["login"] == args.login]
        if not accounts:
            print(f"FEL: Konto {args.login!r} finns inte i .env", file=sys.stderr)
            sys.exit(1)

    instances = [args.instance] if args.instance else ["odoo19", "odoo18"]

    plan = []
    for instance in instances:
        databases = parse_databases(env, instance)
        if args.db:
            databases = [db for db in databases if db == args.db]
        plan.extend((instance, db) for db in databases)

    if not plan:
        where = f"databas {args.db!r}" if args.db else "några databaser"
        print(f"FEL: Hittade inte {where} i ROTATE_DATABASES_* för {', '.join(instances)}",
              file=sys.stderr)
        sys.exit(1)

    rows = []
    for instance, db in plan:
        container = INSTANCE_CONTAINERS[instance]
        for account in accounts:
            row = process_one(container, instance, db, account, dry_run)
            rows.append(row)
            print(format_row(row), flush=True)

    if not dry_run and rows:
        log_path = write_status_file(rows)
        print(f"\nStatusfil: {log_path}")

    missing = warn_missing_logins(rows)
    for login in missing:
        print(f"VARNING: {login!r} fanns inte i någon av databaserna — stämmer login i .env?")

    counts = Counter(r["status"] for r in rows)
    print(f"\nSammanfattning: {dict(counts)}")

    if any(r["status"] in ("FAIL", "OK_UNVERIFIED") for r in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
