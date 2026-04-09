"""
check_deps.py — Verifiera beroenden för clio-agent-obit

Körning:
    python check_deps.py

Integreras i clio-tools environment-check via:
    python run.py --last-run
"""

from __future__ import annotations

import importlib
import os
import sys

# Säkerställ att UTF-8 fungerar på Windows cp1252-konsoler.
# Om reconfigure inte är tillgänglig faller vi tillbaka på ASCII-ikoner.
_UTF8_OK = True
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, Exception):
    _UTF8_OK = False

CHECKS = []
if _UTF8_OK:
    PASS, FAIL, WARN = "✅", "❌", "⚠️"
else:
    PASS, FAIL, WARN = "OK ", "ERR", "...."


def check(label: str):
    def decorator(fn):
        CHECKS.append((label, fn))
        return fn
    return decorator


@check("Python >= 3.8")
def _python_version():
    ok = sys.version_info >= (3, 8)
    return ok, f"Python {sys.version.split()[0]}"


@check("feedparser (valfri, för deprecated RSS-adapter)")
def _feedparser():
    try:
        import feedparser
        return None, f"version {feedparser.__version__}"
    except ImportError:
        return None, "pip install feedparser  (behövs bara om du återaktiverar RSS-källan)"


@check("pyyaml")
def _pyyaml():
    try:
        import yaml
        return True, f"version {yaml.__version__}"
    except ImportError:
        return False, "pip install pyyaml"


@check("requests")
def _requests():
    try:
        import requests
        return True, f"version {requests.__version__}"
    except ImportError:
        return False, "pip install requests"


@check("beautifulsoup4")
def _bs4():
    try:
        import bs4
        return True, f"version {bs4.__version__}"
    except ImportError:
        return False, "pip install beautifulsoup4"


@check("sources.yaml")
def _sources_yaml():
    path = os.path.join(os.path.dirname(__file__), "sources.yaml")
    if not os.path.exists(path):
        return False, "sources.yaml saknas i clio-agent-obit-roten"
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        return False, f"kunde inte parsa: {e}"
    entries = data.get("sources", []) or []
    enabled = [e for e in entries if e.get("enabled", True)]
    if not enabled:
        return False, f"{len(entries)} entries men inga enabled"
    return True, f"{len(enabled)} aktiva av {len(entries)} källor"


@check("python-dotenv")
def _dotenv():
    try:
        import dotenv
        return True, "installerad"
    except ImportError:
        return False, "pip install python-dotenv"


@check("python-gedcom")
def _gedcom():
    try:
        import gedcom
        return True, "installerad"
    except ImportError:
        return False, "pip install python-gedcom"


@check("Levenshtein (valfri, förbättrar namnmatchning)")
def _levenshtein():
    try:
        import Levenshtein
        return True, "installerad"
    except ImportError:
        return None, "pip install python-Levenshtein  (faller tillbaka på difflib)"


@check(".env-fil")
def _env_file():
    path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(path):
        return True, path
    return False, ".env saknas — kopiera .env.example och fyll i"


@check("watchlists/ (en CSV per bevakare)")
def _watchlist():
    import glob as _glob
    watchlists_dir = os.path.join(os.path.dirname(__file__), "watchlists")
    files = sorted(_glob.glob(os.path.join(watchlists_dir, "*.csv")))
    if not files:
        return False, "Inga filer i watchlists/ — lägg till t.ex. watchlists/fredrik@arvas.se.csv"
    summary_parts = []
    for f in files:
        owner = os.path.splitext(os.path.basename(f))[0]
        with open(f, encoding="utf-8") as fh:
            rows = sum(1 for line in fh if line.strip()) - 1
        summary_parts.append(f"{owner} ({rows} poster)")
    return True, "  |  ".join(summary_parts)


@check("state.db (skapas automatiskt)")
def _state_db():
    path = os.path.join(os.path.dirname(__file__), "state.db")
    if os.path.exists(path):
        return True, f"finns ({os.path.getsize(path)} bytes)"
    return None, "Saknas — skapas automatiskt vid första körning av run.py"


@check("config.yaml (SMTP + notify)")
def _config_yaml():
    path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(path):
        return False, "config.yaml saknas — kopiera från .env.example-kommentaren"
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        return False, f"kunde inte parsa: {e}"
    smtp = cfg.get("smtp", {})
    notify = cfg.get("notify", {})
    missing = [k for k in ("host", "user") if not smtp.get(k)]
    if not notify.get("to"):
        missing.append("notify.to")
    if missing:
        return False, f"Saknas i config.yaml: {', '.join(missing)}"
    return True, f"host={smtp['host']}  user={smtp['user']}"


@check("SMTP-lösenord i .env")
def _smtp_password():
    import yaml
    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    pw_var = "SMTP_PASSWORD"
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            pw_var = cfg.get("smtp", {}).get("password_env", pw_var)
        except Exception:
            pass
    password = os.getenv(pw_var, "").strip()
    if password:
        return True, f"{pw_var} satt ({len(password)} tecken)"
    return False, f"{pw_var} saknas eller tomt i .env"


@check("Senaste körning")
def _last_run():
    logfile = os.path.join(os.path.dirname(__file__), "obit.log")
    if not os.path.exists(logfile):
        return None, "obit.log saknas — clio-agent-obit har aldrig körts"
    with open(logfile, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    if lines:
        return True, lines[-1]
    return None, "obit.log är tom"


def main():
    from dotenv import load_dotenv
    load_dotenv(override=True)

    print("clio-agent-obit — beroendecheck\n")
    errors = 0

    for label, fn in CHECKS:
        result, detail = fn()
        if result is True:
            icon = PASS
        elif result is False:
            icon = FAIL
            errors += 1
        else:
            icon = WARN  # None = valfritt/info
        print(f"  {icon}  {label}")
        print(f"       {detail}")

    print()
    if errors == 0:
        print("Allt OK — clio-agent-obit är redo att köras.")
    else:
        print(f"{errors} fel hittades — åtgärda innan du kör run.py.")
    return errors


if __name__ == "__main__":
    sys.exit(main())
