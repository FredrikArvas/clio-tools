"""
clio_run_privfin.py
Privatekonomin — import, rapporter och launcher för clio-privfin.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime
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


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _privfin_db_status(db_path: Path) -> tuple[set, dict]:
    """Returnerar (importerade_filnamn, kända_konton).

    importerade_filnamn: set av filnamn (ej sökväg) som finns i transactions.
    kända_konton: {account_id: (namn, agare, typ)}
    """
    if not db_path.exists():
        return set(), {}
    try:
        conn = sqlite3.connect(db_path)
        imp = {r[0] for r in conn.execute(
            "SELECT DISTINCT importfil FROM transactions"
        ).fetchall()}
        konton = {r[0]: (r[1], r[2], r[3])
                  for r in conn.execute(
                      "SELECT account_id, namn, agare, typ FROM accounts"
                  ).fetchall()}
        conn.close()
        return imp, konton
    except Exception:
        return set(), {}


def _privfin_scan_folder(folder: Path) -> list[Path]:
    """Returnerar XML/CSV-filer i mappen, filtrerar b.csv när XML finns."""
    xml_files = list(folder.glob("*.xml"))
    csv_files = list(folder.glob("*.csv"))
    xml_stems = {f.stem for f in xml_files}
    csv_files = [f for f in csv_files if f.stem not in xml_stems]
    return sorted(xml_files + csv_files, key=lambda f: f.name)


def _privfin_ask_account_meta(fil: Path, konton: dict) -> tuple[str, str, str] | None:
    """Frågar om kontonamn/ägare/typ. Föreslår från DB om account_id är känt.
    Returnerar (konto, agare, typ) eller None om användaren avbryter.
    """
    m = re.search(r"-(\d{8,})-", fil.name)
    account_id = m.group(1) if m else None

    if account_id and account_id in konton:
        namn, agare, typ = konton[account_id]
        print(f"    Konto känt: {BLD}{namn}{NRM}  [{agare}, {typ}]")
        if menu_confirm("    Använd dessa uppgifter?", default=True):
            return namn, agare, typ

    konto = menu_text("    Kontonamn")
    if not konto:
        return None

    agare = menu_select("    Ägare", ["Fredrik", "Ulrika", "Gemensamt"]) or "Fredrik"
    typ   = menu_select("    Kontotyp", ["checking", "savings", "credit", "loan"]) or "checking"

    return konto, agare, typ


# ── Launcher ──────────────────────────────────────────────────────────────────

def run_privfin(tool: dict, state: dict) -> None:
    """Custom launcher för clio-privfin — privatekonomin."""
    privfin_root   = ROOT / "clio-privfin"
    import_script  = privfin_root / "import.py"
    rapport_script = privfin_root / "rapport.py"
    db_path        = privfin_root / "familjekonomi.db"

    RAPPORT_KOMMANDON = [
        ("media",           "Mediaprenumerationer"),
        ("el",              "Elkostnader"),
        ("okategoriserade", "Transaktioner utan kategori"),
        ("sammanstallning", "Översikt per kategori"),
        ("transfers",       "Interna transfereringar"),
        ("manad",           "Transaktioner per månad"),
    ]

    _CHOICES = ["1. Importera kontoutdrag  (mapp eller enstaka fil)"] + [
        f"{i}. {desc}" for i, (_, desc) in enumerate(RAPPORT_KOMMANDON, 2)
    ]

    while True:
        clear()
        print(f"\n{BLD}  clio-privfin  —  Privatekonomi{NRM}")
        print(f"{'─' * 56}\n")

        choice = menu_select("Välj:", _CHOICES)
        if choice is None:
            return
        try:
            val = choice.split(".")[0].strip()
        except (IndexError, AttributeError):
            continue

        if val == "1":
            # ── Välj mapp eller fil ───────────────────────────────────
            try:
                last_folder = state.get("privfin_import_folder", "")
                if last_folder:
                    short = ("..." + last_folder[-45:]) if len(last_folder) > 48 else last_folder
                    print(f"\nSenaste mapp: {YEL}{short}{NRM}")
                    if menu_confirm("Använd samma mapp?", default=True):
                        src_path = Path(last_folder)
                    else:
                        raw = menu_text("Ny mapp eller fil")
                        if not raw:
                            continue
                        src_path = Path(raw.strip('"'))
                else:
                    raw = menu_text("Mapp eller fil")
                    if not raw:
                        continue
                    src_path = Path(raw.strip('"'))
            except BackToMenu:
                continue

            if not src_path.exists():
                print(f"{GRY}Sökvägen hittades inte: {src_path}{NRM}")
                menu_pause()
                continue

            if src_path.is_file():
                filer = [src_path]
                folder_str = str(src_path.parent)
            else:
                filer = _privfin_scan_folder(src_path)
                folder_str = str(src_path)
                if not filer:
                    print(f"{GRY}Inga XML/CSV-filer hittades i mappen.{NRM}")
                    menu_pause()
                    continue

            state["privfin_import_folder"] = folder_str
            save_state(state)

            importerade, konton = _privfin_db_status(db_path)

            nya   = [f for f in filer if f.name not in importerade]
            gamla = [f for f in filer if f.name in importerade]

            print(f"\n{'─' * 56}")
            nr_map = {}
            nr = 1

            if nya:
                print(f"\n  {BLD}EJ IMPORTERADE{NRM}")
                for f in nya:
                    print(f"  {GRN}{nr}.{NRM} {f.name}")
                    nr_map[str(nr)] = f
                    nr += 1
            else:
                print(f"\n  {GRY}(inga nya filer){NRM}")

            if gamla:
                print(f"\n  {GRY}REDAN IMPORTERADE  (reimport hoppar dubbletter automatiskt){NRM}")
                for f in gamla:
                    print(f"  {GRY}{nr}.{NRM} {GRY}{f.name}{NRM}")
                    nr_map[str(nr)] = f
                    nr += 1

            print(f"\n{'─' * 56}")
            print(f"  Ange nummer, intervall eller kombination — t.ex. {YEL}1,3-5{NRM} eller {YEL}a{NRM} för alla ej importerade.")

            try:
                val2 = _input("Val (0=tillbaka): ").strip().lower()
            except BackToMenu:
                continue

            if val2 == "a":
                valda = nya
            else:
                valda = []
                seen = set()
                for tok in val2.split(","):
                    tok = tok.strip()
                    if "-" in tok:
                        parts = tok.split("-", 1)
                        if parts[0].isdigit() and parts[1].isdigit():
                            for n in range(int(parts[0]), int(parts[1]) + 1):
                                k = str(n)
                                if k in nr_map and k not in seen:
                                    valda.append(nr_map[k])
                                    seen.add(k)
                        else:
                            print(f"  {GRY}Ogiltigt intervall: {tok} — hoppas{NRM}")
                    elif tok in nr_map and tok not in seen:
                        valda.append(nr_map[tok])
                        seen.add(tok)
                    else:
                        print(f"  {GRY}Okänt nummer: {tok} — hoppas{NRM}")

            if not valda:
                continue

            for fil in valda:
                print(f"\n  {BLD}{fil.name}{NRM}")
                try:
                    meta = _privfin_ask_account_meta(fil, konton)
                except BackToMenu:
                    print(f"  {GRY}Hoppas {fil.name}{NRM}")
                    continue
                if meta is None:
                    print(f"  {GRY}Hoppas {fil.name}{NRM}")
                    continue

                konto, agare, typ = meta
                cmd_args = [
                    sys.executable, str(import_script),
                    str(fil), "--konto", konto, "--agare", agare, "--typ", typ,
                    "--db", str(db_path),
                ]
                print(f"  Importerar...")
                subprocess.run(cmd_args, text=True, errors="replace")

                importerade_ny, konton = _privfin_db_status(db_path)
                importerade = importerade | importerade_ny

            state["last_run"] = tool["name"]
            save_state(state)
            menu_pause()

        elif val.isdigit() and 2 <= int(val) <= len(RAPPORT_KOMMANDON) + 1:
            rapport_cmd, _ = RAPPORT_KOMMANDON[int(val) - 2]
            extra_args = []

            if rapport_cmd == "manad":
                manad = menu_text("Månad (YYYY-MM, lämna tomt = innevarande)",
                                  default=date.today().strftime("%Y-%m"))
                manad = manad or date.today().strftime("%Y-%m")
                extra_args = [manad]

            print(f"\n{'─' * 40}")
            subprocess.run(
                [sys.executable, str(rapport_script), rapport_cmd] + extra_args,
                text=True, errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            state["last_run"] = tool["name"]
            save_state(state)
            menu_pause()
