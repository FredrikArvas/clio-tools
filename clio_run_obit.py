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
)

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key


# ── Launcher ──────────────────────────────────────────────────────────────────

def run_obit(tool: dict, state: dict) -> None:
    """Custom launcher för clio-agent-obit."""
    obit_root = ROOT / "clio-agent-obit"

    while True:
        clear()
        print(f"\n{BLD}  clio-agent-obit  —  Dödsannonsbevakning{NRM}")
        print(f"{'─' * 56}")
        print(f"  {GRN}1.{NRM} Kör bevakning        (dry-run, skickar inget)")
        print(f"  {GRN}2.{NRM} Kör bevakning         (skarpt läge, skickar mail)")
        print(f"  {GRN}3.{NRM} Kontrollera beroenden (check_deps.py)")
        print(f"  {GRN}4.{NRM} Importera GEDCOM      (→ watchlist)")
        print(f"  {GRN}5.{NRM} Importera adressbok   (→ watchlist)")
        print(f"  {GRN}6.{NRM} Sondera ny källa      (discover.py probe)")
        print(f"  {GRN}7.{NRM} Bjud in bevakare      (skicka mall via mail)")
        print(f"  {GRN}8.{NRM} Visa bevakningslista  (sammanfattning per bevakare)")
        print(f"  {GRN}9.{NRM} Exportera bevakningslista  (CSV till valfri mapp)")
        print(f"  {GRN}10.{NRM} Visa relationsgraf         (HTML i webbläsaren)")
        print(f"\n  {YEL}0.{NRM} Tillbaka")
        print(f"{'─' * 56}")
        try:
            mode = _input("\nVal: ").strip()
        except BackToMenu:
            return
        if mode == "0":
            return

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
                prompt = (f"  Sökväg till .ged-fil eller mapp [{last_ged}]: "
                          if last_ged else "  Sökväg till .ged-fil eller mapp: ")
                ged = input(prompt).strip().strip('"') or last_ged
                ged_path = Path(ged)
                if ged_path.is_dir():
                    state["obit_gedcom_path"] = str(ged_path)
                    save_state(state)
                    ged_files = sorted(ged_path.glob("*.ged"))
                    if not ged_files:
                        print("  Inga .ged-filer hittades i mappen.")
                        input(t("menu_continue"))
                        continue
                    print()
                    for i, f in enumerate(ged_files, 1):
                        print(f"  {GRN}{i}.{NRM} {f.name}")
                    print()
                    try:
                        pick = int(input(f"  Välj fil [1-{len(ged_files)}]: ").strip())
                        ged_path = ged_files[pick - 1]
                    except (ValueError, IndexError):
                        print("  Ogiltigt val.")
                        input(t("menu_continue"))
                        continue
                elif not ged_path.is_file():
                    print(f"  Filen hittades inte: {ged}")
                    input(t("menu_continue"))
                    continue
                last_owner = state.get("obit_last_owner", "")
                owner_prompt = (f"  Bevakare [{last_owner}]: "
                                if last_owner else "  Bevakare (e-post, t.ex. fredrik@arvas.se): ")
                owner = ""
                while "@" not in owner:
                    owner = input(owner_prompt).strip() or last_owner
                    if "@" not in owner:
                        print("  Ange en giltig e-postadress.")
                state["obit_last_owner"] = owner
                save_state(state)
                ego = input(f"  Centralperson [Enter = {owner}]: ").strip()
                print(f"\n  Djupnivå:")
                print(f"    1  Partner + föräldrar  (standard)")
                print(f"    2  + Syskon + mor/farföräldrar")
                print(f"    3  + Syskonbarn + föräldrars syskon")
                print(f"    F  Alla levande i trädet (fullständig)\n")
                depth_input = input("  Djup [1]: ").strip().lower() or "1"
                dry = input("  Dry-run? [J/n]: ").strip().lower()
                cmd = [sys.executable, str(obit_root / "watchlist" / "import_gedcom.py"),
                       "--gedcom", str(ged_path), "--owner", owner]
                if ego:
                    cmd += ["--ego", ego]
                if depth_input == "f":
                    cmd.append("--full")
                else:
                    cmd += ["--depth", depth_input if depth_input in ("1", "2", "3") else "1"]
                if dry != "n":
                    cmd.append("--dry-run")
                subprocess.run(cmd, text=True, errors="replace")

            elif mode == "5":
                contacts = input("  Sökväg till adressbok-CSV: ").strip().strip('"')
                owner = input("  Bevakare (e-post, t.ex. fredrik@arvas.se): ").strip()
                dry = input("  Dry-run? [J/n]: ").strip().lower()
                cmd = [sys.executable, str(obit_root / "watchlist" / "import_contacts.py"),
                       "--contacts", contacts, "--owner", owner]
                if dry != "n":
                    cmd.append("--dry-run")
                subprocess.run(cmd, text=True, errors="replace")

            elif mode == "6":
                url = input("  URL att sondera: ").strip()
                name_arg = input("  Namn för ny källa (Enter = lägg inte till): ").strip()
                cmd = [sys.executable, str(obit_root / "sources" / "discover.py"), "probe", url]
                if name_arg:
                    cmd += ["--add", name_arg]
                subprocess.run(cmd, text=True, errors="replace")

            elif mode == "7":
                to_name  = input("  Mottagarens fullständiga namn: ").strip()
                to_email = input("  Mottagarens e-post: ").strip()
                dry = input("  Dry-run (förhandsgranska utan att skicka)? [J/n]: ").strip().lower()
                cmd = [sys.executable,
                       str(obit_root / "watchlist" / "send_invitation.py"),
                       "--to-name", to_name, "--to-email", to_email]
                if dry != "n":
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
                    pick = input("\n  Välj [A]: ").strip().lower() or "a"
                    if pick == "a":
                        to_export = files
                    else:
                        try:
                            to_export = [files[int(pick) - 1]]
                        except (ValueError, IndexError):
                            print("  Ogiltigt val.")
                            input(t("menu_continue"))
                            continue
                    last_export = state.get("obit_export_path", str(Path.home() / "Desktop"))
                    dest = input(f"  Exportmapp [{last_export}]: ").strip().strip('"') or last_export
                    dest_path = Path(dest)
                    if not dest_path.exists():
                        print(f"  Mappen finns inte: {dest}")
                        input(t("menu_continue"))
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
                    input(t("menu_continue"))
                    continue
                print(f"\n  Välj .ged-fil:")
                for i, f in enumerate(ged_files, 1):
                    print(f"    {GRN}{i}.{NRM} {f.name}")
                try:
                    pick = int(input(f"\n  Val [1]: ").strip() or "1")
                    ged_path = ged_files[pick - 1]
                except (ValueError, IndexError):
                    print("  Ogiltigt val.")
                    input(t("menu_continue"))
                    continue
                last_owner = state.get("obit_last_owner", "")
                owner_prompt = (f"  Bevakare [{last_owner}]: "
                                if last_owner else "  Bevakare (e-post): ")
                owner = input(owner_prompt).strip() or last_owner
                if "@" not in owner:
                    print("  Ange en giltig e-postadress.")
                    input(t("menu_continue"))
                    continue
                print(f"\n  Djup (antal relationsnivåer från dig):")
                print(f"    1  Partner + föräldrar")
                print(f"    2  + Syskon + mor/farföräldrar  (standard)")
                print(f"    3  + Syskonbarn + föräldrars syskon")
                depth = input("  Djup [2]: ").strip() or "2"
                cmd = [sys.executable,
                       str(obit_root / "watchlist" / "graph.py"),
                       "--gedcom", str(ged_path),
                       "--owner", owner,
                       "--depth", depth if depth in ("1", "2", "3") else "2"]
                subprocess.run(cmd, text=True, errors="replace")

            else:
                print("Ogiltigt val.")
                input(t("menu_continue"))
                continue

        except KeyboardInterrupt:
            print("\n(Avbruten av användaren)")
        except Exception as e:
            print(f"\nFel: {e}")

        elapsed = (datetime.now() - start).seconds
        print(f"\n{'─' * 40}")
        print(t("run_done", s=elapsed))
        input(t("menu_continue"))
