#!/usr/bin/env python3
"""
uninstall.py — ClioTools Uninstaller v1.0

Avinstallerar exakt det som install.py loggade i install_log.json.
Inget mer, inget mindre.

Körning:
    python clio-install/uninstall.py   (från clio-tools-roten)
    python uninstall.py                (från clio-install/)

Flaggor:
    --yes, -y    Auto-bekräfta avinstallation (agent-läge)
    --dry-run    Visa vad som skulle göras utan att ångra något
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import winreg
    _HAS_WINREG = True
except ImportError:
    _HAS_WINREG = False

# ── Sökvägar ──────────────────────────────────────────────────────────────────
VERSION       = "1.0"
INSTALLER_DIR = Path(__file__).resolve().parent
LOG_FILE      = INSTALLER_DIR / "install_log.json"
ARCHIVE_FILE  = INSTALLER_DIR / "install_log_archive.json"


# ══════════════════════════════════════════════════════════════════════════════
# Hjälpare
# ══════════════════════════════════════════════════════════════════════════════

def _ask(prompt: str, default: str = "N", auto_yes: bool = False) -> str:
    """Frågar användaren. Returnerar 'j' eller 'n'."""
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
        print("  Ange j (ja) eller n (nej)")


def _load_log() -> dict | None:
    """Läser install_log.json. Returnerar None om filen saknas."""
    if not LOG_FILE.exists():
        return None
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [FEL] Kunde inte läsa {LOG_FILE}: {e}")
        return None


def _pip_uninstall(pkg_spec: str, dry_run: bool = False) -> tuple[bool, str]:
    """
    Avinstallerar ett pip-paket.
    pkg_spec kan vara 'anthropic==0.89.0' eller 'clio-core @ /path'.
    Returnerar (success, error_msg).
    """
    # Extrahera paketnamn (ignorera version och @ path)
    pkg_name = pkg_spec.split("==")[0].split(" @ ")[0].strip()
    if not pkg_name:
        return False, "tomt paketnamn"
    if dry_run:
        return True, ""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", pkg_name, "--yes", "--quiet"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True, ""
    # pip returnerar 1 om paketet inte är installerat — behandla som OK
    if "not installed" in result.stdout.lower() or "not installed" in result.stderr.lower():
        return True, ""
    return False, result.stderr.strip()


def _remove_from_user_path(remove_path: str, dry_run: bool = False) -> tuple[bool, str]:
    """
    Tar bort en sökväg ur user-PATH via Windows Registry.
    Returnerar (success, error_msg).
    """
    if not _HAS_WINREG:
        return False, "winreg ej tillgängligt (ej Windows)"
    if dry_run:
        return True, ""
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
            winreg.CloseKey(key)
            return True, ""  # PATH finns inte — ingenting att ta bort

        # Ta bort exakt sökväg (case-insensitive)
        parts = [p for p in current.split(";") if p.lower() != remove_path.lower()]
        new_value = ";".join(parts)
        winreg.SetValueEx(key, "PATH", 0, reg_type, new_value)
        winreg.CloseKey(key)

        # Notifiera Windows
        try:
            import ctypes
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None
            )
        except Exception:
            pass

        return True, ""
    except PermissionError:
        return False, "behörighet nekad"
    except Exception as e:
        return False, str(e)


def _archive_log(dry_run: bool = False) -> None:
    """Arkiverar install_log.json → install_log_archive.json."""
    if dry_run:
        return
    if LOG_FILE.exists():
        LOG_FILE.rename(ARCHIVE_FILE)


# ══════════════════════════════════════════════════════════════════════════════
# Huvud
# ══════════════════════════════════════════════════════════════════════════════

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ClioTools Uninstaller v" + VERSION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Auto-bekräfta avinstallation (agent-läge)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Visa vad som skulle göras utan att ångra något",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # UTF-8 på Windows cp1252-konsoler
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, Exception):
        pass

    # Banner
    print()
    print("  " + "═" * 44)
    print(f"    ClioTools Uninstaller v{VERSION}")
    if args.dry_run:
        print("    [DRY-RUN — inga ändringar görs]")
    print("  " + "═" * 44)
    print()

    # ── Läs loggen ────────────────────────────────────────────────────────────
    log = _load_log()
    if log is None:
        print(f"  [FEL] {LOG_FILE} saknas eller är oläsbar.")
        print(f"  Avinstallation utan logg är inte möjlig — det är en funktion, inte en bugg.")
        print()
        return 1

    install_date = log.get("install_date", "okänt datum")
    machine      = log.get("machine", "okänd maskin")
    pip_list     = log.get("pip_installed", [])
    path_list    = log.get("path_changes", [])
    actions      = log.get("actions", [])

    print(f"  Installationslogg: {LOG_FILE}")
    print(f"  Installationsdatum: {install_date}  |  Maskin: {machine}")
    print()

    # ── Sammanfatta vad som installerades ─────────────────────────────────────
    pip_to_remove   = list(pip_list)   # kopia
    path_to_remove  = list(path_list)

    # Systemprogram installerade via winget (kan inte avinstalleras automatiskt)
    winget_installed = [
        a for a in actions
        if a.get("type") == "system" and a.get("action") == "installed"
        and a.get("status") == "OK"
    ]

    if not pip_to_remove and not path_to_remove and not winget_installed:
        print("  Loggen är tom — ingenting att avinstallera.")
        print()
        return 0

    print("  Följande installerades av ClioTools Installer:")
    print()

    if pip_to_remove:
        print("  pip-paket:")
        for p in pip_to_remove:
            print(f"    - {p}")
        print()

    if path_to_remove:
        print("  PATH-tillägg (user-PATH):")
        for p in path_to_remove:
            print(f"    - {p}")
        print()

    if winget_installed:
        print("  Systemprogram (installerade via winget — avinstalleras EJ automatiskt):")
        for a in winget_installed:
            print(f"    - {a.get('component', '?')}  →  avinstallera manuellt via winget")
        print()

    # ── Bekräftelse ───────────────────────────────────────────────────────────
    ans = _ask("  Vill du avinstallera pip-paket och PATH-tillägg ovan? [j/N]: ",
               default="N", auto_yes=args.yes)

    if ans != "j":
        print()
        print("  Avinstallation avbruten.")
        print()
        return 0

    print()
    stats = dict(ok=0, failed=0, skipped=0)

    # ── Avinstallera pip-paket ────────────────────────────────────────────────
    if pip_to_remove:
        print("  Avinstallerar pip-paket...")
        for pkg_spec in pip_to_remove:
            pkg_name = pkg_spec.split("==")[0].split(" @ ")[0].strip()

            # Varna om paketet kan användas av andra program
            common_pkgs = {"requests", "Pillow", "pillow", "anthropic", "python-dotenv"}
            if pkg_name in common_pkgs:
                print(f"  ⚠️   {pkg_name} — används möjligen av andra program")

            ok, err = _pip_uninstall(pkg_spec, dry_run=args.dry_run)
            if ok:
                print(f"  ✅  pip uninstall {pkg_name} — OK")
                stats["ok"] += 1
            else:
                print(f"  ❌  pip uninstall {pkg_name} — {err}")
                stats["failed"] += 1
        print()

    # ── Ta bort PATH-tillägg ─────────────────────────────────────────────────
    if path_to_remove:
        print("  Återställer PATH...")
        for path_entry in path_to_remove:
            ok, err = _remove_from_user_path(path_entry, dry_run=args.dry_run)
            if ok:
                print(f"  ✅  PATH-tillägg borttaget — kräver ny terminal")
                stats["ok"] += 1
            else:
                print(f"  ❌  Kunde inte ta bort från PATH: {err}")
                stats["failed"] += 1
        print()

    # ── Systemprogram — manuell instruktion ───────────────────────────────────
    if winget_installed:
        print("  Systemprogram — avinstallera manuellt vid behov:")
        winget_remove_cmds = {
            "git":       "winget uninstall Git.Git",
            "ollama":    "winget uninstall Ollama.Ollama",
            "tesseract": "winget uninstall UB-Mannheim.TesseractOCR",
            "digikam":   "winget uninstall KDE.digiKam",
        }
        for a in winget_installed:
            tid = a.get("component", "")
            cmd = winget_remove_cmds.get(tid, f"winget uninstall <{tid}>")
            print(f"    {tid}:  {cmd}")
        print()

    # ── Arkivera loggen ───────────────────────────────────────────────────────
    _archive_log(dry_run=args.dry_run)
    if not args.dry_run:
        print(f"  Installationslogg arkiverad: {ARCHIVE_FILE}")
    else:
        print(f"  (dry-run) Loggen hade arkiverats som: {ARCHIVE_FILE}")

    # ── Sammanfattning ────────────────────────────────────────────────────────
    print()
    if stats["failed"] == 0:
        print("  ✅  Avinstallation klar.")
    else:
        print(f"  ⚠️   Klart med {stats['failed']} fel — se meddelanden ovan.")
    print()

    if args.dry_run:
        print("  (dry-run — inga faktiska ändringar gjordes)")
        print()

    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
