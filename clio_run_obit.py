"""
clio_run_obit.py
Launcher för clio-agent-obit — dödsannonsbevakning.
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
    save_state, clear,
    menu_select, menu_confirm, menu_text, menu_pause,
)

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key


# ── Launcher ──────────────────────────────────────────────────────────────────

def run_obit(tool: dict, state: dict) -> None:
    """Custom launcher för clio-agent-obit."""
    obit_root = ROOT / "clio-agent-obit"

    _CHOICES = [
        "1.  Kör bevakning        (dry-run, skickar inget)",
        "2.  Kör bevakning        (skarpt läge, skickar mail)",
        "3.  Kontrollera beroenden",
        "4.  Importera GEDCOM     (→ watchlist)",
        "5.  Importera adressbok  (→ watchlist)",
        "6.  Sondera ny källa     (discover.py probe)",
        "7.  Bjud in bevakare     (skicka mall via mail)",
        "8.  Visa bevakningslista (sammanfattning)",
        "9.  Exportera bevakningslista (CSV)",
        "10. Visa relationsgraf   (HTML i webbläsaren)",
    ]

    while True:
        clear()
        print(f"\n{BLD}  clio-agent-obit  —  Dödsannonsbevakning{NRM}")
        print(f"{'─' * 56}\n")
        choice = menu_select("Välj:", _CHOICES)
        if choice is None:
            return
        mode = choice.split(".")[0].strip()

        print(f"\n{'─' * 40}")
        start = datetime.now()

        try:
            if mode == "1":
                print("Startar clio-agent-obit (dry-run)...")
                subprocess.run(
                    [sys.executable, str(obit_root / "run.py"), "--dry-run"],
                    text=True, errors="replace")

            elif mode == "2":
                print("Startar clio-agent-obit (skarpt)...")
                subprocess.run(
                    [sys.executable, str(obit_root / "run.py")],
                    text=True, errors="replace")

            elif mode == "3":
                print("Kontrollerar beroenden...")
                subprocess.run(
                    [sys.executable, str(obit_root / "check_deps.py")],
                    text=True, errors="replace")

            elif mode == "4":
                last_ged = state.get("obit_gedcom_path", "")
                ged = menu_text("  Sökväg till .ged-fil eller mapp", default=last_ged)
                if not ged:
                    continue
                ged = ged.strip('"')
                ged_path = Path(ged)
                if ged_path.is_dir():
                    state["obit_gedcom_path"] = str(ged_path)
                    save_state(state)
                    ged_files = sorted(ged_path.glob("*.ged"))
                    if not ged_files:
                        print("  Inga .ged-filer hittades i mappen.")
                        menu_pause()
                        continue
                    picked = menu_select("  Välj .ged-fil:", [f.name for f in ged_files])
                    if not picked:
                        continue
                    ged_path = ged_path / picked
                elif not ged_path.is_file():
                    print(f"  Filen hittades inte: {ged}")
                    menu_pause()
                    continue
                last_owner = state.get("obit_last_owner", "")
                owner = menu_text("  Bevakare (e-post)", default=last_owner) or last_owner
                if "@" not in owner:
                    print("  Ange en giltig e-postadress.")
                    menu_pause()
                    continue
                state["obit_last_owner"] = owner
                save_state(state)
                ego = menu_text(f"  Centralperson (lämna tomt = {owner})", default="") or ""
                depth_choice = menu_select("  Djupnivå:", [
                    "1 — Partner + föräldrar  (standard)",
                    "2 — + Syskon + mor/farföräldrar",
                    "3 — + Syskonbarn + föräldrars syskon",
                    "F — Alla levande i trädet (fullständig)",
                ]) or "1 — Partner + föräldrar  (standard)"
                depth_input = depth_choice[0].lower()
                dry = menu_confirm("  Dry-run?", default=True)
                cmd = [sys.executable, str(obit_root / "watchlist" / "import_gedcom.py"),
                       "--gedcom", str(ged_path), "--owner", owner]
                if ego:
                    cmd += ["--ego", ego]
                if depth_input == "f":
                    cmd.append("--full")
                else:
                    cmd += ["--depth", depth_input if depth_input in ("1", "2", "3") else "1"]
                if dry:
                    cmd.append("--dry-run")
                subprocess.run(cmd, text=True, errors="replace")

            elif mode == "5":
                contacts = menu_text("  Sökväg till adressbok-CSV")
                if not contacts:
                    continue
                owner = menu_text("  Bevakare (e-post)") or ""
                dry = menu_confirm("  Dry-run?", default=True)
                cmd = [sys.executable, str(obit_root / "watchlist" / "import_contacts.py"),
                       "--contacts", contacts.strip('"'), "--owner", owner]
                if dry:
                    cmd.append("--dry-run")
                subprocess.run(cmd, text=True, errors="replace")

            elif mode == "6":
                url = menu_text("  URL att sondera")
                if not url:
                    continue
                name_arg = menu_text("  Namn för ny källa (lämna tomt = lägg inte till)", default="") or ""
                cmd = [sys.executable, str(obit_root / "sources" / "discover.py"), "probe", url]
                if name_arg:
                    cmd += ["--add", name_arg]
                subprocess.run(cmd, text=True, errors="replace")

            elif mode == "7":
                to_name  = menu_text("  Mottagarens fullständiga namn") or ""
                to_email = menu_text("  Mottagarens e-post") or ""
                dry = menu_confirm("  Dry-run (förhandsgranska utan att skicka)?", default=True)
                cmd = [sys.executable,
                       str(obit_root / "watchlist" / "send_invitation.py"),
                       "--to-name", to_name, "--to-email", to_email]
                if dry:
                    cmd.append("--dry-run")
                subprocess.run(cmd, text=True, errors="replace")

            elif mode == "8":
                import csv as _csv
                wdir = obit_root / "watchlists"
                files = sorted(wdir.glob("*.csv"))
                if not files:
                    print("  Inga bevakningslistor hittades i watchlists/")
                else:
                    print()
                    for f in files:
                        owner = f.stem
                        rows_raw = []
                        with open(f, newline="", encoding="utf-8") as fh:
                            for line in fh:
                                if not line.lstrip().startswith("#"):
                                    rows_raw.append(line)
                        reader = list(_csv.DictReader(rows_raw))
                        viktig = [r for r in reader if r.get("prioritet", "").strip() == "viktig"]
                        normal = [r for r in reader if r.get("prioritet", "").strip() == "normal"]
                        bav    = [r for r in reader if r.get("prioritet", "").strip() == "bra_att_veta"]
                        print(f"  {BLD}{owner}{NRM}  ({len(reader)} poster)")
                        print(f"    viktig: {len(viktig)}  normal: {len(normal)}  bra_att_veta: {len(bav)}")
                        if viktig:
                            names = ", ".join(
                                f"{r.get('fornamn', '')} {r.get('efternamn', '')}".strip()
                                for r in viktig
                            )
                            print(f"    Viktiga: {names}")
                        print()

            elif mode == "9":
                import shutil as _shutil
                wdir = obit_root / "watchlists"
                files = sorted(wdir.glob("*.csv"))
                if not files:
                    print("  Inga bevakningslistor att exportera.")
                else:
                    print(f"\n  Tillgängliga listor:")
                    for i, f in enumerate(files, 1):
                        print(f"    {GRN}{i}.{NRM} {f.stem}")
                    print(f"    {GRN}A.{NRM} Alla")
                    export_choices = ["A. Alla"] + [f"{i}. {f.stem}" for i, f in enumerate(files, 1)]
                    picked = menu_select("  Välj lista:", export_choices) or "A. Alla"
                    if picked.startswith("A."):
                        to_export = files
                    else:
                        try:
                            to_export = [files[int(picked.split(".")[0]) - 1]]
                        except (ValueError, IndexError):
                            continue
                    last_export = state.get("obit_export_path", str(Path.home() / "Desktop"))
                    dest = menu_text("  Exportmapp", default=last_export) or last_export
                    dest = dest.strip('"')
                    dest_path = Path(dest)
                    if not dest_path.exists():
                        print(f"  Mappen finns inte: {dest}")
                        menu_pause()
                        continue
                    state["obit_export_path"] = str(dest_path)
                    save_state(state)
                    exported = []
                    for f in to_export:
                        out = dest_path / f.name
                        _shutil.copy2(f, out)
                        exported.append(out.name)
                    print(f"\n  Exporterade {len(exported)} fil(er) till {dest_path}:")
                    for name in exported:
                        print(f"    {name}")

            elif mode == "10":
                ged_dir = state.get("obit_gedcom_path", "")
                ged_files = sorted(Path(ged_dir).glob("*.ged")) if ged_dir else []
                if not ged_files:
                    print("  Ingen GEDCOM-mapp känd — kör val 4 först för att ange mapp.")
                    menu_pause()
                    continue
                picked_ged = menu_select("  Välj .ged-fil:", [f.name for f in ged_files])
                if not picked_ged:
                    continue
                ged_path = Path(ged_dir) / picked_ged
                last_owner = state.get("obit_last_owner", "")
                owner = menu_text("  Bevakare (e-post)", default=last_owner) or last_owner
                if "@" not in owner:
                    print("  Ange en giltig e-postadress.")
                    menu_pause()
                    continue
                depth_choice = menu_select("  Djup:", [
                    "1 — Partner + föräldrar",
                    "2 — + Syskon + mor/farföräldrar  (standard)",
                    "3 — + Syskonbarn + föräldrars syskon",
                ]) or "2 — + Syskon + mor/farföräldrar  (standard)"
                depth = depth_choice[0]
                cmd = [sys.executable,
                       str(obit_root / "watchlist" / "graph.py"),
                       "--gedcom", str(ged_path),
                       "--owner", owner,
                       "--depth", depth if depth in ("1", "2", "3") else "2"]
                subprocess.run(cmd, text=True, errors="replace")

        except KeyboardInterrupt:
            print("\n(Avbruten av användaren)")
        except Exception as e:
            print(f"\nFel: {e}")

        elapsed = (datetime.now() - start).seconds
        print(f"\n{'─' * 40}")
        print(t("run_done", s=elapsed))
        menu_pause()
