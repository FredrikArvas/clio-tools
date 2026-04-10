#!/usr/bin/env python3
"""
install.py — ClioTools Installer v1.1

Interaktivt installationsscript för clio-tools-ekosystemet.
Inventerar systemet, installerar beroenden med ditt medgivande,
sätter PATH och loggar alla åtgärder i install_log.json.

Kör igen när uppskjutna beroenden är klara: python install.py
Ångra: python uninstall.py  (läser install_log.json)

Körning:
    python clio-install/install.py            (från clio-tools-roten)
    python install.py                         (från clio-install/)
    python install.py --venv                  (isolerad venv, standard: .venv/)
    python install.py --venv C:\\temp\\clio-env  (egen venv-sökväg)

Flaggor:
    --yes, -y         Auto-bekräfta alla installationer (agent-läge)
    --dry-run         Visa vad som skulle göras utan att installera
    --venv [PATH]     Kör i virtuell miljö — skapar om den saknas
    --check           Kör check_all.py som regressionstest efter installation
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import winreg
    _HAS_WINREG = True
except ImportError:
    _HAS_WINREG = False

# ── Sökvägar ──────────────────────────────────────────────────────────────────
VERSION       = "1.1"
INSTALLER_DIR = Path(__file__).resolve().parent
ROOT          = INSTALLER_DIR.parent          # clio-tools rot
LOG_FILE      = INSTALLER_DIR / "install_log.json"
CLIO_CORE_DIR = ROOT / "clio-core"
ENV_FILE      = ROOT / ".env"
ENV_EXAMPLE   = ROOT / ".env.example"

# ── pip-paket (kategori A) ────────────────────────────────────────────────────
# (import_name, pip_spec, display_name, metadata_pkg_name)
PIP_PACKAGES: list[tuple[str, str, str, str]] = [
    ("anthropic",      "anthropic>=0.25.0",          "anthropic",          "anthropic"),
    ("dotenv",         "python-dotenv>=1.0.0",       "python-dotenv",      "python-dotenv"),
    ("notion_client",  "notion-client>=2.0.0",       "notion-client",      "notion-client"),
    ("thefuzz",        "thefuzz>=0.19.0",             "thefuzz",            "thefuzz"),
    ("Levenshtein",    "python-Levenshtein>=0.12.0",  "python-Levenshtein", "python-levenshtein"),
    ("openpyxl",       "openpyxl>=3.1.0",             "openpyxl",           "openpyxl"),
    ("ocrmypdf",       "ocrmypdf>=16.0.0",            "ocrmypdf",           "ocrmypdf"),
    ("pypdf",          "pypdf>=4.0.0",                "pypdf",              "pypdf"),
    ("fitz",           "pymupdf>=1.23.0",             "pymupdf",            "pymupdf"),
    ("PIL",            "Pillow>=10.0.0",               "Pillow",             "pillow"),
    ("pytesseract",    "pytesseract>=0.3.10",         "pytesseract",        "pytesseract"),
    ("exiftool",       "pyexiftool>=0.5.0",           "pyexiftool",         "pyexiftool"),
    ("faster_whisper", "faster-whisper>=1.0.0",       "faster-whisper",     "faster-whisper"),
    ("edge_tts",       "edge-tts>=6.0.0",              "edge-tts",           "edge-tts"),
    ("mutagen",        "mutagen>=1.45.0",              "mutagen",            "mutagen"),
    ("docx",           "python-docx>=0.8.11",          "python-docx",        "python-docx"),
    ("requests",       "requests>=2.31.0",             "requests",           "requests"),
    ("bs4",            "beautifulsoup4>=4.12.0",      "beautifulsoup4",     "beautifulsoup4"),
    ("lxml",           "lxml>=4.9.0",                  "lxml",               "lxml"),
    ("chardet",        "chardet>=5.0.0",               "chardet",            "chardet"),
    ("send2trash",     "send2trash>=1.8.0",            "send2trash",         "send2trash"),
    ("keyring",        "keyring>=24.0.0",              "keyring",            "keyring"),
    ("yaml",           "pyyaml>=6.0",                  "pyyaml",             "pyyaml"),
    ("gedcom",         "python-gedcom>=1.0.0",         "python-gedcom",      "python-gedcom"),
]

# ── Systemprogram (kategori C) ────────────────────────────────────────────────
SYSTEM_TOOLS: list[dict] = [
    dict(id="python",    name="Python 3.x",   cmd="python",    blocking=True,  optional=False,
         winget=None,  # Python är alltid installerat (vi kör ju just nu)
         manual_url="https://python.org",
         local_search=None),
    dict(id="git",       name="Git",           cmd="git",       blocking=True,  optional=False,
         winget="winget install Git.Git",
         manual_url="https://git-scm.com",
         local_search=None),
    dict(id="exiftool",  name="exiftool",      cmd="exiftool",  blocking=False, optional=False,
         winget=None,   # Ingen winget — lokal kopia i clio-vision/
         manual_url="https://exiftool.org",
         local_search="clio-vision/exiftool-13.54_64/exiftool.exe"),
    dict(id="ollama",    name="Ollama",        cmd="ollama",    blocking=False, optional=False,
         winget="winget install Ollama.Ollama",
         manual_url="https://ollama.com/download",
         local_search=None),
    dict(id="tesseract", name="Tesseract OCR", cmd="tesseract", blocking=False, optional=False,
         winget="winget install UB-Mannheim.TesseractOCR",
         manual_url="https://github.com/UB-Mannheim/tesseract/wiki",
         local_search=None),
    dict(id="digikam",   name="DigiKam",       cmd="digikam",   blocking=False, optional=True,
         winget="winget install KDE.digiKam",
         manual_url="https://digikam.org",
         local_search=None),
]

# ── Grov diskestimat per pip-paket (MB, inkl. beroenden) ─────────────────────
# faster-whisper drar PyTorch + ctranslate2 — klart störst.
DISK_ESTIMATES_MB: dict[str, int] = {
    "faster-whisper":     2500,
    "pymupdf":              50,
    "ocrmypdf":             35,
    "lxml":                 12,
    "Pillow":               10,
    "anthropic":             8,
    "notion-client":         5,
    "python-docx":           5,
    "openpyxl":              5,
    "requests":              4,
    "beautifulsoup4":        3,
    "edge-tts":              3,
    "pypdf":                 3,
    "keyring":               2,
    "mutagen":               2,
    "python-Levenshtein":    2,
    "thefuzz":               2,
    "chardet":               1,
    "pyexiftool":            2,
    "pytesseract":           2,
    "pyyaml":                2,
    "python-gedcom":         2,
    "python-dotenv":         1,
    "send2trash":            1,
}
LLAVA_MB = 4096   # ~4 GB för llava-modellen

# ── Felkoder ──────────────────────────────────────────────────────────────────
E_USER_DEFERRED   = "E_USER_DEFERRED"
E_WINGET_FAILED   = "E_WINGET_FAILED"
E_PIP_FAILED      = "E_PIP_FAILED"
E_PATH_DENIED     = "E_PATH_DENIED"
E_DEP_NOT_FOUND   = "E_DEP_NOT_FOUND"
E_DISK_FOUND_NO_PATH = "E_DISK_FOUND_NO_PATH"


# ══════════════════════════════════════════════════════════════════════════════
# Logg-hjälpare
# ══════════════════════════════════════════════════════════════════════════════

def _init_log() -> dict:
    return {
        "install_date":       datetime.now().isoformat(timespec="seconds"),
        "installer_version":  VERSION,
        "machine":            platform.node(),
        "python_version":     platform.python_version(),
        "actions":            [],
        "path_changes":       [],
        "pip_installed":      [],
    }


def _log_action(log: dict, component: str, type_: str, action: str,
                status: str, *, version: str = "", path: str = "",
                error_code: str = "") -> None:
    entry: dict = {
        "timestamp":   datetime.now().isoformat(timespec="seconds"),
        "component":   component,
        "type":        type_,
        "action":      action,
        "status":      status,
        "error_code":  error_code or None,
    }
    if version:
        entry["version"] = version
    if path:
        entry["path"] = path
    log["actions"].append(entry)

    if status == "OK" and type_ == "pip":
        ver_tag = f"=={version}" if version else ""
        log["pip_installed"].append(f"{component}{ver_tag}")
    if status == "OK" and type_ == "path" and path:
        log["path_changes"].append(path)


def _save_log(log: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# Detekterings-hjälpare
# ══════════════════════════════════════════════════════════════════════════════

def _pkg_version(metadata_name: str) -> str:
    """Returnerar installerad version eller tom sträng."""
    try:
        return importlib.metadata.version(metadata_name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _is_pip_installed(import_name: str) -> bool:
    return importlib.util.find_spec(import_name) is not None


def _is_clio_core_installed() -> bool:
    return importlib.util.find_spec("clio_core") is not None


def _tool_version_str(cmd: str) -> str:
    """Returnerar version-sträng från CLI-verktyg eller tom sträng."""
    flags_map = {
        "git":        ["--version"],
        "exiftool":   ["-ver"],
        "ollama":     ["--version"],
        "tesseract":  ["--version"],
        "digikam":    ["--version"],
    }
    flags = flags_map.get(cmd, ["--version"])
    try:
        result = subprocess.run(
            [cmd] + flags,
            capture_output=True, text=True, timeout=8
        )
        out = (result.stdout + result.stderr).strip()
        return out.split("\n")[0] if out else "OK"
    except Exception:
        return ""


def _find_local_tool(relative_path: str) -> Path | None:
    """Letar efter ett verktyg på disk relativt repo-roten."""
    p = ROOT / relative_path
    return p if p.exists() else None


def _check_api_key() -> bool:
    """Kollar om ANTHROPIC_API_KEY är satt i miljö eller .env-fil."""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return True
    if ENV_FILE.exists():
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    val = line.strip().split("=", 1)[1].strip()
                    return bool(val and val != "your_key_here")
    return False


def _check_ollama_has_llava() -> bool:
    """Kontrollerar om llava-modellen är nedladdad i Ollama."""
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=10
        )
        return "llava" in result.stdout.lower()
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Åtgärds-hjälpare
# ══════════════════════════════════════════════════════════════════════════════

def _ask(prompt: str, default: str = "N", auto_yes: bool = False) -> str:
    """Frågar användaren. Returnerar 'j', 'n' eller 'h' (hoppa)."""
    if auto_yes:
        print(f"{prompt}[auto: j]")
        return "j"
    while True:
        try:
            ans = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "n"
        if not ans:
            return default[0].lower()
        if ans in ("j", "ja", "y", "yes"):
            return "j"
        if ans in ("n", "nej", "no"):
            return "n"
        if ans in ("h", "hoppa", "s", "skip", "vänta", "vanta"):
            return "h"
        print("  Ange j (ja), n (nej) eller h (hoppa över)")


def _pip_install(pip_spec: str, dry_run: bool = False) -> tuple[bool, str, str]:
    """
    Installerar ett pip-paket.
    Returnerar (success, version, error_code).
    """
    if dry_run:
        return True, "(dry-run)", ""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", pip_spec, "--quiet"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False, "", E_PIP_FAILED
    # Hämta version från metadata
    pkg_name = pip_spec.split(">=")[0].split("==")[0].split("[")[0]
    try:
        ver = importlib.metadata.version(pkg_name)
    except Exception:
        ver = ""
    return True, ver, ""


def _winget_install(winget_cmd: str, dry_run: bool = False) -> tuple[bool, str]:
    """
    Kör ett winget-kommando.
    Returnerar (success, error_code).
    """
    if dry_run:
        return True, ""
    parts = winget_cmd.split()
    try:
        result = subprocess.run(parts, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return True, ""
        return False, E_WINGET_FAILED
    except FileNotFoundError:
        return False, E_WINGET_FAILED
    except subprocess.TimeoutExpired:
        return False, E_WINGET_FAILED


def _install_clio_core(dry_run: bool = False) -> tuple[bool, str, str]:
    """
    Installerar clio-core i editable mode.
    Returnerar (success, version, error_code).
    """
    if not CLIO_CORE_DIR.exists():
        return False, "", E_DEP_NOT_FOUND
    if dry_run:
        return True, "(dry-run)", ""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(CLIO_CORE_DIR), "--quiet"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False, "", E_PIP_FAILED
    try:
        ver = importlib.metadata.version("clio-core")
    except Exception:
        ver = "editable"
    return True, ver, ""


def _add_to_user_path(new_path: str, dry_run: bool = False) -> tuple[bool, str]:
    """
    Lägger till ny_sökväg i user-PATH via Windows Registry.
    Returnerar (success, error_code).
    """
    if dry_run:
        return True, ""
    if not _HAS_WINREG:
        return False, E_PATH_DENIED

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
        try:
            current, reg_type = winreg.QueryValueEx(key, "PATH")
        except FileNotFoundError:
            current, reg_type = "", winreg.REG_SZ

        if new_path.lower() in current.lower():
            winreg.CloseKey(key)
            return True, ""  # redan i PATH

        new_value = current.rstrip(";") + ";" + new_path
        winreg.SetValueEx(key, "PATH", 0, reg_type, new_value)
        winreg.CloseKey(key)

        # Notifiera Windows om PATH-ändringen
        try:
            import ctypes
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None
            )
        except Exception:
            pass  # Icke-kritiskt

        return True, ""
    except PermissionError:
        return False, E_PATH_DENIED
    except Exception:
        return False, E_PATH_DENIED


def _ensure_env_stub(dry_run: bool = False) -> bool:
    """Skapar .env-stub om filen inte finns. Returnerar True om .env nu finns."""
    if ENV_FILE.exists():
        return True
    if dry_run:
        return False
    if ENV_EXAMPLE.exists():
        import shutil as _sh
        _sh.copy(ENV_EXAMPLE, ENV_FILE)
    else:
        ENV_FILE.write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Förhandsvisning — wizard
# ══════════════════════════════════════════════════════════════════════════════

def preflight_wizard(args: argparse.Namespace) -> bool:
    """
    Visar vad som kommer att installeras och en grov diskuppskattning.
    Returnerar True om användaren vill fortsätta (eller --yes), annars False.
    Körs tyst (ingen skärm) om allt redan är installerat.
    """
    # Snabbscan: pip
    missing_pip: list[tuple[str, str]] = [
        (display_name, pip_spec)
        for import_name, pip_spec, display_name, _ in PIP_PACKAGES
        if not _is_pip_installed(import_name)
    ]

    # Snabbscan: systemverktyg (utom python — alltid OK)
    missing_system: list[dict] = [
        t for t in SYSTEM_TOOLS
        if t["id"] != "python" and not shutil.which(t["cmd"])
    ]

    clio_missing = not _is_clio_core_installed()

    # llava-check (timeout 5 s — samma som step1)
    llava_missing = False
    if shutil.which("ollama"):
        try:
            r = subprocess.run(
                ["ollama", "list"], capture_output=True, text=True, timeout=5
            )
            llava_missing = "llava" not in r.stdout.lower()
        except Exception:
            pass

    # Inget att göra — hoppa wizard
    if not missing_pip and not missing_system and not clio_missing:
        return True

    # Beräkna diskestimat
    pip_mb = sum(
        DISK_ESTIMATES_MB.get(name, 3)
        for name, _ in missing_pip
    )
    llava_mb = LLAVA_MB if llava_missing else 0
    total_mb = pip_mb + (1 if clio_missing else 0) + llava_mb

    def _fmt_mb(mb: int) -> str:
        return f"~{mb / 1024:.1f} GB" if mb >= 1024 else f"~{mb} MB"

    print("  Förhandsvisning — vad som kommer att installeras:")
    print()

    if missing_pip:
        # Tunga paket (> 10 MB) visas individuellt
        heavy   = [(n, s) for n, s in missing_pip if DISK_ESTIMATES_MB.get(n, 3) > 10]
        n_light  = len(missing_pip) - len(heavy)
        light_mb = sum(DISK_ESTIMATES_MB.get(n, 3) for n, _ in missing_pip
                       if DISK_ESTIMATES_MB.get(n, 3) <= 10)
        for name, _ in heavy:
            mb = DISK_ESTIMATES_MB.get(name, 3)
            print(f"    pip  {name:<28} {_fmt_mb(mb):>10}")
        if n_light:
            print(f"    pip  {n_light} mindre paket{'':<17} {_fmt_mb(light_mb):>10}")

    if clio_missing:
        print(f"    pip  clio-core (editable){'':<13}    < 1 MB")

    for t in missing_system:
        lbl = "(valfri) " + t["name"] if t.get("optional") else t["name"]
        print(f"    sys  {lbl}")

    if llava_missing:
        print(f"    ollama  llava-modell{'':<17} {_fmt_mb(LLAVA_MB):>10}")

    print()
    if total_mb > 0:
        print(f"  Beräknad diskåtgång: {_fmt_mb(total_mb)}"
              + ("  (llava ingår)" if llava_missing else ""))
        print()

    if args.yes:
        print("  [--yes] Fortsätter automatiskt.")
        print()
        return True

    ans = _ask("  Fortsätt med installationen? [j/N]: ", default="N", auto_yes=False)
    print()
    return ans == "j"


# ══════════════════════════════════════════════════════════════════════════════
# Steg 1 — Systemprogram
# ══════════════════════════════════════════════════════════════════════════════

def step1_system(log: dict, args: argparse.Namespace) -> dict:
    """Kontrollerar och installerar systemprogram. Returnerar statistik."""
    print("\nSteg 1/4: Inventerar systemet...")
    print()

    stats = dict(ok=0, installed=0, deferred=0, failed=0)

    for tool in SYSTEM_TOOLS:
        tid   = tool["id"]
        name  = tool["name"]
        cmd   = tool["cmd"]
        opt   = tool.get("optional", False)
        lbl   = f"(valfri) {name}" if opt else name

        # ── Python: alltid tillgänglig ──────────────────────────────────────
        if tid == "python":
            ver = platform.python_version()
            print(f"  ✅  {name} {ver} — OK")
            _log_action(log, "python", "system", "verified", "OK", version=ver)
            stats["ok"] += 1
            continue

        # ── Kontrollera om verktyget finns i PATH ───────────────────────────
        if shutil.which(cmd):
            ver = _tool_version_str(cmd)
            print(f"  ✅  {lbl} — {ver or 'OK'}")
            _log_action(log, tid, "system", "verified", "OK", version=ver)
            stats["ok"] += 1

            # Ollama: fråga om llava oavsett om den precis installerades
            if tid == "ollama":
                _maybe_pull_llava(log, args)
            continue

        # ── Inte i PATH — kolla lokal kopia ─────────────────────────────────
        local = None
        if tool.get("local_search"):
            local = _find_local_tool(tool["local_search"])

        if local:
            local_dir = str(local.parent)
            print(f"  ⚠️   {lbl} — hittades inte i PATH")
            print(f"       Lokal kopia hittad: {local}")
            ans = _ask(f"       → Lägg till {local_dir} i PATH? [j/N/h]: ",
                       default="N", auto_yes=args.yes)
            if ans == "j":
                ok, err = _add_to_user_path(local_dir, dry_run=args.dry_run)
                if ok:
                    print(f"  ✅  PATH uppdaterat — kräver ny terminal för att gälla")
                    _log_action(log, tid, "path", "added_to_path", "OK", path=local_dir)
                    stats["installed"] += 1
                else:
                    print(f"  ❌  Kunde inte uppdatera PATH ({err})")
                    _log_action(log, tid, "path", "add_path_failed", "FAILED",
                                path=local_dir, error_code=err)
                    stats["failed"] += 1
            else:
                print(f"       → Uppskjutet. Lägg till manuellt eller kör igen.")
                _log_action(log, tid, "path", "deferred", "WAIT",
                            path=local_dir, error_code=E_DISK_FOUND_NO_PATH)
                stats["deferred"] += 1
            continue

        # ── Saknas helt ──────────────────────────────────────────────────────
        print(f"  ❌  {lbl} — saknas")
        if tool.get("winget"):
            print(f"       Auto-install:  {tool['winget']}")
        print(f"       Manuell:       {tool['manual_url']}")
        if tool.get("blocking"):
            print(f"       ⚠️  Blockande — krävs för att fortsätta")

        if tool.get("winget"):
            ans = _ask(f"       → Installera nu automatiskt? [j/N/h]: ",
                       default="N", auto_yes=args.yes)
        else:
            ans = _ask(f"       → Hanterat manuellt — hoppa för nu? [j=ja hoppa/n=avbryt]: ",
                       default="j", auto_yes=args.yes)
            # Mappa j → h för "hoppa" i detta fall
            if ans == "j":
                ans = "h"

        if ans == "j":
            print(f"       Installerar via winget...")
            ok, err = _winget_install(tool["winget"], dry_run=args.dry_run)
            if ok:
                # Verifiera att det nu finns i PATH
                if shutil.which(cmd) or args.dry_run:
                    ver = _tool_version_str(cmd) if not args.dry_run else "(dry-run)"
                    print(f"  ✅  {name} installerat — {ver or 'OK'}")
                    _log_action(log, tid, "system", "installed", "OK", version=ver)
                    stats["installed"] += 1
                    if tid == "ollama":
                        _maybe_pull_llava(log, args)
                else:
                    print(f"  ⚠️   Installerat men ej i PATH ännu — starta om terminalen")
                    _log_action(log, tid, "system", "installed_no_path", "WAIT",
                                error_code=E_DISK_FOUND_NO_PATH)
                    stats["deferred"] += 1
            else:
                print(f"  ❌  winget misslyckades. Installera manuellt: {tool['manual_url']}")
                print(f"       Kommando: {tool.get('winget', '')}")
                _log_action(log, tid, "system", "winget_failed", "FAILED",
                            error_code=E_WINGET_FAILED)
                stats["failed"] += 1
        else:
            # Deferred eller hoppa
            print(f"       → Uppskjutet.")
            if tool.get("winget"):
                print(f"       Kör när du är redo:  {tool['winget']}")
            print(f"       Manuell nedladdning:  {tool['manual_url']}")
            _log_action(log, tid, "system", "deferred", "WAIT",
                        error_code=E_USER_DEFERRED)
            stats["deferred"] += 1

    print()
    return stats


def _maybe_pull_llava(log: dict, args: argparse.Namespace) -> None:
    """Frågar om llava-modellen ska laddas ned om den saknas."""
    # Kolla llava snabbt — om ollama inte svarar, hoppa
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        if "llava" in result.stdout.lower():
            print("       llava — redan nedladdad ✅")
            return
    except Exception:
        # Ollama svarar inte — hoppa tyst
        return

    # I --yes-läge: skip automatiskt (4 GB download kräver explicit val)
    if args.yes:
        print("       llava saknas — kör: ollama pull llava")
        _log_action(log, "ollama-llava", "system", "deferred", "WAIT",
                    error_code=E_USER_DEFERRED)
        return

    ans = _ask("       → Ladda ned llava-modellen (~4 GB)? [j/N]: ",
               default="N", auto_yes=False)
    if ans == "j" and not args.dry_run:
        print("       Laddar ned llava... (kan ta tid)")
        subprocess.run(["ollama", "pull", "llava"])
        _log_action(log, "ollama-llava", "system", "pulled", "OK")
    elif ans == "j" and args.dry_run:
        print("       (dry-run) ollama pull llava")
    else:
        print("       → Hoppar över llava. Kör: ollama pull llava")
        _log_action(log, "ollama-llava", "system", "deferred", "WAIT",
                    error_code=E_USER_DEFERRED)


# ══════════════════════════════════════════════════════════════════════════════
# Steg 2 — pip-paket
# ══════════════════════════════════════════════════════════════════════════════

def step2_pip(log: dict, args: argparse.Namespace) -> dict:
    """Kontrollerar och installerar pip-paket. Returnerar statistik."""
    print("Steg 2/4: Python-paket...")
    print()

    stats = dict(ok=0, installed=0, deferred=0, failed=0, elapsed_s=0.0)
    missing: list[tuple] = []

    # Inventera
    for import_name, pip_spec, display_name, meta_name in PIP_PACKAGES:
        if _is_pip_installed(import_name):
            ver = _pkg_version(meta_name)
            print(f"  ✅  {display_name} {ver}")
            _log_action(log, display_name, "pip", "verified", "OK", version=ver)
            stats["ok"] += 1
        else:
            print(f"  ❌  {display_name} — saknas")
            missing.append((import_name, pip_spec, display_name, meta_name))

    if not missing:
        print()
        return stats

    # Installera saknade
    print()
    print(f"  {len(missing)} paket saknas.")
    ans = _ask(f"  → Installera alla {len(missing)} saknade paket? [j/N/h]: ",
               default="N", auto_yes=args.yes)

    if ans == "n":
        for _, pip_spec, display_name, _ in missing:
            _log_action(log, display_name, "pip", "deferred", "WAIT",
                        error_code=E_USER_DEFERRED)
            stats["deferred"] += 1
    elif ans == "h":
        for _, pip_spec, display_name, _ in missing:
            _log_action(log, display_name, "pip", "deferred", "WAIT",
                        error_code=E_USER_DEFERRED)
            stats["deferred"] += 1
    else:
        for import_name, pip_spec, display_name, meta_name in missing:
            print(f"  Installerar {display_name}...", end=" ", flush=True)
            t0 = time.time()
            ok, ver, err = _pip_install(pip_spec, dry_run=args.dry_run)
            elapsed = time.time() - t0
            stats["elapsed_s"] += elapsed
            if ok:
                print(f"✅ {ver}  ({elapsed:.0f}s)")
                _log_action(log, display_name, "pip", "installed", "OK",
                            version=ver)
                stats["installed"] += 1
            else:
                print(f"❌")
                print(f"     Kör manuellt: pip install {pip_spec}")
                _log_action(log, display_name, "pip", "failed", "FAILED",
                            error_code=E_PIP_FAILED)
                stats["failed"] += 1

    print()
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# Steg 3 — clio-core
# ══════════════════════════════════════════════════════════════════════════════

def step3_clio_core(log: dict, args: argparse.Namespace) -> dict:
    """Installerar clio-core (editable). Returnerar statistik."""
    print("Steg 3/4: clio-core...")
    print()

    stats = dict(ok=0, installed=0, deferred=0, failed=0)

    if _is_clio_core_installed():
        ver = _pkg_version("clio-core")
        print(f"  ✅  clio_core {ver or 'installerad'}")
        _log_action(log, "clio-core", "pip", "verified", "OK", version=ver)
        stats["ok"] += 1
        print()
        return stats

    print(f"  ❌  clio_core — ej installerad")

    if not CLIO_CORE_DIR.exists():
        print(f"  ⚠️   Mappen {CLIO_CORE_DIR} hittades inte")
        _log_action(log, "clio-core", "pip", "failed", "FAILED",
                    error_code=E_DEP_NOT_FOUND)
        stats["failed"] += 1
        print()
        return stats

    print(f"       Källa: {CLIO_CORE_DIR}")
    ans = _ask("       → pip install -e ./clio-core? [j/N/h]: ",
               default="N", auto_yes=args.yes)

    if ans == "j":
        print("       Installerar...", end=" ", flush=True)
        ok, ver, err = _install_clio_core(dry_run=args.dry_run)
        if ok:
            print(f"✅ {ver}")
            _log_action(log, "clio-core", "pip", "installed", "OK",
                        version=ver, path=str(CLIO_CORE_DIR))
            log["pip_installed"].append(f"clio-core @ {CLIO_CORE_DIR}")
            stats["installed"] += 1
        else:
            print("❌")
            print(f"       Kör manuellt: pip install -e {CLIO_CORE_DIR}")
            _log_action(log, "clio-core", "pip", "failed", "FAILED",
                        error_code=err)
            stats["failed"] += 1
    else:
        print("       → Uppskjutet.")
        print(f"       Kör manuellt: pip install -e {CLIO_CORE_DIR}")
        _log_action(log, "clio-core", "pip", "deferred", "WAIT",
                    error_code=E_USER_DEFERRED)
        stats["deferred"] += 1

    print()
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# Steg 4 — .env + sammanfattning
# ══════════════════════════════════════════════════════════════════════════════

def step4_summary(log: dict, args: argparse.Namespace,
                  s1: dict, s2: dict, s3: dict,
                  disk_used_mb: float = 0.0) -> None:
    """Kontrollerar .env, skriver sammanfattning."""
    print("Steg 4/4: Miljövariabler & sammanfattning")
    print()

    # .env-kontroll
    if _check_api_key():
        print("  ✅  ANTHROPIC_API_KEY — satt")
    else:
        print("  ⚠️   ANTHROPIC_API_KEY — saknas eller tom")
        if not ENV_FILE.exists():
            if not args.dry_run:
                _ensure_env_stub(dry_run=args.dry_run)
            print(f"       .env skapad: {ENV_FILE}")
            print(f"       Fyll i: ANTHROPIC_API_KEY=sk-ant-...")
        else:
            print(f"       Öppna {ENV_FILE} och fyll i ANTHROPIC_API_KEY=")
        _log_action(log, "ANTHROPIC_API_KEY", "env", "stub_created", "WAIT",
                    error_code=E_USER_DEFERRED)

    print()

    # Räkna totaler
    total_ok         = s1["ok"]         + s2["ok"]         + s3["ok"]
    total_installed  = s1["installed"]  + s2["installed"]  + s3["installed"]
    total_deferred   = s1["deferred"]   + s2["deferred"]   + s3["deferred"]
    total_failed     = s1["failed"]     + s2["failed"]     + s3["failed"]

    # pip-installationstid
    pip_elapsed = s2.get("elapsed_s", 0.0)

    print("  " + "─" * 48)
    print(f"  Redan installerat:  {total_ok}")
    print(f"  Nyinstallerat:      {total_installed}")
    if total_deferred:
        print(f"  Uppskjutet:         {total_deferred}  ← kör install.py igen")
    if total_failed:
        print(f"  Misslyckades:       {total_failed}  ← se felmeddelanden ovan")

    # Disk + tid — visa bara om något faktiskt installerades
    if total_installed > 0 and not args.dry_run:
        print()
        if disk_used_mb >= 1024:
            disk_str = f"~{disk_used_mb / 1024:.1f} GB"
        elif disk_used_mb > 0:
            disk_str = f"~{disk_used_mb:.0f} MB"
        else:
            disk_str = "< 1 MB"
        print(f"  Diskåtgång:         {disk_str}")
        if pip_elapsed >= 60:
            tid_str = f"{pip_elapsed / 60:.0f} min {pip_elapsed % 60:.0f} s"
        else:
            tid_str = f"{pip_elapsed:.0f} s"
        print(f"  pip-installationstid: {tid_str}")

    print()
    print(f"  Installationslogg:  {LOG_FILE}")

    if total_failed == 0 and total_deferred == 0:
        print()
        print("  🎉  Alla beroenden är på plats. clio-tools är redo!")
    elif total_failed > 0:
        print()
        print("  ⚠️   Vissa installationer misslyckades — se loggen för detaljer.")
    else:
        print()
        print("  Kör install.py igen när uppskjutna beroenden är hanterade.")

    if args.dry_run:
        print()
        print("  (dry-run — inga faktiska ändringar gjordes)")

    print()


# ══════════════════════════════════════════════════════════════════════════════
# Venv-bootstrap
# ══════════════════════════════════════════════════════════════════════════════

def _bootstrap_venv(venv_path: Path, original_argv: list[str],
                    dry_run: bool = False) -> int:
    """
    Skapar en virtualenv och återstartar install.py inuti den.
    Alla pip-installationer går då till venv:en — inte till global Python.
    """
    import venv as _venv_mod

    print(f"  Venv-läge: {venv_path}")

    if venv_path.exists():
        print(f"  ℹ️   Venv finns redan — återanvänder")
    else:
        print(f"  Skapar venv...", end=" ", flush=True)
        if not dry_run:
            _venv_mod.create(str(venv_path), with_pip=True, clear=False)
        print("✅")  # skrivs ut INNAN subprocess startar

    # Hitta venv:ens Python-executable
    if platform.system() == "Windows":
        venv_python = venv_path / "Scripts" / "python.exe"
    else:
        venv_python = venv_path / "bin" / "python"

    if not venv_python.exists() and not dry_run:
        print(f"  ❌  Python hittades inte i venv: {venv_python}")
        return 1

    print(f"  Python: {venv_python}")
    print()

    if dry_run:
        print(f"  (dry-run) Hade återstartat med venv:ens Python.")
        return 0

    # Bygg ny argv: ta bort --venv + ev. explicit sökväg, lägg till --_venv-active
    # OBS: hoppa bara nästa arg om det är en sökväg (inte en flagga som börjar med -)
    new_argv: list[str] = []
    i = 0
    while i < len(original_argv):
        arg = original_argv[i]
        if arg == "--venv":
            # Hoppa ev. explicit sökväg (nästa arg som inte börjar med -)
            if i + 1 < len(original_argv) and not original_argv[i + 1].startswith("-"):
                i += 1  # hoppa sökvägen
        elif arg.startswith("--venv="):
            pass  # hoppa hela --venv=PATH
        else:
            new_argv.append(arg)
        i += 1
    new_argv.append("--_venv-active")

    result = subprocess.run(
        [str(venv_python), "-X", "utf8", str(Path(__file__).resolve())] + new_argv
    )
    return result.returncode


# ══════════════════════════════════════════════════════════════════════════════
# Huvud
# ══════════════════════════════════════════════════════════════════════════════

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ClioTools Installer v" + VERSION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Auto-bekräfta alla installationer (agent-läge, hoppar ej över stora downloads)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Visa vad som skulle göras utan att installera något",
    )
    parser.add_argument(
        "--venv",
        nargs="?",
        const=str(INSTALLER_DIR / ".venv"),
        default=None,
        metavar="PATH",
        help=(
            "Kör installationen i en virtuell miljö — skapar om den saknas. "
            f"Standard: {INSTALLER_DIR / '.venv'}"
        ),
    )
    parser.add_argument(
        "--_venv-active",
        action="store_true",
        dest="venv_active",
        help=argparse.SUPPRESS,   # Intern flagga — sätts automatiskt av --venv
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Kör check_all.py som regressionstest efter installation",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # Säkerställ UTF-8 på Windows cp1252-konsoler
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, Exception):
        pass

    # ── Venv-bootstrap ────────────────────────────────────────────────────────
    # Om --venv är satt och vi INTE redan är inne i rätt venv:
    # skapa venv och återstarta install.py med venv:ens Python.
    if args.venv and not args.venv_active:
        print()
        print("  " + "═" * 44)
        print(f"    ClioTools Installer v{VERSION} — venv-läge")
        if args.dry_run:
            print("    [DRY-RUN — inga ändringar görs]")
        print("  " + "═" * 44)
        print()
        return _bootstrap_venv(Path(args.venv), sys.argv[1:], dry_run=args.dry_run)

    # Banner
    print()
    print("  " + "═" * 44)
    print(f"    ClioTools Installer v{VERSION}")
    if args.dry_run:
        print("    [DRY-RUN — inga ändringar görs]")
    if args.venv_active:
        print(f"    [VENV: {Path(sys.executable).parent.parent}]")
    print("  " + "═" * 44)
    print(f"  Repo:    {ROOT}")
    print(f"  Python:  {sys.executable}")
    print(f"  Maskin:  {platform.node()}")
    print()

    if platform.system() != "Windows":
        print("  ⚠️  install.py är optimerat för Windows.")
        print("      Vissa funktioner (winget, PATH via registry) fungerar inte på andra OS.")
        print()

    log = _init_log()
    if args.venv_active:
        log["venv"] = str(Path(sys.executable).parent.parent)

    # ── Förhandsvisning (wizard) ───────────────────────────────────────────────
    if not preflight_wizard(args):
        print("  Avbrutet.")
        return 0

    # ── Mät ledigt diskutrymme INNAN installation ─────────────────────────────
    try:
        _disk_free_before = shutil.disk_usage(ROOT).free
    except Exception:
        _disk_free_before = 0

    # Steg 1–4
    s1 = step1_system(log, args)

    # Kontrollera blockerande systemprogram
    blocking_missing = [
        t for t in SYSTEM_TOOLS
        if t.get("blocking") and t["id"] != "python" and not shutil.which(t["cmd"])
    ]
    if blocking_missing and not args.dry_run:
        names = ", ".join(t["name"] for t in blocking_missing)
        print(f"  ⛔  Blockerande beroenden saknas: {names}")
        print("      Installera dem och kör install.py igen.\n")
        _save_log(log)
        return 1

    s2 = step2_pip(log, args)
    s3 = step3_clio_core(log, args)

    # ── Mät diskdelta ─────────────────────────────────────────────────────────
    try:
        _disk_free_after = shutil.disk_usage(ROOT).free
        disk_used_mb = max(0.0, (_disk_free_before - _disk_free_after) / (1024 * 1024))
    except Exception:
        disk_used_mb = 0.0

    step4_summary(log, args, s1, s2, s3, disk_used_mb=disk_used_mb)

    _save_log(log)

    # ── Regressionstest ───────────────────────────────────────────────────────
    if args.check and not args.dry_run:
        check_all = ROOT / "check_all.py"
        print("  " + "─" * 44)
        print("  Regressionstest — check_all.py")
        print()
        if not check_all.exists():
            print(f"  ⚠️   {check_all} saknas — hoppar över test")
        else:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(check_all)]
            )
            print()
            if result.returncode == 0:
                print("  ✅  Regressionstest: GRÖN — alla moduler OK")
            else:
                print("  ❌  Regressionstest: RÖD — se felmeddelanden ovan")
                return 1
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
