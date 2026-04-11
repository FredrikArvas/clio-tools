"""
clio_runners.py
Generiska run-helpers: run_tool, run_submenu, run_setup, run_check, export_source_zip.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT       = Path(__file__).parent
CONFIG_DIR = ROOT / "config"

# Python 3.12 venv för Ollama-beroende moduler (ollama-paketet stöder ej 3.14)
_VENV_OLLAMA_PYTHON = ROOT / "venv-ollama" / "Scripts" / "python.exe"
_OLLAMA_SCRIPTS     = {"clio_vision.py", "digikam_db.py"}

from clio_menu import (
    BackToMenu, _input,
    GRN, YEL, GRY, BLD, NRM,
    load_state, save_state, register_run,
    select_folder, clear,
)
from clio_run_research import run_research
from clio_run_mail     import run_mail
from clio_run_privfin  import run_privfin
from clio_run_obit     import run_obit

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key

try:
    from clio_env import check_environment as _check_environment
except ImportError:
    def _check_environment(**kwargs): pass


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _python_for(script: Path) -> str:
    """Returnerar rätt Python-körbar för givet script."""
    if script.name in _OLLAMA_SCRIPTS and _VENV_OLLAMA_PYTHON.exists():
        return str(_VENV_OLLAMA_PYTHON)
    return sys.executable


# ── Runners ───────────────────────────────────────────────────────────────────

def run_tool(tool: dict, state: dict) -> None:
    name         = tool["name"]
    needs_folder = tool.get("needs_folder", True)

    if tool.get("custom_runner"):
        if name == "clio-research":
            run_research(tool, state)
            return
        if name == "clio-agent-mail":
            run_mail(tool, state)
            return
        if name == "clio-agent-obit":
            run_obit(tool, state)
            return
        if name == "clio-privfin":
            run_privfin(tool, state)
            return

    if not tool["script"].exists():
        print(f"\nScript missing: {tool['script']}")
        input(t("menu_continue"))
        return

    folder = None
    if needs_folder:
        try:
            folder = select_folder(name, state)
        except BackToMenu:
            return
        if not folder:
            print(t("no_folder_selected"))
            input("\nPress Enter to continue...")
            return

        folder_path = Path(folder)
        if not folder_path.is_dir():
            print(f"\nFolder not found: {folder}")
            input("\nPress Enter to continue...")
            return

    try:
        if folder:
            state.setdefault("last_folder", {})[name] = folder
        state["last_run"] = name
        save_state(state)
    except Exception:
        pass

    print(f"\nStartar {name}...")
    print("─" * 40)
    start = datetime.now()

    cmd = [_python_for(tool["script"]), str(tool["script"])]
    if folder:
        cmd.append(folder)

    try:
        subprocess.run(cmd, text=True, errors="replace")
    except KeyboardInterrupt:
        print("\n(Avbruten av användaren)")
    except Exception as e:
        print(f"\nError running tool: {e}")

    elapsed = (datetime.now() - start).seconds
    print(f"\n{'─' * 40}")
    print(t("run_done", s=elapsed))

    try:
        register_run(name, folder or "", 0, 0, state)
        save_state(state)
    except Exception:
        pass

    input(t("menu_continue"))


def run_submenu(tool: dict, state: dict) -> None:
    """Visar undermeny för ett tool med submenu-lista."""
    while True:
        clear()
        print(f"\n{BLD}  {tool['name']}  —  {tool['desc']}{NRM}")
        print(f"{'─' * 56}")
        print()
        for item in tool["submenu"]:
            print(f"  {GRN}{item['nr']}.{NRM} {BLD}{item['name']}{NRM}")
            print(f"     {item['desc']}")
            print()
        print(f"  {YEL}0.{NRM} Tillbaka\n")
        print(f"{'─' * 56}")
        choice = input(t("menu_select")).strip().lower()
        if choice == "0":
            return
        try:
            nr = int(choice)
            match = next((i for i in tool["submenu"] if i["nr"] == nr), None)
            if match:
                run_tool(match, state)
        except ValueError:
            pass


def run_setup() -> None:
    """Guidat setup-flöde — skapar clio.config och .env."""
    config_file = ROOT / "clio.config"
    env_file    = ROOT / ".env"

    clear()
    print("\n" + "─" * 56)
    print("  Clio Setup")
    print("─" * 56)
    print()

    existing = []
    if config_file.exists(): existing.append("clio.config")
    if env_file.exists():    existing.append(".env")
    if existing:
        print(f"  Befintliga filer hittades: {', '.join(existing)}")
        ans = input("  Skriv över dem? [j/N]: ").strip().lower()
        if ans != "j":
            print("\n  Setup avbruten. Befintliga filer är oförändrade.")
            input("\nTryck Enter för att fortsätta...")
            return

    print()
    ans = input("  Har du clio.config och .env från en befintlig installation? [j/N]: ").strip().lower()
    if ans == "j":
        print()
        print("  Kopiera dina filer manuellt:")
        print(f"    1. clio.config  →  {config_file}")
        print(f"    2. .env         →  {env_file}")
        print()
        print("  Kör sedan 'python clio.py' för att starta.")
        input("\nTryck Enter för att fortsätta...")
        return

    print()
    print("  Ny installation — svara på frågorna nedan.")
    print("  (Tryck Enter för standardvärde / hoppa över)\n")

    name     = input("  Ditt namn: ").strip() or "Clio-användare"
    lang_in  = input("  Språk [sv/en, standard: sv]: ").strip().lower()
    language = lang_in if lang_in in ("sv", "en") else "sv"
    digikam  = input("  Sökväg till digikam4.db (Enter = hoppa över): ").strip()
    exiftool = input("  Sökväg till exiftool (Enter = 'exiftool' i PATH): ").strip() or "exiftool"

    print()
    print("  Notion parent page ID")
    print("  (Hitta det i Notion-URL:en: notion.so/.../DETTA-ID)")
    print("  (Lämna tomt om du inte använder Notion)")
    notion_page = input("  Notion page ID: ").strip()

    print()
    print("  Anthropic API-nyckel")
    print("  (Börjar med sk-ant-... — hämta på https://console.anthropic.com/)")
    anthropic_key = getpass.getpass("  ANTHROPIC_API_KEY: ").strip()

    print()
    print("  Notion API-nyckel (valfri)")
    print("  (Hämta på https://www.notion.so/my-integrations)")
    print("  (Glöm inte att dela dina Notion-sidor med integrationen)")
    print("  (Lämna tomt om du inte använder Notion)")
    notion_key = getpass.getpass("  NOTION_API_KEY (Enter = hoppa över): ").strip()

    config_content = f"""[user]
name = "{name}"
language = "{language}"

[paths]
digikam_db = "{digikam}"
exiftool = "{exiftool}"

[notion]
parent_page_id = "{notion_page}"
"""
    config_file.write_text(config_content, encoding="utf-8")

    env_lines = [f"ANTHROPIC_API_KEY={anthropic_key}"]
    if notion_key:
        env_lines.append(f"NOTION_API_KEY={notion_key}")
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    print()
    print("  Filer skapade:")
    print(f"    {config_file}")
    print(f"    {env_file}")

    print()
    print("  Kontrollerar miljön...")
    try:
        _check_environment()
        print("  [OK] Miljökontrollen OK")
    except SystemExit:
        print("  (Se felmeddelande ovan — åtgärda och kör 'python clio.py' igen)")
        input("\nTryck Enter för att fortsätta...")
        return

    print()
    print("  Setup klar. Kör 'python clio.py' för att starta.")
    input("\nTryck Enter för att fortsätta...")


def run_check() -> None:
    print()
    subprocess.run([sys.executable, str(CONFIG_DIR / "clio_check.py")])
    input("\nTryck Enter för att fortsätta...")


def export_source_zip() -> None:
    """Skapar clio-source.zip med all git-spårad källkod (git archive HEAD)."""
    clear()
    print("\n" + "─" * 56)
    print("  Exportera källkod")
    print("─" * 56)
    print()

    out = ROOT / "clio-source.zip"
    result = subprocess.run(
        ["git", "archive", "HEAD", "--format=zip", f"--output={out}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  Fel: {result.stderr.strip() or 'git archive misslyckades'}")
        input("\nTryck Enter för att fortsätta...")
        return

    size_kb = out.stat().st_size // 1024
    print(f"  Klar: {out}")
    print(f"  Storlek: {size_kb} KB")
    print()
    print(f"  {GRY}Ladda upp filen till Claude chat för att diskutera källkoden.{NRM}")
    input("\nTryck Enter för att fortsätta...")
