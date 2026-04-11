"""
check_all.py — Beroendeöversikt för hela clio-tools
Kör: python check_all.py

Anropar check_deps.py i varje delprogram och rapporterar status.
Delprogram utan check_deps.py markeras som ej migrerade.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent

MODULES = [
    "clio-agent-mail",
    "clio-vision",
    "clio-docs",
    "clio-transcribe",
    "clio-narrate",
    "clio-audio-edit",
    "clio-library",
    "clio-research",
    "clio-fetch",
    "clio-emailfetch",
]


def run() -> bool:
    results = {}

    for module in MODULES:
        check_file = ROOT / module / "check_deps.py"
        if not check_file.exists():
            results[module] = ("⚠️ ", "check_deps.py saknas — ej migrerad ännu")
            continue

        spec = importlib.util.spec_from_file_location("check_deps", check_file)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            ok = mod.check(verbose=False)
            if ok:
                results[module] = ("✅", "OK")
            else:
                results[module] = ("❌", "Beroenden saknas — kör: python check_deps.py")
        except Exception as e:
            results[module] = ("❌", f"Fel vid körning: {e}")

    print("\nclio-tools — Beroendeöversikt")
    print("=" * 52)
    all_ok = True
    for module, (icon, msg) in results.items():
        print(f"  {icon}  {module:<22}  {msg}")
        if icon == "❌":
            all_ok = False
    print()

    if not all_ok:
        print("Kör  python check_deps.py  i respektive mapp för detaljer.\n")

    return all_ok


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
