"""
clio_run_job.py
Custom launcher för clio-agent-job — jobbsökar- och förändringssignalagent.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent

from clio_menu import (
    BackToMenu, _input,
    GRN, YEL, GRY, BLD, NRM,
    clear,
    menu_select, menu_confirm, menu_text, menu_pause,
)

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key


# ── Launcher ──────────────────────────────────────────────────────────────────

def _list_profiles(job_root: Path) -> list[Path]:
    """Returnerar alla .yaml-profiler i profiles/-mappen."""
    profiles_dir = job_root / "profiles"
    return sorted(p for p in profiles_dir.glob("*.yaml") if p.stem != "profile_loader")


def _pick_profile(job_root: Path) -> str | None:
    """Visar profilväljare och returnerar sökväg som sträng, eller None."""
    profiles = _list_profiles(job_root)
    if not profiles:
        print("  Inga profiler hittades i profiles/")
        return None
    if len(profiles) == 1:
        return str(profiles[0])
    choices = [f"{i+1}.  {p.stem}" for i, p in enumerate(profiles)]
    choices.append(f"{len(profiles)+1}.  Alla profiler (kör en i taget)")
    picked = menu_select("  Välj profil:", choices)
    if picked is None:
        return None
    idx = int(picked.split(".")[0]) - 1
    if idx == len(profiles):
        return "ALL"
    return str(profiles[idx])


def run_job(tool: dict, state: dict) -> None:
    """Custom launcher för clio-agent-job."""
    job_root = ROOT / "clio-agent-job"

    _CHOICES = [
        "1.  Kor bevakning        (dry-run, skickar inget)",
        "2.  Kor bevakning        (skarpt lage, skickar mail)",
        "3.  Kor med verbost lage (dry-run, visa alla artiklar)",
        "4.  Visa senaste korning",
        "5.  Kontrollera beroenden",
    ]

    while True:
        clear()
        print(f"\n{BLD}  clio-agent-job  --  Jobbsokning & Forandringssignaler{NRM}")
        print(f"{'=' * 56}\n")
        choice = menu_select("Valj:", _CHOICES)
        if choice is None:
            return
        mode = choice.split(".")[0].strip()

        print(f"\n{'=' * 40}")
        start = datetime.now()

        try:
            if mode == "1":
                profile = _pick_profile(job_root)
                if profile is None:
                    continue
                profiles_to_run = _list_profiles(job_root) if profile == "ALL" else [Path(profile)]
                for p in profiles_to_run:
                    print(f"Startar dry-run: {p.stem}...")
                    subprocess.run(
                        [sys.executable, str(job_root / "run.py"), "--dry-run",
                         "--profile", str(p)],
                        text=True, errors="replace")

            elif mode == "2":
                if not menu_confirm(
                    "  Vill du kora i skarpt lage? (mail skickas till kandidaten)",
                    default=False
                ):
                    continue
                profile = _pick_profile(job_root)
                if profile is None:
                    continue
                profiles_to_run = _list_profiles(job_root) if profile == "ALL" else [Path(profile)]
                for p in profiles_to_run:
                    print(f"Startar skarp korning: {p.stem}...")
                    subprocess.run(
                        [sys.executable, str(job_root / "run.py"),
                         "--profile", str(p)],
                        text=True, errors="replace")

            elif mode == "3":
                profile = _pick_profile(job_root)
                if profile is None:
                    continue
                p_path = _list_profiles(job_root)[0] if profile == "ALL" else Path(profile)
                print(f"Startar verbose dry-run: {p_path.stem}...")
                subprocess.run(
                    [sys.executable, str(job_root / "run.py"), "--dry-run", "--verbose",
                     "--profile", str(p_path)],
                    text=True, errors="replace")

            elif mode == "4":
                subprocess.run(
                    [sys.executable, str(job_root / "run.py"), "--last-run"],
                    text=True, errors="replace")

            elif mode == "5":
                print("Kontrollerar beroenden...")
                subprocess.run(
                    [sys.executable, str(job_root / "check_deps.py")],
                    text=True, errors="replace")

        except KeyboardInterrupt:
            print("\n(Avbruten av användaren)")
        except Exception as e:
            print(f"\nFel: {e}")

        elapsed = (datetime.now() - start).seconds
        print(f"\n{'─' * 40}")
        print(t("run_done", s=elapsed))
        menu_pause()
