"""
clio_run_research.py
GEDCOM-navigering och launcher för clio-research.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from clio_menu import (
    BackToMenu, _input,
    GRN, YEL, GRY, BLD, NRM,
    save_state,
)

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key


# ── GEDCOM-hjälpare ───────────────────────────────────────────────────────────

def _scan_ged_files(folder: str) -> list:
    """Returnerar .ged-filer i mappen, sorterade på mtime fallande."""
    p = Path(folder)
    if not p.exists():
        return []
    return sorted(p.rglob("*.ged"), key=lambda f: f.stat().st_mtime, reverse=True)


def select_gedcom(state: dict) -> str | None:
    """Välj GEDCOM-fil — speglar select_folder-mönstret, med bytbar sökmapp."""
    last       = state.get("last_gedcom", "")
    recent     = state.get("recent_gedcom", [])
    search_dir = state.get("gedcom_search_dir",
                           str(Path.home() / "Documents" / "Dropbox" /
                               "ulrika-fredrik" / "släktforskning"))

    if last:
        short = ("..." + last[-50:]) if len(last) > 53 else last
        print(f"\nSenaste GEDCOM: {YEL}{short}{NRM}")
        answer = _input("Använd samma fil? [J/n] (0=tillbaka): ").strip().lower()
        if answer == "" or answer == "j":
            return last

    while True:
        found   = _scan_ged_files(search_dir)
        others  = [f for f in reversed(recent) if f != last]
        options = list(dict.fromkeys(others + [str(f) for f in found]))

        short_dir = ("..." + search_dir[-40:]) if len(search_dir) > 43 else search_dir
        print(f"\nTillgängliga GEDCOM-filer  {GRY}(sökmapp: {short_dir}){NRM}")
        if options:
            for i, f in enumerate(options[:8], 1):
                name_part  = Path(f).name
                short_path = ("..." + f[-45:]) if len(f) > 48 else f
                print(f"  {i}. {BLD}{name_part}{NRM}")
                print(f"     {GRY}{short_path}{NRM}")
        else:
            print(f"  {GRY}(inga .ged-filer hittades){NRM}")
        print(f"  s. Byt sökmapp")
        print(f"  m. Ange filsökväg manuellt")

        val = _input("\nVal [1] (0=tillbaka): ").strip().strip('"')

        if val == "s":
            new_dir = _input("Ny sökmapp (0=tillbaka): ").strip().strip('"')
            if Path(new_dir).is_dir():
                search_dir = new_dir
                state["gedcom_search_dir"] = search_dir
                save_state(state)
            else:
                print(f"{GRY}Mappen hittades inte.{NRM}")
            continue

        if val == "m" or val == "":
            path = _input("Sökväg till .ged-fil (0=tillbaka): ").strip().strip('"')
            return path if path else None

        if val.isdigit() and 1 <= int(val) <= len(options[:8]):
            return options[int(val) - 1]

        print(f"{GRY}Ogiltigt val.{NRM}")


def _search_gedcom_persons(gedcom_path: str, query: str) -> list:
    """Snabb namnsökning i GEDCOM-text. Returnerar lista med {id, name}-dicts."""
    results      = []
    current_id   = None
    current_name = None
    words = query.lower().replace("*", "").split()

    def _matches(name: str) -> bool:
        n = name.lower().replace("*", "")
        return all(w in n for w in words)

    try:
        with open(gedcom_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip()
                if line.startswith("0 @") and " INDI" in line:
                    if current_id and current_name and _matches(current_name):
                        results.append({"id": current_id, "name": current_name})
                    parts = line.split(" ", 2)
                    current_id   = parts[1] if len(parts) > 1 else None
                    current_name = None
                elif current_id and line.startswith("1 NAME "):
                    current_name = line[7:].replace("/", " ").strip()
        if current_id and current_name and _matches(current_name):
            results.append({"id": current_id, "name": current_name})
    except OSError:
        pass
    return results


def _gedcom_has_asterisk(gedcom_path: str, gedcom_id: str) -> bool:
    """Returnerar True om personens NAME-rad i GEDCOM innehåller asterisk (levande-markör)."""
    in_block = False
    try:
        with open(gedcom_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip()
                if line.startswith("0 ") and " INDI" in line:
                    in_block = gedcom_id in line
                elif in_block and line.startswith("1 NAME "):
                    return "*" in line
                elif in_block and line.startswith("0 "):
                    break
    except OSError:
        pass
    return False


def _pick_person(gedcom: str) -> str | None:
    """Interaktiv namnsökning i GEDCOM-fil. Returnerar GEDCOM-ID eller None."""
    while True:
        query = _input("Sök person (namn eller del av namn, tomt=ID, 0=tillbaka): ").strip()
        if not query:
            person_id = _input("GEDCOM-ID (t.ex. @I294@, 0=tillbaka): ").strip()
            if person_id and not person_id.startswith("@"):
                person_id = f"@{person_id}@"
            return person_id or None

        matches = _search_gedcom_persons(gedcom, query)
        if not matches:
            print(f"  {GRY}Inga träffar på '{query}'. Försök igen.{NRM}")
            continue

        if len(matches) == 1:
            m = matches[0]
            print(f"  Hittade: {BLD}{m['name']}{NRM}  {GRY}({m['id']}){NRM}")
            return m["id"]

        print(f"\n  {len(matches)} träffar:")
        for i, m in enumerate(matches[:20], 1):
            print(f"  {i}. {BLD}{m['name']}{NRM}  {GRY}({m['id']}){NRM}")
        if len(matches) > 20:
            print(f"  {GRY}… och {len(matches)-20} till. Förfina sökningen.{NRM}")

        val = _input("\nVälj nummer (Enter=ny sökning, 0=tillbaka): ").strip()
        if val.isdigit() and 1 <= int(val) <= min(len(matches), 20):
            return matches[int(val) - 1]["id"]


# ── Launcher ──────────────────────────────────────────────────────────────────

def run_research(tool: dict, state: dict) -> None:
    """Custom launcher för clio-research — hämtar GEDCOM-fil, läge och parametrar."""
    if not tool["script"].exists():
        print(f"\nScript saknas: {tool['script']}")
        input(t("menu_continue"))
        return

    try:
        gedcom = select_gedcom(state)
        if not gedcom:
            print("\nIngen GEDCOM-fil vald.")
            input(t("menu_continue"))
            return

        if not Path(gedcom).exists():
            print(f"\nFilen hittades inte: {gedcom}")
            input(t("menu_continue"))
            return

        print(f"\n── Läge {'─' * 45}")
        print(f"  1. Analysera person   (enskild → Notion)")
        print(f"  2. Batch              (flera personer → Notion)")
        print(f"  3. Granskningsstatus  (visa väntande kort)")
        print(f"  4. Godkänn            (markera granskningskort som klart)")
        mode = _input("\nLäge [1] (0=tillbaka): ").strip() or "1"

        cmd = [sys.executable, str(tool["script"])]

        if mode == "1":
            person_id = _pick_person(gedcom)
            if not person_id:
                print("Person-ID krävs.")
                input(t("menu_continue"))
                return

            possibly_living = _gedcom_has_asterisk(gedcom, person_id)
            if possibly_living:
                print(f"\n  {YEL}⚠ Personen kan vara levande — syfte krävs som GDPR-grund{NRM}")
                print(f"  {GRY}Legitima syften t.ex.:{NRM}")
                print(f"  {GRY}  • Söker om mig själv (eget medgivande){NRM}")
                print(f"  {GRY}  • Familjeminnet / genealogi (t.ex. guldboda-75){NRM}")
                print(f"  {GRY}  • Valberedning inom förening (offentlig roll){NRM}")
                print(f"  {GRY}  • Annat — ange fritext, sparas som GDPR-grund{NRM}")
                while True:
                    syfte = _input("  Syfte (obligatoriskt, 0=tillbaka): ").strip()
                    if syfte:
                        break
                    print(f"  {YEL}Syfte måste anges för levande person.{NRM}")
            else:
                syfte = _input("Syfte/etikett (valfritt, t.ex. guldboda-75, 0=tillbaka): ").strip()

            dry  = _input("Dry-run — visa utan att spara till Notion? [J/n] (0=tillbaka): ").strip().lower()
            cmd += ["--gedcom-id", person_id, "--gedcom-file", gedcom]
            if syfte:
                cmd += ["--syfte", syfte]
            if possibly_living:
                cmd += ["--levande", "ja"]
            if dry != "n":
                cmd.append("--dry-run")

        elif mode == "2":
            surname = _input("Filtrera på efternamn (tomt=alla, 0=tillbaka): ").strip()
            syfte   = _input("Syfte/etikett (valfritt, 0=tillbaka): ").strip()
            dry     = _input("Dry-run — visa utan att spara till Notion? [J/n] (0=tillbaka): ").strip().lower()
            cmd    += ["--batch", "--gedcom-file", gedcom]
            if surname:
                cmd += ["--filter-surname", surname]
            if syfte:
                cmd += ["--syfte", syfte]
            if dry != "n":
                cmd.append("--dry-run")

        elif mode == "3":
            cmd.append("--status")

        elif mode == "4":
            import subprocess as _sp
            status_result = _sp.run(
                [sys.executable, str(tool["script"]), "--status"],
                capture_output=True, text=True, errors="replace"
            )
            print(status_result.stdout)
            if "Inga väntande" in status_result.stdout:
                input(t("menu_continue"))
                return
            val = _input("Välj nummer att godkänna (0=tillbaka): ").strip()
            if not val or not val.isdigit():
                return
            cmd += ["--approve", val]

        else:
            print("Ogiltigt val.")
            input(t("menu_continue"))
            return

    except BackToMenu:
        return

    # Spara GEDCOM i state
    state["last_gedcom"] = gedcom
    recent = state.setdefault("recent_gedcom", [])
    if gedcom in recent:
        recent.remove(gedcom)
    recent.append(gedcom)
    state["recent_gedcom"] = recent[-5:]
    state["last_run"] = tool["name"]
    save_state(state)

    print(f"\nStartar clio-research...")
    print("─" * 40)
    start = datetime.now()
    try:
        subprocess.run(cmd, text=True, errors="replace")
    except Exception as e:
        print(f"\nFel vid körning: {e}")
    elapsed = (datetime.now() - start).seconds
    print(f"\n{'─' * 40}")
    print(t("run_done", s=elapsed))
    input(t("menu_continue"))
