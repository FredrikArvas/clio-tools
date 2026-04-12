"""
clio.py
Tunn launcher för clio-tools. All logik finns i separata moduler:
  clio_menu.py          — färger, state, menyvisning, select_folder
  clio_run_research.py  — GEDCOM-navigering, run_research
  clio_run_mail.py      — mail-helpers, run_mail
  clio_run_privfin.py   — privatekonomi-helpers, run_privfin
  clio_run_obit.py      — dödsannonsbevakning, run_obit
  clio_runners.py       — run_tool, run_submenu, run_setup, run_check, export_source_zip

Usage:
    python clio.py
    python clio.py setup
"""

import os
import sys
from pathlib import Path

# Sätt UTF-8 på stdout/stderr så att box-tecken och unicode fungerar i Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ladda .env så att alla subtools ärver API-nycklar
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv(_env_file, override=True)
    except ImportError:
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ[_k.strip()] = _v.strip()

__version__ = "2.1.1"

ROOT       = Path(__file__).parent
CONFIG_DIR = ROOT / "config"
STATE_FILE = CONFIG_DIR / "clio_state.json"

try:
    from clio_env import check_environment as _check_environment
except ImportError:
    def _check_environment(**kwargs): pass

try:
    from config.clio_utils import t, set_language
except ImportError:
    def t(key, **kwargs): return key

try:
    from clio_core.banner import print_banner as _print_banner
except ImportError:
    _print_banner = None

# ── Verktygsregister ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "nr":     1,
        "name":   "clio-docs",
        "desc":   "Skannade PDF:er → sökbar PDF + text",
        "script": ROOT / "clio-docs" / "clio-docs-batch.py",
        "status": "active",
    },
    {
        "nr":           2,
        "name":         "clio-vision",
        "desc":         "Bilder → beskrivning, taggar och masterdata",
        "status":       "active",
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
        "nr":     5,
        "name":   "clio-audio-edit",
        "desc":        "Ljud → transkribera, annotera och klipp (paper edit)",
        "script":      ROOT / "clio-audio-edit" / "clio-audio-edit.py",
        "status":      "active",
        "needs_folder": False,
    },
    {
        "nr":           6,
        "name":         "clio-library",
        "desc":         "Arvas Familjebibliotek — import, berikning, rekommendation",
        "status":       "active",
        "needs_folder": False,
        "submenu": [
            {
                "nr":           1,
                "name":         "import-json",
                "desc":         "Importera JSON (böcker + exemplar i ett svep)",
                "script":       ROOT / "clio-library" / "import_json.py",
                "needs_folder": False,
            },
            {
                "nr":           2,
                "name":         "import-böcker",
                "desc":         "Importera böcker till Bokregistret (CSV → Notion)",
                "script":       ROOT / "clio-library" / "import_books.py",
                "needs_folder": False,
            },
            {
                "nr":           3,
                "name":         "import-läsningar",
                "desc":         "Importera läsningar/betyg till Betygstabellen (CSV → Notion)",
                "script":       ROOT / "clio-library" / "import_lasningar.py",
                "needs_folder": False,
            },
            {
                "nr":           4,
                "name":         "import-exemplar",
                "desc":         "Importera exemplar/platser till Exemplar-tabellen (CSV → Notion)",
                "script":       ROOT / "clio-library" / "import_copies.py",
                "needs_folder": False,
            },
            {
                "nr":           5,
                "name":         "prepare-import",
                "desc":         "Förbered import — konverterar GoodReads/Storytel-export till CSV",
                "script":       ROOT / "clio-library" / "prepare_import.py",
                "needs_folder": False,
            },
            {
                "nr":           6,
                "name":         "enrich",
                "desc":         "Berika med år, ISBN och förlag via Google Books",
                "script":       ROOT / "clio-library" / "enrich_books.py",
                "needs_folder": False,
            },
            {
                "nr":           7,
                "name":         "match-bokid",
                "desc":         "Fuzzy-matcha BOK-ID i Betygstabellen mot Bokregistret",
                "script":       ROOT / "clio-library" / "match_bokid.py",
                "needs_folder": False,
            },
            {
                "nr":           8,
                "name":         "smakrådgivaren",
                "desc":         "Bokklubbsrekommendation via Notion + Claude",
                "script":       ROOT / "clio-library" / "taste_recommender.py",
                "needs_folder": False,
            },
            {
                "nr":           9,
                "name":         "library-excel",
                "desc":         "Bygg biblioteks-Excel från Notion",
                "script":       ROOT / "clio-library" / "build_library_excel.py",
                "needs_folder": False,
            },
        ],
    },
    {
        "nr":           7,
        "name":         "clio-emailfetch",
        "desc":         "IMAP-backup av e-post till Dropbox",
        "script":       ROOT / "clio-emailfetch" / "imap_backup.py",
        "status":       "active",
        "needs_folder": False,
    },
    {
        "nr":           8,
        "name":         "clio-fetch",
        "desc":         "Webbhämtning → JSON  (--url URL | --dir mapp | --file fil)",
        "script":       ROOT / "clio-fetch" / "clio_fetch.py",
        "status":       "active",
        "needs_folder": False,
    },
    {
        "nr":           9,
        "name":         "clio-research",
        "desc":         "Släktforskning — GEDCOM → Wikidata → Wikipedia → Notion",
        "script":       ROOT / "clio-research" / "research.py",
        "status":       "active",
        "needs_folder": False,
        "custom_runner": True,
    },
    {
        "nr":           10,
        "name":         "clio-agent-mail",
        "desc":         "AI-mailhantering — IMAP-polling, regelmotor, svarsgenerering",
        "script":       ROOT / "clio-agent-mail" / "main.py",
        "status":       "active",
        "needs_folder": False,
        "custom_runner": True,
    },
    {
        "nr":           11,
        "name":         "clio-agent-obit",
        "desc":         "Dödsannonsbevakning — daglig kontroll mot bevakningslista",
        "script":       ROOT / "clio-agent-obit" / "run.py",
        "status":       "active",
        "needs_folder": False,
        "custom_runner": True,
    },
    {
        "nr":           12,
        "name":         "clio-privfin",
        "desc":         "Privatekonomin — importera kontoutdrag, kategorisera, rapporter",
        "script":       ROOT / "clio-privfin" / "rapport.py",
        "status":       "active",
        "needs_folder": False,
        "custom_runner": True,
    },
    {
        "nr":           13,
        "name":         "clio-rag",
        "desc":         "Lokal RAG — indexera böcker/dokument, sök med Claude (Qdrant)",
        "status":       "active",
        "needs_folder": False,
        "submenu": [
            {
                "nr":           1,
                "name":         "ingest",
                "desc":         "Importera PDF-dokument till RAG-indexet (Qdrant + Docling)",
                "script":       ROOT / "clio-rag" / "ingest.py",
                "needs_folder": True,
            },
            {
                "nr":           2,
                "name":         "query",
                "desc":         "Sök i RAG-indexet med Claude",
                "script":       ROOT / "clio-rag" / "query.py",
                "needs_folder": False,
            },
            {
                "nr":           3,
                "name":         "export-index",
                "desc":         "Exportera RAG-index till fil",
                "script":       ROOT / "clio-rag" / "export_index.py",
                "needs_folder": False,
            },
        ],
    },
]

# ── Importer från moduler ─────────────────────────────────────────────────────

from clio_menu    import load_state, show_menu, _input, BackToMenu
from clio_runners import run_tool, run_submenu, run_setup, run_check, export_source_zip

# ── Dispatch ──────────────────────────────────────────────────────────────────

def _dispatch(raw: str, tools: list, state: dict) -> bool:
    """Returnerar False om loopen ska avslutas."""
    val = raw.strip().lower()
    if val in ("q", "quit", "exit"):
        print(t("menu_goodbye"))
        return False
    if val == "c":
        run_check()
    elif val == "e":
        export_source_zip()
    elif val.isdigit():
        nr = int(val)
        match = next((tool for tool in tools if tool["nr"] == nr), None)
        if match:
            if "submenu" in match:
                run_submenu(match, state)
            else:
                run_tool(match, state)
    return True


# ── Huvudloop ─────────────────────────────────────────────────────────────────

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] == "setup":
        run_setup()
        return

    _check_environment()

    state = load_state()

    while True:
        show_menu(state, TOOLS, __version__, print_banner=_print_banner)
        try:
            raw = _input(t("menu_select") + " ")
        except (BackToMenu, KeyboardInterrupt):
            continue
        if not raw.strip():
            continue
        if not _dispatch(raw, TOOLS, state):
            break


if __name__ == "__main__":
    main()
