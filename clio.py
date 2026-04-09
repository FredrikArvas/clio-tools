"""
clio.py
Main menu for the clio-tools ecosystem.

Usage:
    python clio.py
"""

import sys
import json
import os
import subprocess
import getpass
from pathlib import Path
from datetime import datetime

# Load .env so all subtools inherit API keys
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv(_env_file, override=True)
    except ImportError:
        # python-dotenv not installed — parse manually
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ[_k.strip()] = _v.strip()

__version__ = "2.1.1"

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT       = Path(__file__).parent
CONFIG_DIR = ROOT / "config"
STATE_FILE = CONFIG_DIR / "clio_state.json"

# Python 3.12 venv för Ollama-beroende moduler (ollama-paketet stöder ej 3.14)
_VENV_OLLAMA_PYTHON = ROOT / "venv-ollama" / "Scripts" / "python.exe"
_OLLAMA_SCRIPTS = {"clio_vision.py", "digikam_db.py"}

def _python_for(script: Path) -> str:
    """Returnerar rätt Python-körbar för givet script."""
    if script.name in _OLLAMA_SCRIPTS and _VENV_OLLAMA_PYTHON.exists():
        return str(_VENV_OLLAMA_PYTHON)
    return sys.executable

try:
    from clio_env import check_environment as _check_environment
except ImportError:
    def _check_environment(**kwargs): pass  # bootstrap-fallback

try:
    from config.clio_utils import t, set_language
except ImportError:
    def t(key, **kwargs): return key

try:
    from clio_core.banner import print_banner as _print_banner
except ImportError:
    _print_banner = None

# ── Tools registry ────────────────────────────────────────────────────────────

TOOLS = [
    {
        "nr":     1,
        "name":   "clio-docs",
        "desc":   "Skannade PDF:er → sökbar PDF + text",
        "script": ROOT / "clio-docs" / "clio-docs-batch.py",
        "status": "active",
    },
    {
        "nr":          2,
        "name":        "clio-vision",
        "desc":        "Bilder → beskrivning, taggar och masterdata",
        "status":      "active",
        "needs_folder": False,
        "submenu": [
            {
                "nr":           1,
                "name":         "analysera-bilder",
                "desc":         "Kör bildanalys på en mapp (Claude / Haiku / Ollama)",
                "script":       ROOT / "clio-vision" / "clio_vision.py",
                "needs_folder": True,
            },
            {
                "nr":           2,
                "name":         "digikam-browser",
                "desc":         "Bläddra DigiKam-album, statistik och starta analys",
                "script":       ROOT / "clio-vision" / "digikam_db.py",
                "needs_folder": False,
            },
        ],
    },
    {
        "nr":     3,
        "name":   "clio-transcribe",
        "desc":   "Ljud/video → text med tidsstämplar",
        "script": ROOT / "clio-transcribe" / "clio-transcribe-batch.py",
        "status": "active",
    },
    {
        "nr":     4,
        "name":   "clio-narrate",
        "desc":   "Text/DOCX → tal (ljudbok, Piper/Edge-TTS)",
        "script": ROOT / "clio-narrate" / "clio-narrate-batch.py",
        "status": "active",
    },
    {
        "nr":          5,
        "name":        "clio-library",
        "desc":        "Arvas Familjebibliotek — import, berikning, rekommendation",
        "status":      "active",
        "needs_folder": False,
        "submenu": [
            {
                "nr":          1,
                "name":        "import-json",
                "desc":        "Importera JSON (böcker + exemplar i ett svep)",
                "script":      ROOT / "clio-library" / "import_json.py",
                "needs_folder": False,
            },
            {
                "nr":          2,
                "name":        "import-böcker",
                "desc":        "Importera böcker till Bokregistret (CSV → Notion)",
                "script":      ROOT / "clio-library" / "import_books.py",
                "needs_folder": False,
            },
            {
                "nr":          3,
                "name":        "import-läsningar",
                "desc":        "Importera läsningar/betyg till Betygstabellen (CSV → Notion)",
                "script":      ROOT / "clio-library" / "import_lasningar.py",
                "needs_folder": False,
            },
            {
                "nr":          4,
                "name":        "import-exemplar",
                "desc":        "Importera exemplar/platser till Exemplar-tabellen (CSV → Notion)",
                "script":      ROOT / "clio-library" / "import_copies.py",
                "needs_folder": False,
            },
            {
                "nr":          5,
                "name":        "prepare-import",
                "desc":        "Förbered import — konverterar GoodReads/Storytel-export till CSV",
                "script":      ROOT / "clio-library" / "prepare_import.py",
                "needs_folder": False,
            },
            {
                "nr":          6,
                "name":        "enrich",
                "desc":        "Berika med år, ISBN och förlag via Google Books",
                "script":      ROOT / "clio-library" / "enrich_books.py",
                "needs_folder": False,
            },
            {
                "nr":          7,
                "name":        "match-bokid",
                "desc":        "Fuzzy-matcha BOK-ID i Betygstabellen mot Bokregistret",
                "script":      ROOT / "clio-library" / "match_bokid.py",
                "needs_folder": False,
            },
            {
                "nr":          8,
                "name":        "smakrådgivaren",
                "desc":        "Bokklubbsrekommendation via Notion + Claude",
                "script":      ROOT / "clio-library" / "taste_recommender.py",
                "needs_folder": False,
            },
            {
                "nr":          9,
                "name":        "library-excel",
                "desc":        "Bygg biblioteks-Excel från Notion",
                "script":      ROOT / "clio-library" / "build_library_excel.py",
                "needs_folder": False,
            },
        ],
    },
    {
        "nr":          6,
        "name":        "clio-emailfetch",
        "desc":        "IMAP-backup av e-post till Dropbox",
        "script":      ROOT / "clio-emailfetch" / "imap_backup.py",
        "status":      "active",
        "needs_folder": False,
    },
    {
        "nr":          7,
        "name":        "clio-fetch",
        "desc":        "Webbhämtning → JSON  (--url URL | --dir mapp | --file fil)",
        "script":      ROOT / "clio-fetch" / "clio_fetch.py",
        "status":      "active",
        "needs_folder": False,
    },
    {
        "nr":           8,
        "name":         "clio-research",
        "desc":         "Släktforskning — GEDCOM → Wikidata → Wikipedia → Notion",
        "script":       ROOT / "clio-research" / "research.py",
        "status":       "active",
        "needs_folder": False,
        "custom_runner": True,
    },
    {
        "nr":           9,
        "name":         "clio-agent-mail",
        "desc":         "AI-mailhantering — IMAP-polling, regelmotor, svarsgenerering",
        "script":       ROOT / "clio-agent-mail" / "main.py",
        "status":       "active",
        "needs_folder": False,
        "custom_runner": True,
    },
    {
        "nr":           10,
        "name":         "clio-agent-obit",
        "desc":         "Dödsannonsbevakning — daglig kontroll mot bevakningslista",
        "script":       ROOT / "clio-agent-obit" / "run.py",
        "status":       "active",
        "needs_folder": False,
        "custom_runner": True,
    },
    {
        "nr":           11,
        "name":         "clio-privfin",
        "desc":         "Privatekonomin — importera kontoutdrag, kategorisera, rapporter",
        "script":       ROOT / "clio-privfin" / "rapport.py",
        "status":       "active",
        "needs_folder": False,
        "custom_runner": True,
    },
]

# ── Colors ────────────────────────────────────────────────────────────────────

GRN = "\033[92m"
YEL = "\033[93m"
GRY = "\033[90m"
BLU = "\033[94m"
BLD = "\033[1m"
NRM = "\033[0m"

# ── Navigation ────────────────────────────────────────────────────────────────

class BackToMenu(Exception):
    """Kastas när användaren skriver 0 i en aktiv prompt — återgår till huvudmenyn."""
    pass


def _input(prompt: str) -> str:
    """Wrappar input(). Kastar BackToMenu om användaren skriver '0'."""
    val = input(prompt)
    if val.strip() == "0":
        raise BackToMenu()
    return val

# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {"last_folder": {}, "runs": {}}


def save_state(state: dict):
    CONFIG_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

# ── Status display ────────────────────────────────────────────────────────────

def tool_status(tool: dict, state: dict) -> str:
    name = tool["name"]
    runs = state.get("runs", {}).get(name, [])
    last_folder = state.get("last_folder", {}).get(name, "")

    if not runs:
        return f"{GRY}Never run{NRM}"

    last = runs[-1]
    date   = last.get("date", "")
    ok     = last.get("succeeded", 0)
    total  = last.get("total", 0)
    folder = last.get("folder", "")
    short  = ("..." + folder[-30:]) if len(folder) > 33 else folder
    return f"{GRN}Last: {date}{NRM} – {ok}/{total} files – {GRY}{short}{NRM}"


def register_run(name: str, folder: str, succeeded: int, total: int, state: dict):
    state.setdefault("runs", {}).setdefault(name, []).append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "folder": folder,
        "succeeded": succeeded,
        "total": total,
    })
    state["runs"][name] = state["runs"][name][-10:]
    state.setdefault("last_folder", {})[name] = folder
    # Track most recently used folders across all tools
    folders = state.setdefault("recent_folders", [])
    if folder in folders:
        folders.remove(folder)
    folders.append(folder)
    state["recent_folders"] = folders[-10:]

# ── Menu ──────────────────────────────────────────────────────────────────────

def clear():
    import os
    os.system("cls" if sys.platform == "win32" else "clear")


def show_menu(state: dict):
    clear()
    if _print_banner:
        _print_banner("Clio Tools", __version__, subtitle="")
    else:
        print(f"\n{BLD}{'─' * 56}{NRM}")
        print(f"{BLD}  Clio Tools  v{__version__}{NRM}")
        print(f"{BLD}{'─' * 56}{NRM}")
    print()

    last_run = state.get("last_run", None)

    for t in TOOLS:
        if t["status"] == "active":
            color = GRN
        else:
            color = GRY

        marker = f" {YEL}◀{NRM}" if t["name"] == last_run else ""
        print(f"  {color}{t['nr']}.{NRM} {BLD}{t['name']}{NRM}{marker}")
        print(f"     {t['desc']}")
        print(f"     {tool_status(t, state)}")
        print()

    print(f"  {YEL}c.{NRM} Kontrollera miljön (clio_check)")
    print(f"  {YEL}e.{NRM} Exportera källkod (ZIP för Claude chat)")
    print(f"  {YEL}q.{NRM} Avsluta\n")
    print(f"{'─' * 56}")


def select_folder(tool_name: str, state: dict) -> str | None:
    last = state.get("last_folder", {}).get(tool_name, "")
    recent = state.get("recent_folders", [])

    if last:
        print(f"\nSenaste mapp: {YEL}{last}{NRM}")
        answer = _input(t("same_folder")).strip().lower()
        if answer == "" or answer == "j":
            return last

    # Show numbered list of recent folders
    others = [f for f in reversed(recent) if f != last]
    if others:
        print(t("menu_other_folders"))
        for i, f in enumerate(others[:5], 1):
            print(f"  {i}. {f}")
        print(t("menu_manual_path"))
        val = _input(t("menu_choice")).strip().strip('"')
        if val.isdigit() and 1 <= int(val) <= len(others[:5]):
            return others[int(val) - 1]
        elif val:
            return val
        return None

    folder = _input(t("menu_enter_folder")).strip().strip('"')
    return folder if folder else None


def _scan_ged_files(folder: str) -> list:
    """Return .ged files in folder, sorted by mtime descending."""
    p = Path(folder)
    if not p.exists():
        return []
    return sorted(p.rglob("*.ged"), key=lambda f: f.stat().st_mtime, reverse=True)


def select_gedcom(state: dict) -> str | None:
    """Select a GEDCOM file — mirrors select_folder pattern, with changeable search dir."""
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
        found  = _scan_ged_files(search_dir)
        others = [f for f in reversed(recent) if f != last]
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
            continue  # re-render list with new dir

        if val == "m" or val == "":
            path = _input("Sökväg till .ged-fil (0=tillbaka): ").strip().strip('"')
            return path if path else None

        if val.isdigit() and 1 <= int(val) <= len(options[:8]):
            return options[int(val) - 1]

        print(f"{GRY}Ogiltigt val.{NRM}")


def _search_gedcom_persons(gedcom_path: str, query: str) -> list:
    """Quick name search directly in GEDCOM text. Returns list of {id, name} dicts."""
    results      = []
    current_id   = None
    current_name = None
    # Alla ord i query måste finnas i namnet (ordning spelar ingen roll)
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
        # Last person
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
                    break  # nästa post, hittade inget
    except OSError:
        pass
    return False


def _pick_person(gedcom: str) -> str | None:
    """Interactive name search in GEDCOM file. Returns GEDCOM-ID or None."""
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
        # Empty/invalid → loop back to search


def run_research(tool: dict, state: dict):
    """Custom launcher for clio-research — collects GEDCOM file, mode and params."""
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

            # GDPR: levande person kräver angivet syfte som rättslig grund
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
            # Hämta och visa väntande kort först — välj med siffra
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

    # Save GEDCOM to state
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


def _mail_whitelist(tool: dict, state: dict):
    """Lägg till e-postadress i Notion-vitlistan för clio@."""
    import configparser, sys as _sys
    cfg_path = tool["script"].parent / "clio.config"
    if not cfg_path.exists():
        print(f"\n{GRY}clio.config hittades inte: {cfg_path}{NRM}")
        input(t("menu_continue"))
        return

    cfg = configparser.ConfigParser()
    cfg.read(str(cfg_path), encoding="utf-8")
    page_id = cfg.get("mail", "whitelist_notion_page_id", fallback="")
    if not page_id:
        print(f"\n{GRY}whitelist_notion_page_id saknas i clio.config{NRM}")
        input(t("menu_continue"))
        return

    try:
        addr = _input("\nE-postadress att vitlista (0=tillbaka): ").strip().lower()
    except BackToMenu:
        return
    if not addr or "@" not in addr:
        print(f"{GRY}Ogiltig adress.{NRM}")
        input(t("menu_continue"))
        return

    # Läs .env för Notion-nyckel
    env_root = tool["script"].parent.parent / ".env"
    env_mod  = tool["script"].parent / ".env"
    for f in (env_root, env_mod):
        if f.exists():
            try:
                from dotenv import load_dotenv as _ld
                _ld(f, override=False)
            except ImportError:
                pass

    notion_token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN")
    if not notion_token:
        print(f"\n{GRY}NOTION_API_KEY / NOTION_TOKEN saknas i .env{NRM}")
        input(t("menu_continue"))
        return

    try:
        from notion_client import Client as _NC
        client = _NC(auth=notion_token)
        client.blocks.children.append(
            block_id=page_id,
            children=[{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": addr}}]
                }
            }]
        )
        print(f"\n{GRN}✓ {addr} tillagd i vitlistan.{NRM}")
    except Exception as e:
        print(f"\n{GRY}Fel: {e}{NRM}")
    input(t("menu_continue"))


def _mail_log(tool: dict, state: dict):
    """Visar hanterade mail och låter Fredrik åtgärda väntande."""
    import sqlite3 as _sql
    import re as _re
    db_path = tool["script"].parent / "state.db"
    if not db_path.exists():
        print(f"\n{GRY}state.db hittades inte — inget mail har hanterats ännu.{NRM}")
        input(t("menu_continue"))
        return

    status_color = {
        "NEW": YEL, "PENDING": YEL, "SENT": GRN,
        "FLAGGED": GRY, "REJECTED": GRY, "WAITING": YEL,
    }
    status_label = {
        "NEW": "NY", "PENDING": "VÄNTAR-GODK", "SENT": "SKICKAT",
        "FLAGGED": "FLAGGAD", "REJECTED": "AVVISAD", "WAITING": "⏳ VÄNTAR",
    }

    def _addr(sender):
        m = _re.search(r"<([^>]+)>", sender or "")
        return (m.group(1) if m else sender or "?").lower()

    def _load(con, status_filter, n):
        if status_filter:
            return con.execute(
                "SELECT id, date_received, sender, subject, status, body "
                "FROM mail WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status_filter, n)
            ).fetchall()
        return con.execute(
            "SELECT id, date_received, sender, subject, status, body "
            "FROM mail ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()

    def _print_list(rows, numbered=False):
        print(f"\n{BLD}{'─' * 82}")
        prefix = "    " if not numbered else "  # "
        print(f"{prefix}{'Datum':<17} {'Avsändare':<28} {'Ämne':<22} {'Status'}")
        print(f"{'─' * 82}{NRM}")
        for i, row in enumerate(rows, 1):
            mail_id, date, sender, subject, status, body = row
            date_s    = (date or "?")[:16]
            sender_s  = _addr(sender)[:27]
            subject_s = (subject or "")[:21]
            col   = status_color.get(status, NRM)
            label = status_label.get(status, status)
            idx = f"[{i}]" if numbered else "   "
            print(f"  {idx} {date_s:<17} {sender_s:<28} {subject_s:<22} {col}{label}{NRM}")

    # ── Välj filter ───────────────────────────────────────────────────────────
    print(f"\n{BLD}Maillogg — visa:{NRM}")
    print(f"  {GRN}1.{NRM} Väntar på åtgärd  (default)")
    print(f"  {GRN}2.{NRM} Alla")
    print(f"  {GRN}3.{NRM} Skickade")
    print(f"  {GRN}4.{NRM} Flaggade / avvisade")
    try:
        f_choice = _input("\nVal [1]: ").strip() or "1"
    except BackToMenu:
        return

    filter_map = {
        "1": "WAITING", "2": None, "3": "SENT", "4": "FLAGGED",
    }
    status_filter = filter_map.get(f_choice, "WAITING")

    try:
        n_input = _input("Antal att visa [20]: ").strip()
    except BackToMenu:
        return
    n = int(n_input) if n_input.isdigit() else 20

    try:
        con = _sql.connect(str(db_path))
        rows = _load(con, status_filter, n)
    except Exception as e:
        print(f"\n{GRY}Fel vid läsning av databas: {e}{NRM}")
        input(t("menu_continue"))
        return

    if not rows:
        print(f"\n  {GRY}(inga mail med detta filter){NRM}")
        con.close()
        input(t("menu_continue"))
        return

    numbered = (status_filter == "WAITING")
    _print_list(rows, numbered=numbered)

    waiting_count = sum(1 for r in rows if r[4] == "WAITING")
    if waiting_count:
        print(f"\n  {YEL}⏳ {waiting_count} mail väntar på vitlistningsbeslut{NRM}")
    print(f"{BLD}{'─' * 82}{NRM}")

    # ── Åtgärd för väntande ───────────────────────────────────────────────────
    if not numbered:
        con.close()
        input(t("menu_continue"))
        return

    try:
        sel = _input("\nVälj mail för åtgärd (Enter=avsluta): ").strip()
    except BackToMenu:
        con.close()
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(rows)):
        con.close()
        return

    selected = rows[int(sel) - 1]
    mail_id, date, sender, subject, status, body = selected
    sender_email = _addr(sender)

    print(f"\n{BLD}{'─' * 60}")
    print(f"Från:  {sender}")
    print(f"Ämne:  {subject or '(tomt)'}")
    print(f"Datum: {(date or '')[:16]}")
    print(f"{'─' * 60}{NRM}")
    print((body or "")[:600])
    if body and len(body) > 600:
        print(f"{GRY}[...]{NRM}")
    print(f"\n{BLD}{'─' * 60}{NRM}")

    print(f"  {GRN}V{NRM} — Vitlista  (nästa poll skickar svar)")
    print(f"  {GRN}S{NRM} — Svartlista")
    print(f"  {GRN}B{NRM} — Behåll olistad (hållsvaret är redan skickat)")
    try:
        action = _input("\nÅtgärd [V/S/B] (Enter=avbryt): ").strip().upper()
    except BackToMenu:
        con.close()
        return

    # Läs config för Notion-nyckel och whitelist-sida
    cfg_path = tool["script"].parent / "clio.config"
    cfg = configparser.ConfigParser()
    cfg.read(str(cfg_path), encoding="utf-8")
    wl_page = cfg.get("mail", "whitelist_notion_page_id", fallback="")

    env_root = tool["script"].parent.parent / ".env"
    env_mod  = tool["script"].parent / ".env"
    for f in (env_root, env_mod):
        if f.exists():
            try:
                from dotenv import load_dotenv as _ld
                _ld(f, override=False)
            except ImportError:
                pass
    notion_token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN")

    if action == "V":
        # Lägg till i Notion-vitlistan
        added = False
        if wl_page and notion_token:
            try:
                from notion_client import Client as _NC
                _NC(auth=notion_token).blocks.children.append(
                    block_id=wl_page,
                    children=[{"object": "block", "type": "paragraph",
                               "paragraph": {"rich_text": [{"type": "text",
                                             "text": {"content": sender_email}}]}}]
                )
                added = True
            except Exception as e:
                print(f"{GRY}Notion-fel: {e}{NRM}")
        if added:
            print(f"\n{GRN}✓ {sender_email} vitlistad. Nästa poll-cykel skickar svar automatiskt.{NRM}")
        else:
            print(f"{GRY}Kunde inte lägga till i vitlistan.{NRM}")

    elif action == "S":
        # Lägg till i svartlistan (SQLite) och stäng alla väntande från denna avsändare
        now = __import__("datetime").datetime.utcnow().isoformat()
        try:
            con.execute(
                "INSERT OR IGNORE INTO blacklist (email, added_at) VALUES (?, ?)",
                (sender_email, now)
            )
            con.execute(
                "UPDATE mail SET status = 'FLAGGED', updated_at = ? "
                "WHERE status = 'WAITING' AND sender LIKE ?",
                (now, f"%{sender_email}%")
            )
            con.commit()
            print(f"\n{GRN}✓ {sender_email} svartlistad. Väntande mail stängda.{NRM}")
        except Exception as e:
            print(f"{GRY}Fel: {e}{NRM}")

    elif action == "B":
        # Stäng väntande mail — hållsvaret är redan skickat
        now = __import__("datetime").datetime.utcnow().isoformat()
        try:
            con.execute(
                "UPDATE mail SET status = 'FLAGGED', updated_at = ? "
                "WHERE status = 'WAITING' AND sender LIKE ?",
                (now, f"%{sender_email}%")
            )
            con.commit()
            print(f"\n{GRN}✓ {sender_email} behålls olistad. Inga fler åtgärder.{NRM}")
        except Exception as e:
            print(f"{GRY}Fel: {e}{NRM}")

    con.close()
    input(t("menu_continue"))


def _mail_insights(tool: dict, state: dict):
    """Kör insiktsanalys och visar resultatet i TUI."""
    import configparser, sys as _sys

    script_dir = tool["script"].parent
    cfg_path = script_dir / "clio.config"
    if not cfg_path.exists():
        print(f"\n{GRY}clio.config hittades inte.{NRM}")
        input(t("menu_continue"))
        return

    cfg = configparser.ConfigParser()
    cfg.read(str(cfg_path), encoding="utf-8")

    # Ladda .env
    for env_file in (script_dir.parent / ".env", script_dir / ".env"):
        if env_file.exists():
            try:
                from dotenv import load_dotenv as _ld
                _ld(env_file, override=False)
            except ImportError:
                pass

    # Kör via subprocess för att få rätt Python-miljö
    import subprocess
    cmd = [
        sys.executable, "-c",
        (
            "import sys; sys.path.insert(0, r'" + str(script_dir) + "'); "
            "import configparser, os; "
            "from dotenv import load_dotenv; "
            f"load_dotenv(r'{script_dir.parent / '.env'}'); "
            f"load_dotenv(r'{script_dir / '.env'}', override=True); "
            "cfg = configparser.ConfigParser(); "
            f"cfg.read(r'{cfg_path}', encoding='utf-8'); "
            "import insights; "
            "print(insights.run_insights(cfg))"
        )
    ]

    print(f"\n{BLD}Insiktsanalys startar...{NRM}")
    print(f"{'─' * 56}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                cwd=str(script_dir))
        output = result.stdout.strip()
        if output:
            print(output)
        if result.stderr.strip():
            print(f"\n{GRY}{result.stderr.strip()[:500]}{NRM}")
    except Exception as e:
        print(f"{GRY}Fel: {e}{NRM}")
    print(f"{'─' * 56}")
    input(t("menu_continue"))


def run_mail(tool: dict, state: dict):
    """Custom launcher för clio-agent-mail."""
    if not tool["script"].exists():
        print(f"\nScript saknas: {tool['script']}")
        input(t("menu_continue"))
        return

    try:
        print(f"\n{BLD}  clio-agent-mail{NRM}")
        print(f"{'─' * 56}")
        print(f"  {GRN}1.{NRM} Starta daemon      (pollar kontinuerligt var 5 min)")
        print(f"  {GRN}2.{NRM} Kör ett pass nu    (--once, avslutar efteråt)")
        print(f"  {GRN}3.{NRM} Dry-run             (--dry-run, skickar inget)")
        print(f"  {GRN}4.{NRM} Vitlista            (lägg till adress i Notion)")
        print(f"  {GRN}5.{NRM} Maillogg            (senaste hanterade mail)")
        print(f"  {GRN}6.{NRM} Insiktsanalys       (analysera mönster + förutsäg frågor)")
        print(f"\n  {YEL}0.{NRM} Tillbaka")
        print(f"{'─' * 56}")
        mode = _input("\nVal [1] (0=tillbaka): ").strip() or "1"
    except BackToMenu:
        return

    if mode == "0":
        return

    if mode == "4":
        _mail_whitelist(tool, state)
        return

    if mode == "5":
        _mail_log(tool, state)
        return

    if mode == "6":
        _mail_insights(tool, state)
        return

    cmd = [sys.executable, str(tool["script"])]
    label = ""

    if mode == "1":
        label = "daemon"
    elif mode == "2":
        cmd.append("--once")
        label = "ett pass"
    elif mode == "3":
        cmd += ["--dry-run", "--once"]
        label = "dry-run"
    else:
        print("Ogiltigt val.")
        input(t("menu_continue"))
        return

    state["last_run"] = tool["name"]
    save_state(state)

    print(f"\nStartar clio-agent-mail ({label})...")
    print("─" * 40)
    start = datetime.now()
    try:
        subprocess.run(cmd, text=True, errors="replace")
    except KeyboardInterrupt:
        print("\n(Avbruten av användaren)")
    except Exception as e:
        print(f"\nFel vid körning: {e}")
    elapsed = (datetime.now() - start).seconds
    print(f"\n{'─' * 40}")
    print(t("run_done", s=elapsed))
    input(t("menu_continue"))


def _privfin_db_status(db_path: Path) -> tuple[set, dict]:
    """Returnerar (importerade_filnamn, kända_konton).
    importerade_filnamn: set av filnamn (ej sökväg) som finns i transactions.
    kända_konton: {account_id: (namn, agare, typ)}
    """
    import sqlite3 as _sq
    if not db_path.exists():
        return set(), {}
    try:
        conn = _sq.connect(db_path)
        imp = {r[0] for r in conn.execute("SELECT DISTINCT importfil FROM transactions").fetchall()}
        konton = {r[0]: (r[1], r[2], r[3])
                  for r in conn.execute("SELECT account_id, namn, agare, typ FROM accounts").fetchall()}
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
    import re as _re
    m = _re.search(r"-(\d{8,})-", fil.name)
    account_id = m.group(1) if m else None

    # Känt konto → föreslå, bekräfta med Enter
    if account_id and account_id in konton:
        namn, agare, typ = konton[account_id]
        print(f"    Konto känt: {BLD}{namn}{NRM}  [{agare}, {typ}]")
        ans = _input("    Använd dessa uppgifter? [J/n] (0=tillbaka): ").strip().lower()
        if ans in ("", "j"):
            return namn, agare, typ

    # Nytt konto eller användaren vill ändra
    konto = _input("    Kontonamn (0=tillbaka): ").strip()
    if not konto:
        return None

    print(f"    Ägare: 1=Fredrik  2=Ulrika  3=Gemensamt")
    agare_val = _input("    Ägare [1]: ").strip() or "1"
    agare = {"1": "Fredrik", "2": "Ulrika", "3": "Gemensamt"}.get(agare_val, "Fredrik")

    print(f"    Typ: 1=checking  2=savings  3=credit  4=loan")
    typ_val = _input("    Kontotyp [1]: ").strip() or "1"
    typ = {"1": "checking", "2": "savings", "3": "credit", "4": "loan"}.get(typ_val, "checking")

    return konto, agare, typ


def run_privfin(tool: dict, state: dict):
    """Custom launcher för clio-privfin — privatekonomin."""
    privfin_root = ROOT / "clio-privfin"
    import_script = privfin_root / "import.py"
    rapport_script = privfin_root / "rapport.py"
    db_path = privfin_root / "familjekonomi.db"

    RAPPORT_KOMMANDON = [
        ("media",          "Mediaprenumerationer"),
        ("el",             "Elkostnader"),
        ("okategoriserade","Transaktioner utan kategori"),
        ("sammanstallning","Översikt per kategori"),
        ("transfers",      "Interna transfereringar"),
        ("manad",          "Transaktioner per månad"),
    ]

    while True:
        clear()
        print(f"\n{BLD}  clio-privfin  —  Privatekonomi{NRM}")
        print(f"{'─' * 56}")
        print(f"  {GRN}1.{NRM} Importera kontoutdrag  (mapp eller enstaka fil)")
        print()
        for i, (cmd, desc) in enumerate(RAPPORT_KOMMANDON, 2):
            print(f"  {GRN}{i}.{NRM} {desc}")
        print(f"\n  {YEL}0.{NRM} Tillbaka\n")
        print(f"{'─' * 56}")

        try:
            val = _input("Val: ").strip()
        except BackToMenu:
            return

        if val == "1":
            # ── Välj mapp eller fil ───────────────────────────────────
            try:
                last_folder = state.get("privfin_import_folder", "")
                if last_folder:
                    short = ("..." + last_folder[-45:]) if len(last_folder) > 48 else last_folder
                    print(f"\nSenaste mapp: {YEL}{short}{NRM}")
                    ans = _input("Använd samma mapp? [J/n/ny sökväg] (0=tillbaka): ").strip()
                    if ans.lower() in ("", "j"):
                        src_path = Path(last_folder)
                    elif ans == "0":
                        raise BackToMenu()
                    else:
                        src_path = Path(ans.strip('"'))
                else:
                    raw = _input("Mapp eller fil (0=tillbaka): ").strip().strip('"')
                    src_path = Path(raw)
            except BackToMenu:
                continue

            if not src_path.exists():
                print(f"{GRY}Sökvägen hittades inte: {src_path}{NRM}")
                input(t("menu_continue"))
                continue

            # ── Enstaka fil ──────────────────────────────────────────
            if src_path.is_file():
                filer = [src_path]
                folder_str = str(src_path.parent)
            else:
                filer = _privfin_scan_folder(src_path)
                folder_str = str(src_path)
                if not filer:
                    print(f"{GRY}Inga XML/CSV-filer hittades i mappen.{NRM}")
                    input(t("menu_continue"))
                    continue

            # Spara mapp i state
            state["privfin_import_folder"] = folder_str
            save_state(state)

            # ── Hämta DB-status och gruppera ─────────────────────────
            importerade, konton = _privfin_db_status(db_path)

            nya   = [f for f in filer if f.name not in importerade]
            gamla = [f for f in filer if f.name in importerade]

            print(f"\n{'─' * 56}")
            nr_map = {}  # nummer → Path
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

            # ── Importera valda filer ────────────────────────────────
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

                # Uppdatera konton-cache för nästa fil i samma körning
                importerade_ny, konton = _privfin_db_status(db_path)
                importerade = importerade | importerade_ny

            state["last_run"] = tool["name"]
            save_state(state)
            input(t("menu_continue"))

        elif val.isdigit() and 2 <= int(val) <= len(RAPPORT_KOMMANDON) + 1:
            # ── Rapport ───────────────────────────────────────────────
            rapport_cmd, _ = RAPPORT_KOMMANDON[int(val) - 2]
            extra_args = []

            if rapport_cmd == "manad":
                try:
                    manad = _input("Månad (YYYY-MM, tomt=innevarande, 0=tillbaka): ").strip()
                except BackToMenu:
                    continue
                from datetime import date
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
            input(t("menu_continue"))

        elif val == "0":
            return


def run_obit(tool: dict, state: dict):
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
                prompt = f"  Sökväg till .ged-fil eller mapp [{last_ged}]: " if last_ged else "  Sökväg till .ged-fil eller mapp: "
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
                owner_prompt = f"  Bevakare [{last_owner}]: " if last_owner else "  Bevakare (e-post, t.ex. fredrik@arvas.se): "
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
                    cmd += ["--depth", depth_input if depth_input in ("1","2","3") else "1"]
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
                cmd = [sys.executable, str(obit_root / "sources" / "discover.py"),
                       "probe", url]
                if name_arg:
                    cmd += ["--add", name_arg]
                subprocess.run(cmd, text=True, errors="replace")

            elif mode == "8":
                import glob as _glob
                import csv as _csv
                wdir = obit_root / "watchlists"
                files = sorted(wdir.glob("*.csv"))
                if not files:
                    print("  Inga bevakningslistor hittades i watchlists/")
                else:
                    print()
                    for f in files:
                        owner = f.stem
                        rows = []
                        with open(f, newline="", encoding="utf-8") as fh:
                            for line in fh:
                                if not line.lstrip().startswith("#"):
                                    rows.append(line)
                        reader = list(_csv.DictReader(rows))
                        viktig = [r for r in reader if r.get("prioritet","").strip() == "viktig"]
                        normal = [r for r in reader if r.get("prioritet","").strip() == "normal"]
                        bav    = [r for r in reader if r.get("prioritet","").strip() == "bra_att_veta"]
                        print(f"  {BLD}{owner}{NRM}  ({len(reader)} poster)")
                        print(f"    viktig: {len(viktig)}  normal: {len(normal)}  bra_att_veta: {len(bav)}")
                        if viktig:
                            names = ", ".join(f"{r.get('fornamn','')} {r.get('efternamn','')}".strip() for r in viktig)
                            print(f"    Viktiga: {names}")
                        print()

            elif mode == "9":
                import shutil as _shutil
                import glob as _glob
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

            elif mode == "10":
                # Välj .ged-fil
                ged_dir = state.get("obit_gedcom_path", "")
                if ged_dir:
                    ged_files = sorted(Path(ged_dir).glob("*.ged"))
                else:
                    ged_files = []
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
                owner_prompt = f"  Bevakare [{last_owner}]: " if last_owner else "  Bevakare (e-post): "
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
                       "--depth", depth if depth in ("1","2","3") else "2"]
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


def run_tool(tool: dict, state: dict):
    name = tool["name"]
    needs_folder = tool.get("needs_folder", True)

    if tool.get("custom_runner"):
        if tool["name"] == "clio-research":
            run_research(tool, state)
            return
        if tool["name"] == "clio-agent-mail":
            run_mail(tool, state)
            return
        if tool["name"] == "clio-agent-obit":
            run_obit(tool, state)
            return
        if tool["name"] == "clio-privfin":
            run_privfin(tool, state)
            return

    if not tool["script"].exists():
        print(f"\nScript missing: {tool['script']}")
        input(t("menu_continue"))
        return

    folder = None
    if needs_folder:
        try:
            folder = select_folder(name, state)
        except BackToMenu:
            return
        if not folder:
            print(t("no_folder_selected"))
            input("\nPress Enter to continue...")
            return

        folder_path = Path(folder)
        if not folder_path.is_dir():
            print(f"\nFolder not found: {folder}")
            input("\nPress Enter to continue...")
            return

    # Save folder and last_run before starting
    try:
        if folder:
            state.setdefault("last_folder", {})[name] = folder
        state["last_run"] = name
        save_state(state)
    except Exception as e:
        pass  # State save failed silently

    print(f"\nStartar {name}...")
    print("─" * 40)
    start = datetime.now()

    cmd = [_python_for(tool["script"]), str(tool["script"])]
    if folder:
        cmd.append(folder)

    try:
        subprocess.run(cmd, text=True, errors="replace")
    except KeyboardInterrupt:
        print("\n(Avbruten av användaren)")
    except Exception as e:
        print(f"\nError running tool: {e}")

    elapsed = (datetime.now() - start).seconds
    print(f"\n{'─' * 40}")
    print(t("run_done", s=elapsed))

    # Update run history — always runs, even after Ctrl-C
    try:
        register_run(name, folder or "", 0, 0, state)
        save_state(state)
    except:
        pass

    input(t("menu_continue"))


def run_submenu(tool: dict, state: dict):
    """Visar undermeny för ett tool med submenu-lista."""
    while True:
        clear()
        print(f"\n{BLD}  {tool['name']}  —  {tool['desc']}{NRM}")
        print(f"{'─' * 56}")
        print()
        for item in tool["submenu"]:
            print(f"  {GRN}{item['nr']}.{NRM} {BLD}{item['name']}{NRM}")
            print(f"     {item['desc']}")
            print()
        print(f"  {YEL}0.{NRM} Tillbaka\n")
        print(f"{'─' * 56}")
        choice = input(t("menu_select")).strip().lower()
        if choice == "0":
            return
        try:
            nr = int(choice)
            match = next((i for i in tool["submenu"] if i["nr"] == nr), None)
            if match:
                run_tool(match, state)
        except ValueError:
            pass


def run_setup():
    """Guidat setup-flöde — skapar clio.config och .env."""
    config_file = ROOT / "clio.config"
    env_file    = ROOT / ".env"

    clear()
    print("\n" + "─" * 56)
    print("  Clio Setup")
    print("─" * 56)
    print()

    # Hantera befintliga filer
    existing = []
    if config_file.exists(): existing.append("clio.config")
    if env_file.exists():    existing.append(".env")
    if existing:
        print(f"  Befintliga filer hittades: {', '.join(existing)}")
        ans = input("  Skriv över dem? [j/N]: ").strip().lower()
        if ans != "j":
            print("\n  Setup avbruten. Befintliga filer är oförändrade.")
            input("\nTryck Enter för att fortsätta...")
            return

    print()
    ans = input("  Har du clio.config och .env från en befintlig installation? [j/N]: ").strip().lower()
    if ans == "j":
        print()
        print("  Kopiera dina filer manuellt:")
        print(f"    1. clio.config  →  {config_file}")
        print(f"    2. .env         →  {env_file}")
        print()
        print("  Kör sedan 'python clio.py' för att starta.")
        input("\nTryck Enter för att fortsätta...")
        return

    # Guidad ny installation
    print()
    print("  Ny installation — svara på frågorna nedan.")
    print("  (Tryck Enter för standardvärde / hoppa över)\n")

    name     = input("  Ditt namn: ").strip() or "Clio-användare"
    lang_in  = input("  Språk [sv/en, standard: sv]: ").strip().lower()
    language = lang_in if lang_in in ("sv", "en") else "sv"
    digikam  = input("  Sökväg till digikam4.db (Enter = hoppa över): ").strip()
    exiftool = input("  Sökväg till exiftool (Enter = 'exiftool' i PATH): ").strip() or "exiftool"

    print()
    print("  Notion parent page ID")
    print("  (Hitta det i Notion-URL:en: notion.so/.../DETTA-ID)")
    print("  (Lämna tomt om du inte använder Notion)")
    notion_page = input("  Notion page ID: ").strip()

    print()
    print("  Anthropic API-nyckel")
    print("  (Börjar med sk-ant-... — hämta på https://console.anthropic.com/)")
    anthropic_key = getpass.getpass("  ANTHROPIC_API_KEY: ").strip()

    print()
    print("  Notion API-nyckel (valfri)")
    print("  (Hämta på https://www.notion.so/my-integrations)")
    print("  (Glöm inte att dela dina Notion-sidor med integrationen)")
    print("  (Lämna tomt om du inte använder Notion)")
    notion_key = getpass.getpass("  NOTION_API_KEY (Enter = hoppa över): ").strip()

    # Skriv clio.config
    config_content = f"""[user]
name = "{name}"
language = "{language}"

[paths]
digikam_db = "{digikam}"
exiftool = "{exiftool}"

[notion]
parent_page_id = "{notion_page}"
"""
    config_file.write_text(config_content, encoding="utf-8")

    # Skriv .env
    env_lines = [
        f"ANTHROPIC_API_KEY={anthropic_key}",
    ]
    if notion_key:
        env_lines.append(f"NOTION_API_KEY={notion_key}")
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    print()
    print("  Filer skapade:")
    print(f"    {config_file}")
    print(f"    {env_file}")

    # Kör miljökontroll
    print()
    print("  Kontrollerar miljön...")
    try:
        _check_environment()
        print("  [OK] Miljökontrollen OK")
    except SystemExit:
        print("  (Se felmeddelande ovan — åtgärda och kör 'python clio.py' igen)")
        input("\nTryck Enter för att fortsätta...")
        return

    print()
    print("  Setup klar. Kör 'python clio.py' för att starta.")
    input("\nTryck Enter för att fortsätta...")


def run_check():
    print()
    subprocess.run([sys.executable, str(CONFIG_DIR / "clio_check.py")])
    input("\nTryck Enter för att fortsätta...")


def export_source_zip():
    """Skapar clio-source.zip med all git-spårad källkod (git archive HEAD)."""
    clear()
    print("\n" + "─" * 56)
    print("  Exportera källkod")
    print("─" * 56)
    print()

    out = ROOT / "clio-source.zip"
    result = subprocess.run(
        ["git", "archive", "HEAD", "--format=zip", f"--output={out}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  Fel: {result.stderr.strip() or 'git archive misslyckades'}")
        input("\nTryck Enter för att fortsätta...")
        return

    size_kb = out.stat().st_size // 1024
    print(f"  Klar: {out}")
    print(f"  Storlek: {size_kb} KB")
    print()
    print(f"  {GRY}Ladda upp filen till Claude chat för att diskutera källkoden.{NRM}")
    input("\nTryck Enter för att fortsätta...")

# ── Main loop ─────────────────────────────────────────────────────────────────

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    # 'python clio.py setup' — körs alltid, även utan clio.config
    if argv and argv[0] == "setup":
        run_setup()
        return

    _check_environment()   # Fail fast — tyst om OK

    state = load_state()

    while True:
        show_menu(state)
        choice = input(t("menu_select")).strip().lower()

        if choice == "q":
            print(t("menu_goodbye"))
            break
        elif choice == "c":
            run_check()
        elif choice == "e":
            export_source_zip()
        elif choice == "setup":
            run_setup()
        else:
            try:
                nr = int(choice)
                match = next((t for t in TOOLS if t["nr"] == nr), None)
                if match:
                    if "submenu" in match:
                        run_submenu(match, state)
                    else:
                        run_tool(match, state)
                else:
                    pass
            except ValueError:
                pass


if __name__ == "__main__":
    main()
