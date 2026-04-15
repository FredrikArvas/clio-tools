"""
check_deps.py
Verifierar att alla beroenden för clio-agent-job är på plats.
Kör: python check_deps.py
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

_BASE_DIR = Path(__file__).parent
_ROOT_DIR = _BASE_DIR.parent

GRN = "\033[32m"
RED = "\033[31m"
YEL = "\033[33m"
NRM = "\033[0m"
BLD = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {GRN}[OK]{NRM}  {msg}")


def _err(msg: str) -> None:
    print(f"  {RED}[FEL]{NRM} {msg}")


def _warn(msg: str) -> None:
    print(f"  {YEL}[OBS]{NRM} {msg}")


def check(verbose: bool = True) -> int:
    """Kör alla kontroller. Returnerar antal fel."""
    errors = 0

    print(f"\n{BLD}  clio-agent-job -- Beroendekontroll{NRM}")
    print("  " + "-" * 40)

    # 1. Python-version
    major, minor = sys.version_info[:2]
    if major >= 3 and minor >= 8:
        _ok(f"Python {major}.{minor}")
    else:
        _err(f"Python {major}.{minor} — kräver 3.8+")
        errors += 1

    # 2. feedparser
    try:
        importlib.import_module("feedparser")
        _ok("feedparser (RSS-insamling)")
    except ImportError:
        _err("feedparser saknas — kör: pip install feedparser")
        errors += 1

    # 3. anthropic
    try:
        importlib.import_module("anthropic")
        _ok("anthropic (Claude API)")
    except ImportError:
        _err("anthropic saknas — kör: pip install anthropic")
        errors += 1

    # 4. pyyaml
    try:
        importlib.import_module("yaml")
        _ok("pyyaml (konfiguration)")
    except ImportError:
        _err("pyyaml saknas — kör: pip install pyyaml")
        errors += 1

    # 5. python-dotenv
    try:
        importlib.import_module("dotenv")
        _ok("python-dotenv (.env-laddning)")
    except ImportError:
        _warn("python-dotenv saknas (valfri) — kör: pip install python-dotenv")

    # 6. clio-core
    try:
        sys.path.insert(0, str(_ROOT_DIR / "clio-core"))
        importlib.import_module("clio_core")
        _ok("clio-core (delat bibliotek)")
    except ImportError:
        _warn("clio-core ej installerat — kör: pip install -e ../clio-core")

    # 7. sources.yaml finns och har aktiva källor
    sources_yaml = _BASE_DIR / "sources" / "sources.yaml"
    if sources_yaml.exists():
        try:
            import yaml
            with open(sources_yaml, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            enabled = [s for s in data.get("sources", []) if s.get("enabled")]
            if enabled:
                _ok(f"sources.yaml ({len(enabled)} aktiva källor)")
            else:
                _warn("sources.yaml finns men inga källor är enabled:true")
        except Exception as e:
            _err(f"sources.yaml parsningsfel: {e}")
            errors += 1
    else:
        _err(f"sources.yaml saknas: {sources_yaml}")
        errors += 1

    # 8. Profil finns
    default_profile = _BASE_DIR / "profiles" / "richard.yaml"
    if default_profile.exists():
        _ok(f"Standardprofil: profiles/richard.yaml")
    else:
        _warn("Standardprofil saknas: profiles/richard.yaml")

    # 9. .env finns (root eller modul)
    env_root = _ROOT_DIR / ".env"
    env_local = _BASE_DIR / ".env"
    if env_root.exists() or env_local.exists():
        _ok(".env finns")
        # Ladda och kontrollera ANTHROPIC_API_KEY
        try:
            from dotenv import load_dotenv
            load_dotenv(env_root, override=True)
            load_dotenv(env_local, override=True)
        except ImportError:
            pass
        if os.environ.get("ANTHROPIC_API_KEY"):
            _ok("ANTHROPIC_API_KEY är satt")
        else:
            _err("ANTHROPIC_API_KEY saknas i .env")
            errors += 1
    else:
        _err(".env saknas — kopiera .env.example till .env och fyll i")
        errors += 1

    # 10. config.yaml finns
    config_yaml = _BASE_DIR / "config.yaml"
    if config_yaml.exists():
        _ok("config.yaml (SMTP och trösklar)")
        try:
            import yaml
            with open(config_yaml, encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            smtp = cfg.get("smtp", {})
            if smtp.get("host") and smtp.get("user"):
                _ok("SMTP konfigurerat i config.yaml")
            else:
                _warn("SMTP ofullständigt i config.yaml (smtp.host och smtp.user behövs)")
        except Exception:
            pass
    else:
        _warn("config.yaml saknas — kopiera från mallen och konfigurera SMTP")

    print()
    if errors == 0:
        print(f"  {GRN}{BLD}Alla kontroller OK.{NRM}")
    else:
        print(f"  {RED}{BLD}{errors} fel hittades — åtgärda ovan och kör om.{NRM}")
    print()

    return errors


if __name__ == "__main__":
    failed = check(verbose=True)
    sys.exit(failed)
