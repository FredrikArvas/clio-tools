"""
clio_env.py
Lättviktig miljövakt — kontrollerar att allt är på plats innan clio startar.
Tyst om OK. Tydligt felmeddelande + exact fix-kommando vid problem, sedan sys.exit(1).

Usage:
    from clio_env import check_environment
    check_environment()                    # grundläggande kontroll
    check_environment(require_notion=True) # kräver även NOTION_API_KEY
"""

import os
import sys
import shutil
from pathlib import Path

__version__ = "1.0.0"

_ROOT = Path(__file__).parent


_ERR = "\033[91m[FEL]\033[0m"


def _fail(message: str, fix: str) -> None:
    print(f"\n{_ERR} {message}")
    print(f"  Fix: {fix}\n")
    sys.exit(1)


def check_environment(require_notion: bool = False) -> None:
    """Kontrollerar att miljön är komplett. Avslutar med felmeddelande om något saknas."""

    # Ladda .env om python-dotenv finns
    env_file = _ROOT / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=True)
    except ImportError:
        pass  # Faller tillbaka på os.environ

    # 1. clio.config måste finnas
    config_file = _ROOT / "clio.config"
    if not config_file.exists():
        _fail(
            "clio.config saknas",
            "python clio.py setup"
        )

    # 2. .env måste finnas och ANTHROPIC_API_KEY vara satt
    if not env_file.exists():
        _fail(
            ".env saknas",
            "python clio.py setup  (eller kopiera .env från befintlig installation)"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        _fail(
            "ANTHROPIC_API_KEY inte satt i .env",
            "python clio.py setup  (eller lägg till ANTHROPIC_API_KEY=sk-ant-... i .env)"
        )

    # 3. Notion-nyckel (valfri flagga)
    if require_notion:
        notion_key = os.environ.get("NOTION_API_KEY", "").strip()
        if not notion_key:
            _fail(
                "NOTION_API_KEY inte satt i .env (krävs för detta delprogram)",
                "Lägg till NOTION_API_KEY=ntn_... i .env  (hämta på notion.so/my-integrations)"
            )

    # 4. Kritiska pip-paket
    missing = []
    for pkg, import_name in [("anthropic", "anthropic"), ("python-dotenv", "dotenv"), ("Pillow", "PIL")]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        _fail(
            f"Saknar pip-paket: {', '.join(missing)}",
            f"Install by copy this to the command-line: pip install {' '.join(missing)}"
        )

    # 5. exiftool — via PATH eller sökväg ur clio.config
    exiftool_cmd = shutil.which("exiftool")
    if not exiftool_cmd:
        # Försök läsa sökväg ur clio.config (enkel TOML-parsning utan extern dep)
        exiftool_cmd = _read_exiftool_from_config(config_file)

    if not exiftool_cmd or not shutil.which(exiftool_cmd) and not Path(exiftool_cmd).exists():
        _fail(
            "exiftool hittades inte",
            "1 Windows: ladda ned från exiftool.org. Packa upp programmet, byt namn på "
            "exiftool(k).exe till exiftool.exe och lägg sedan den och katalogen "
            "\"exif_tools\" i C:\\windows\\system32\\"
        )


def _read_exiftool_from_config(config_file: Path) -> str:
    """Läser exiftool-sökväg ur clio.config utan extern TOML-parser."""
    try:
        for line in config_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("exiftool"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    value = parts[1].strip().strip('"').strip("'")
                    if value and value != "exiftool":
                        return value
    except Exception:
        pass
    return ""
