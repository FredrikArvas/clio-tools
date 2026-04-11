"""
clio_menu.py
Färger, navigationshjälpare, state-hantering och menyvisning för clio-tools.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key

# ── Colors ────────────────────────────────────────────────────────────────────

GRN = "\033[92m"
YEL = "\033[93m"
GRY = "\033[90m"
BLU = "\033[94m"
BLD = "\033[1m"
NRM = "\033[0m"

# ── Navigation ────────────────────────────────────────────────────────────────

class BackToMenu(Exception):
    """Kastas när användaren skriver 0 i en aktiv prompt — återgår till huvudmenyn."""
    pass


def _input(prompt: str) -> str:
    """Wrappar input(). Kastar BackToMenu om användaren skriver '0'."""
    val = input(prompt)
    if val.strip() == "0":
        raise BackToMenu()
    return val

# ── State ─────────────────────────────────────────────────────────────────────

_ROOT       = Path(__file__).parent
_CONFIG_DIR = _ROOT / "config"
_STATE_FILE = _CONFIG_DIR / "clio_state.json"


def load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_folder": {}, "runs": {}}


def save_state(state: dict) -> None:
    _CONFIG_DIR.mkdir(exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def register_run(name: str, folder: str, succeeded: int, total: int, state: dict) -> None:
    state.setdefault("runs", {}).setdefault(name, []).append({
        "date":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        "folder":    folder,
        "succeeded": succeeded,
        "total":     total,
    })
    state["runs"][name] = state["runs"][name][-10:]
    state.setdefault("last_folder", {})[name] = folder
    folders = state.setdefault("recent_folders", [])
    if folder in folders:
        folders.remove(folder)
    folders.append(folder)
    state["recent_folders"] = folders[-10:]


def tool_status(tool: dict, state: dict) -> str:
    name  = tool["name"]
    runs  = state.get("runs", {}).get(name, [])
    if not runs:
        return f"{GRY}Never run{NRM}"
    last       = runs[-1]
    date       = last.get("date", "")
    ok         = last.get("succeeded", 0)
    total      = last.get("total", 0)
    folder     = last.get("folder", "")
    short      = ("..." + folder[-30:]) if len(folder) > 33 else folder
    return f"{GRN}Last: {date}{NRM} – {ok}/{total} files – {GRY}{short}{NRM}"

# ── Display ───────────────────────────────────────────────────────────────────

def clear() -> None:
    os.system("cls" if sys.platform == "win32" else "clear")


def show_menu(state: dict, tools: list, version: str,
              print_banner=None) -> None:
    clear()
    if print_banner:
        print_banner("Clio Tools", version, subtitle="")
    else:
        print(f"\n{BLD}{'─' * 56}{NRM}")
        print(f"{BLD}  Clio Tools  v{version}{NRM}")
        print(f"{BLD}{'─' * 56}{NRM}")
    print()

    last_run = state.get("last_run", None)

    for tool in tools:
        color  = GRN if tool["status"] == "active" else GRY
        marker = f" {YEL}◀{NRM}" if tool["name"] == last_run else ""
        print(f"  {color}{tool['nr']}.{NRM} {BLD}{tool['name']}{NRM}{marker}")
        print(f"     {tool['desc']}")
        print(f"     {tool_status(tool, state)}")
        print()

    print(f"  {YEL}c.{NRM} Kontrollera miljön (clio_check)")
    print(f"  {YEL}e.{NRM} Exportera källkod (ZIP för Claude chat)")
    print(f"  {YEL}q.{NRM} Avsluta\n")
    print(f"{'─' * 56}")


def select_folder(tool_name: str, state: dict) -> str | None:
    last   = state.get("last_folder", {}).get(tool_name, "")
    recent = state.get("recent_folders", [])

    if last:
        print(f"\nSenaste mapp: {YEL}{last}{NRM}")
        answer = _input(t("same_folder")).strip().lower()
        if answer in ("", "j"):
            return last

    others = [f for f in reversed(recent) if f != last]
    if others:
        print(t("menu_other_folders"))
        for i, f in enumerate(others[:5], 1):
            print(f"  {i}. {f}")
        print(t("menu_manual_path"))
        val = _input(t("menu_choice")).strip().strip('"')
        if val.isdigit() and 1 <= int(val) <= len(others[:5]):
            return others[int(val) - 1]
        elif val:
            return val
        return None

    folder = _input(t("menu_enter_folder")).strip().strip('"')
    return folder if folder else None
