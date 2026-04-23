"""
clio_qc.py — Clio-tools kvalitetskontroll

Körs manuellt:      python clio_qc.py
Körs av pre-push:   python clio_qc.py --strict

Kontroll 1: Filstorlek    — .py-filer > 500 rader        (⚠️  varning)
Kontroll 2: TUI-mönster   — raw input() i runner-filer   (⚠️  varning)
Kontroll 3: Syntax        — py_compile på alla .py-filer (❌  alltid blockerande)
Kontroll 4: Beroenden     — requirements.txt installerade (⚠️  varning)
              Paket märkta med "# optional" i requirements.txt räknas
              som valfria och visas som info, inte varning.

Med --strict: ⚠️ varningar blir också blockerande (exit 1).
"""

from __future__ import annotations

import argparse
import py_compile
import re as _re_module
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# ── Färger ────────────────────────────────────────────────────────────────────
GRN = "\033[92m"
YEL = "\033[93m"
RED = "\033[91m"
BLD = "\033[1m"
NRM = "\033[0m"

OK   = f"{GRN}✅{NRM}"
WARN = f"{YEL}⚠️ {NRM}"
FAIL = f"{RED}❌{NRM}"

# ── Konfiguration ─────────────────────────────────────────────────────────────
MAX_LINES = 500

RUNNER_FILES = [
    "clio.py",
    "clio_runners.py",
    "clio_run_mail.py",
    "clio_run_research.py",
    "clio_run_obit.py",
    "clio_run_privfin.py",
]

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".githooks"}


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def all_py_files() -> list[Path]:
    result = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        result.append(path)
    return result


# ── Kontroller ────────────────────────────────────────────────────────────────

def check_file_sizes(files: list[Path]) -> list[tuple[Path, int]]:
    print(f"\n{BLD}1. Filstorlek (gräns: {MAX_LINES} rader){NRM}")
    violations: list[tuple[Path, int]] = []
    for path in files:
        lines = len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        if lines > MAX_LINES:
            violations.append((path.relative_to(ROOT), lines))
    if not violations:
        print(f"  {OK} Alla filer under {MAX_LINES} rader")
    else:
        for rel, n in sorted(violations, key=lambda x: -x[1]):
            print(f"  {WARN} {rel}  ({n} rader)")
    return violations


_RAW_INPUT_RE = _re_module.compile(r"(?<![_\w])input\s*\(")


def check_raw_input() -> list[tuple[str, list[tuple[int, str]]]]:
    """Flaggar raw input()-anrop i runner-filer.
    _input() (vår wrapper) och def _input räknas ej.
    """
    print(f"\n{BLD}2. TUI-mönster (raw input() i runners){NRM}")
    violations: list[tuple[str, list[tuple[int, str]]]] = []
    for name in RUNNER_FILES:
        path = ROOT / name
        if not path.exists():
            continue
        hits: list[tuple[int, str]] = []
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or "def _input" in s:
                continue
            if _RAW_INPUT_RE.search(s):
                hits.append((i, line.rstrip()))
        if hits:
            violations.append((name, hits))
            for lineno, text in hits:
                print(f"  {WARN} {name}:{lineno}  {text.strip()}")
    if not violations:
        print(f"  {OK} Inga raw input()-anrop i runner-filer")
    return violations


def check_syntax(files: list[Path]) -> list[tuple[Path, str]]:
    print(f"\n{BLD}3. Syntax{NRM}")
    errors: list[tuple[Path, str]] = []
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append((path.relative_to(ROOT), str(e)))
            print(f"  {FAIL} {path.relative_to(ROOT)}: {e}")
    if not errors:
        print(f"  {OK} Syntax OK ({len(files)} filer)")
    return errors


# ── Check 4: Paketberoenden ───────────────────────────────────────────────────

def _parse_requirements(path: Path) -> list[tuple[str, bool]]:
    """Returnerar lista av (paketnamn, optional) från requirements.txt.

    Regler:
    - Rader som börjar med # hoppas över.
    - Versionskrav (>=, ==, ~= osv.) och extras ([security]) trimmas.
    - Rad med "# optional" (skiftlägesokänsligt) sätter optional=True.
    - Helt kommenterade rader (# paket) hoppas över.
    """
    result: list[tuple[str, bool]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Kolla optional-flagga i inline-kommentar
        optional = bool(_re_module.search(r"#\s*optional", line, _re_module.IGNORECASE))
        # Ta bort inline-kommentar
        code_part = line.split("#")[0].strip()
        if not code_part:
            continue
        # Ta bort extras [foo] och versionsspecifikationer
        name = _re_module.split(r"[><=!~\s\[;]", code_part)[0].strip()
        if name:
            result.append((name, optional))
    return result


def check_dependencies() -> list[str]:
    """Kontrollerar att alla paket i requirements.txt är installerade."""
    print(f"\n{BLD}4. Paketberoenden (requirements.txt){NRM}")

    try:
        from importlib.metadata import version, PackageNotFoundError
    except ImportError:
        print(f"  {WARN} importlib.metadata saknas (Python < 3.8) — hoppar över")
        return []

    req_file = ROOT / "requirements.txt"
    if not req_file.exists():
        print(f"  {WARN} requirements.txt saknas")
        return []

    packages = _parse_requirements(req_file)
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for pkg, optional in packages:
        try:
            version(pkg)
        except PackageNotFoundError:
            if optional:
                missing_optional.append(pkg)
            else:
                missing_required.append(pkg)

    for pkg in missing_required:
        print(f"  {WARN} {pkg} — saknas (krävs)")
    for pkg in missing_optional:
        print(f"       {pkg} — saknas (valfritt, OK)")

    total = len(packages)
    n_ok  = total - len(missing_required) - len(missing_optional)

    if not missing_required and not missing_optional:
        print(f"  {OK} Alla {total} paket installerade")
    elif not missing_required:
        print(f"  {OK} {n_ok}/{total} installerade ({len(missing_optional)} valfria saknas)")

    return missing_required


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Säkerställ UTF-8 output i Windows-terminaler
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="clio-tools QC")
    parser.add_argument("--strict", action="store_true",
                        help="Varningar (⚠️) blir också blockerande — exit 1")
    args = parser.parse_args()

    print(f"\n{BLD}{'═' * 56}{NRM}")
    print(f"{BLD}  clio-tools QC{NRM}")
    print(f"{BLD}{'═' * 56}{NRM}")

    files = all_py_files()
    size_violations   = check_file_sizes(files)
    input_violations  = check_raw_input()
    syntax_errors     = check_syntax(files)
    missing_packages  = check_dependencies()

    print(f"\n{BLD}{'═' * 56}{NRM}")
    has_errors   = bool(syntax_errors)
    has_warnings = bool(size_violations or input_violations or missing_packages)

    if not has_errors and not has_warnings:
        print(f"  {OK} Allt OK\n")
        sys.exit(0)

    if has_errors:
        n = len(syntax_errors)
        print(f"  {FAIL} {n} syntaxfel — åtgärda innan push\n")
        sys.exit(1)

    # Bara varningar
    n = len(size_violations) + len(input_violations) + len(missing_packages)
    print(f"  {WARN} {n} varning(ar)")
    if args.strict:
        print(f"  {FAIL} --strict aktiv — push blockerad\n")
        sys.exit(1)
    print(f"  Kör med --strict för att blockera push vid varningar\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
