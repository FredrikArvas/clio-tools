"""
clio_menu.py
Färger, navigationshjälpare, state-hantering och menyvisning för clio-tools.

Ny TUI-standard (questionary):
  menu_select(title, choices)  → piltangentmeny, None = ← Tillbaka
  menu_confirm(question)       → Ja/Nej
  menu_text(prompt, validate)  → fritext, None = avbryt

Äldre API (_input, BackToMenu) behålls under migrering.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key

try:
    import questionary
    from questionary import Style
    _HAS_QUESTIONARY = True
except ImportError:
    _HAS_QUESTIONARY = False

# ── ANSI-hjälpare ────────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

def _vlen(s: str) -> int:
    """Synlig teckenlängd utan ANSI-escape-koder."""
    return len(_ANSI_RE.sub("", s))

def _rpad(s: str, width: int) -> str:
    """Paddar en ANSI-dekorerad sträng till synlig bredd."""
    return s + " " * max(0, width - _vlen(s))

def _trunc(s: str, maxlen: int) -> str:
    """Trunkerar ren sträng och lägger till … om den är för lång."""
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"

# ── Colors ────────────────────────────────────────────────────────────────────

GRN = "\033[92m"
YEL = "\033[93m"
GRY = "\033[90m"
BLU = "\033[94m"
BLD = "\033[1m"
NRM = "\033[0m"

# ── Questionary TUI-standard ──────────────────────────────────────────────────

_CLIO_STYLE = Style([
    ("qmark",       "fg:cyan bold"),
    ("question",    "bold"),
    ("answer",      "fg:green bold"),
    ("pointer",     "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected",    "fg:green"),
    ("instruction", "fg:gray"),
]) if _HAS_QUESTIONARY else None

_BACK = "← Tillbaka"


def menu_select(title: str, choices: list[str], back: bool = True) -> str | None:
    """Piltangentmeny. Returnerar valt värde eller None (← Tillbaka / avbryt).

    Faller tillbaka på numrerad input() om questionary saknas.
    """
    if _HAS_QUESTIONARY:
        opts = list(choices) + ([_BACK] if back else [])
        result = questionary.select(title, choices=opts, style=_CLIO_STYLE).ask()
        return None if result in (None, _BACK) else result

    # Fallback — detektera om val redan har inbyggda prefix ("1.", "c.", osv.)
    _PREFIX_RE = re.compile(r"^\s*([a-z0-9]+)\.\s", re.IGNORECASE)
    prefixes = [m.group(1) if (m := _PREFIX_RE.match(c)) else None for c in choices]
    use_embedded = all(p is not None for p in prefixes)

    print(f"\n{BLD}{title}{NRM}")
    for i, c in enumerate(choices, 1):
        if use_embedded:
            print(f"  {c}")          # val har redan "1.", "c." etc. — visa som de är
        else:
            print(f"  {i}. {c}")    # val utan prefix — lägg till sekventiellt index
    if back:
        print(f"  0. {_BACK}")
    raw = input("\nVal: ").strip()
    if raw == "0" or raw == "":
        return None
    if use_embedded:
        for c, p in zip(choices, prefixes):
            if p and p.lower() == raw.lower():
                return c
        return None
    if raw.isdigit() and 1 <= int(raw) <= len(choices):
        return choices[int(raw) - 1]
    return None


def menu_confirm(question: str, default: bool = True) -> bool:
    """Ja/Nej-fråga. Returnerar bool."""
    if _HAS_QUESTIONARY:
        result = questionary.confirm(question, default=default, style=_CLIO_STYLE).ask()
        return bool(result)
    ans = input(f"{question} [{'J/n' if default else 'j/N'}]: ").strip().lower()
    if ans == "":
        return default
    return ans in ("j", "ja", "y", "yes")


def menu_text(prompt: str, default: str = "", validate=None) -> str | None:
    """Fritext-prompt. Returnerar None om användaren lämnar tomt utan default."""
    if _HAS_QUESTIONARY:
        kwargs = {"style": _CLIO_STYLE}
        if default:
            kwargs["default"] = default
        if validate:
            kwargs["validate"] = validate
        result = questionary.text(prompt, **kwargs).ask()
        return result if result else None
    raw = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return raw or default or None


def menu_pause(msg: str = "Tryck Enter för att fortsätta...") -> None:
    """Pausar och väntar på Enter. Konsekvent i hela TUI:n."""
    input(f"\n{GRY}{msg}{NRM}")


# ── Navigation (äldre API — behålls under migrering) ─────────────────────────

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


def _tool_lines(tool: dict | None, state: dict, last_run: str | None,
                col_w: int) -> tuple[str, str, str]:
    """Bygger tre rader (namn, beskrivning, status) för ett verktyg, paddade till col_w."""
    if tool is None:
        return " " * col_w, " " * col_w, " " * col_w

    color  = GRN if tool.get("status") == "active" else GRY
    marker = f" {YEL}◀{NRM}" if tool["name"] == last_run else ""
    nr_s   = f"{tool['nr']}."

    runs   = state.get("runs", {}).get(tool["name"], [])
    if runs:
        st = f"{GRN}Last: {runs[-1].get('date', '')}{NRM}"
    else:
        st = f"{GRY}Never run{NRM}"

    l1 = f"  {color}{nr_s:>3}{NRM} {BLD}{tool['name']}{NRM}{marker}"
    l2 = f"     {GRY}{_trunc(tool['desc'], 30)}{NRM}"
    l3 = f"     {st}"

    return _rpad(l1, col_w), _rpad(l2, col_w), _rpad(l3, col_w)


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
    COL, SEP = 38, "  "

    # Para ihop verktyg: udda index → vänster, jämna → höger
    lefts  = tools[0::2]
    rights = tools[1::2]
    pairs  = list(zip(lefts, rights))
    if len(tools) % 2:
        pairs.append((tools[-1], None))

    for L, R in pairs:
        l1, l2, l3 = _tool_lines(L, state, last_run, COL)
        r1, r2, r3 = _tool_lines(R, state, last_run, COL)
        print(l1 + SEP + r1)
        print(l2 + SEP + r2)
        print(l3 + SEP + r3)
        print()

    print(f"  {YEL}c.{NRM} Kontrollera miljön   "
          f"  {YEL}e.{NRM} Exportera källkod   "
          f"  {YEL}q.{NRM} Avsluta\n")
    print(f"{'─' * 78}")


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
