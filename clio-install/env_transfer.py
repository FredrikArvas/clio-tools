#!/usr/bin/env python3
"""
env_transfer.py — Exportera och importera .env och clio.config

Samlar alla .env- och clio.config-filer i repot, krypterar dem
i en zip-fil med AES-256 (pyzipper) eller ZipCrypto (stdlib fallback).
Filen kopieras manuellt till målmaskinen och importeras där.

Körning:
    python clio-install/env_transfer.py --export           (sparar på Skrivbordet)
    python clio-install/env_transfer.py --export --out C:\\temp\\transfer.zip
    python clio-install/env_transfer.py --import transfer.zip
"""

from __future__ import annotations

import argparse
import getpass
import io
import os
import sys
from pathlib import Path

# ── Sökvägar ──────────────────────────────────────────────────────────────────
INSTALLER_DIR = Path(__file__).resolve().parent
ROOT          = INSTALLER_DIR.parent

# Filer att exportera (relativa sökvägar från repo-roten, ej mallar)
EXPORT_PATTERNS = [".env", "clio.config"]
SKIP_PATTERNS   = [".env.example", ".env.sample", ".env.template"]


# ══════════════════════════════════════════════════════════════════════════════
# Krypteringsbackend — pyzipper (AES-256) med fallback till stdlib (ZipCrypto)
# ══════════════════════════════════════════════════════════════════════════════

def _get_backend():
    """Returnerar ('pyzipper', modul) eller ('zipfile', modul)."""
    try:
        import pyzipper
        return "pyzipper", pyzipper
    except ImportError:
        import zipfile
        return "zipfile", zipfile


def _write_encrypted_zip(out_path: Path, files: list[tuple[Path, str]],
                          password: str, backend: str, mod) -> None:
    """
    Skriver ett krypterat zip-arkiv.
    files: lista av (absolut sökväg, arkivsökväg)
    """
    pwd = password.encode("utf-8")

    if backend == "pyzipper":
        with mod.AESZipFile(out_path, "w",
                            compression=mod.ZIP_DEFLATED,
                            encryption=mod.WZ_AES) as zf:
            zf.setpassword(pwd)
            for abs_path, arc_name in files:
                zf.write(abs_path, arc_name)
    else:
        # stdlib zipfile — ZipCrypto (svagare, men fungerar utan extra beroenden)
        import zipfile as _zf
        with _zf.ZipFile(out_path, "w", compression=_zf.ZIP_DEFLATED) as zf:
            zf.setpassword(pwd)
            for abs_path, arc_name in files:
                # stdlib kräver att man krypterar varje fil explicit
                data = abs_path.read_bytes()
                info = _zf.ZipInfo(arc_name)
                info.compress_type = _zf.ZIP_DEFLATED
                zf.writestr(info, data)


def _read_encrypted_zip(zip_path: Path, password: str,
                         backend: str, mod) -> dict[str, bytes]:
    """Läser ett krypterat zip-arkiv. Returnerar {arc_name: data}."""
    pwd = password.encode("utf-8")
    result: dict[str, bytes] = {}

    if backend == "pyzipper":
        with mod.AESZipFile(zip_path, "r") as zf:
            zf.setpassword(pwd)
            for name in zf.namelist():
                result[name] = zf.read(name)
    else:
        import zipfile as _zf
        with _zf.ZipFile(zip_path, "r") as zf:
            zf.setpassword(pwd)
            for name in zf.namelist():
                result[name] = zf.read(name)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Skanning
# ══════════════════════════════════════════════════════════════════════════════

def _find_env_files() -> list[tuple[Path, str]]:
    """
    Letar igenom repot efter .env och clio.config.
    Returnerar lista av (absolut sökväg, relativ arkivsökväg).
    Hoppar över .env.example och liknande mallar.
    """
    found: list[tuple[Path, str]] = []
    skip_dirs = {".git", ".venv", "venv", "venv-ollama", "__pycache__",
                 "node_modules", ".pytest_cache"}

    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Skippa onödiga kataloger
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]

        for fname in filenames:
            if fname in SKIP_PATTERNS:
                continue
            if fname in EXPORT_PATTERNS:
                abs_path = Path(dirpath) / fname
                arc_name = str(abs_path.relative_to(ROOT)).replace("\\", "/")
                found.append((abs_path, arc_name))

    return sorted(found, key=lambda x: x[1])


# ══════════════════════════════════════════════════════════════════════════════
# Export
# ══════════════════════════════════════════════════════════════════════════════

def cmd_export(args: argparse.Namespace) -> int:
    backend, mod = _get_backend()

    # Standardsökväg: Skrivbordet
    if args.out:
        out_path = Path(args.out)
    else:
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path.home()
        out_path = desktop / "clio-env-transfer.zip"

    files = _find_env_files()

    if not files:
        print("[INFO]  Inga .env- eller clio.config-filer hittades.")
        return 0

    print()
    print("  Följande filer kommer att exporteras:")
    print()
    for _, arc_name in files:
        print(f"    {arc_name}")
    print()

    if backend == "pyzipper":
        print("  Kryptering: AES-256 (pyzipper)")
    else:
        print("  Kryptering: ZipCrypto (stdlib — svagare)")
        print("  Tips: pip install pyzipper  ger AES-256")
    print()

    # Lösenord
    pwd = getpass.getpass("  Lösenord: ")
    if not pwd:
        print("  [FEL]  Tomt lösenord — avbryter.")
        return 1
    pwd2 = getpass.getpass("  Bekräfta: ")
    if pwd != pwd2:
        print("  [FEL]  Lösenorden matchar inte — avbryter.")
        return 1

    print()
    print(f"  Sparar till: {out_path}")

    try:
        _write_encrypted_zip(out_path, files, pwd, backend, mod)
    except Exception as e:
        print(f"  [FEL]  Kunde inte skriva zip: {e}")
        return 1

    size_kb = out_path.stat().st_size // 1024
    print(f"  ✅  {len(files)} filer exporterade ({size_kb} KB)")
    print()
    print("  Kopiera filen manuellt till målmaskinen, kör sedan:")
    print(f"    python clio-install/env_transfer.py --import {out_path.name}")
    print()
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Import
# ══════════════════════════════════════════════════════════════════════════════

def cmd_import(args: argparse.Namespace) -> int:
    backend, mod = _get_backend()
    zip_path = Path(args.import_file)

    if not zip_path.exists():
        print(f"  [FEL]  Filen hittades inte: {zip_path}")
        return 1

    print()
    pwd = getpass.getpass("  Lösenord: ")

    try:
        files = _read_encrypted_zip(zip_path, pwd, backend, mod)
    except Exception as e:
        print(f"  [FEL]  Kunde inte läsa zip (fel lösenord?): {e}")
        return 1

    if not files:
        print("  [INFO]  Zip-arkivet är tomt.")
        return 0

    print()
    print(f"  Innehåll ({len(files)} filer):")
    for arc_name in sorted(files):
        target = ROOT / arc_name
        status = "skriver över" if target.exists() else "ny"
        print(f"    {arc_name}  [{status}]")
    print()

    ans = input("  Importera alla? [j/N]: ").strip().lower()
    if ans != "j":
        print("  Avbruten.")
        return 0

    restored = 0
    for arc_name, data in files.items():
        target = ROOT / arc_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        restored += 1

    print(f"  ✅  {restored} filer återställda till {ROOT}")
    print()
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exportera/importera .env och clio.config krypterat",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--export",
        action="store_true",
        help="Exportera alla .env och clio.config till krypterat zip",
    )
    group.add_argument(
        "--import",
        dest="import_file",
        metavar="FIL",
        help="Importera från krypterat zip till repot",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="Sökväg för exportfilen (standard: Skrivbordet/clio-env-transfer.zip)",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, Exception):
        pass

    args = parse_args(argv)

    if args.export:
        return cmd_export(args)
    else:
        return cmd_import(args)


if __name__ == "__main__":
    sys.exit(main())
