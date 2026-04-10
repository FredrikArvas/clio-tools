"""
check_deps.py — Beroendecheck för clio-powershell
Kör: python check_deps.py

clio-powershell är en konfigurationsguide (inga Python-scripts).
Kontrollerar att PowerShell finns tillgängligt på systemet.
"""

import shutil
import sys

MODULE_NAME = "clio-powershell"


def check(verbose: bool = True) -> bool:
    # Kolla pwsh (PowerShell 7+) eller powershell (Windows PowerShell 5)
    pwsh   = shutil.which("pwsh")
    ps5    = shutil.which("powershell")

    found = pwsh or ps5
    version_hint = "pwsh (7+)" if pwsh else "powershell (5.x)" if ps5 else None

    if not found:
        if verbose:
            print(f"\n[FEL] {MODULE_NAME} — PowerShell hittades inte i PATH")
            print(f"  PowerShell ingår i Windows 10/11 (sök: 'powershell' i Start)")
            print(f"  PowerShell 7+: winget install Microsoft.PowerShell")
        return False

    if verbose:
        print(f"[OK]  {MODULE_NAME} — {version_hint} tillgänglig")
    return True


if __name__ == "__main__":
    ok = check(verbose=True)
    sys.exit(0 if ok else 1)
