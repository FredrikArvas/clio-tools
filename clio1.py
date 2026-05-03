"""
clio1.py  — PARKERAD VERSION (fryst 2026-04-25)
Se clio2.py för aktiv version. Används som referens och fallback.

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
# Kontext-orienterad layout. Identisk med clio2.py.
# odoo_release: "R1/R2/R3" → visas som [→R1] i menyn.

CONTEXTS = [
    # ── MEDIA-TOOLS ───────────────────────────────────────────────────────────
    {"name": "MEDIA-TOOLS", "tools": [
        {
            "nr":     1,
            "name":   "clio-docs",
            "desc":   "Scanned PDFs → searchable PDF + text",
            "script": ROOT / "clio-docs" / "clio-docs-batch.py",
            "status": "active",
        },
        {
            "nr":           2,
            "name":         "clio-vision",
            "desc":         "Images → description, tags, masterdata",
            "status":       "active",
            "needs_folder": False,
            "submenu": [
                {
                    "nr":           1,
                    "name":         "analysera-bilder",
                    "desc":         "Bildanalys på mapp (Claude/Haiku/Ollama)",
                    "script":       ROOT / "clio-vision" / "clio_vision.py",
                    "needs_folder": True,
                },
                {
                    "nr":           2,
                    "name":         "digikam-browser",
                    "desc":         "Bläddra DigiKam-album, statistik",
                    "script":       ROOT / "clio-vision" / "digikam_db.py",
                    "needs_folder": False,
                },
            ],
        },
        {
            "nr":     3,
            "name":   "clio-transcribe",
            "desc":   "Audio/video → text with timestamps",
            "script": ROOT / "clio-transcribe" / "clio-transcribe-batch.py",
            "status": "active",
        },
        {
            "nr":     4,
            "name":   "clio-narrate",
            "desc":   "Text/DOCX → speech (Piper/Edge-TTS)",
            "script": ROOT / "clio-narrate" / "clio-narrate-batch.py",
            "status": "active",
        },
        {
            "nr":           5,
            "name":         "clio-audio-edit",
            "desc":         "Audio → transcribe, annotate, cut",
            "script":       ROOT / "clio-audio-edit" / "clio-audio-edit.py",
            "status":       "active",
            "needs_folder": False,
        },
    ]},

    # ── KNOWLEDGE ─────────────────────────────────────────────────────────────
    {"name": "KNOWLEDGE", "tools": [
        {
            "nr":           6,
            "name":         "clio-library",
            "desc":         "Family library — import, enrich, recommend",
            "status":       "active",
            "needs_folder": False,
            "submenu": [
                {
                    "nr":           1,
                    "name":         "import-json",
                    "desc":         "Import JSON (books + copies)",
                    "script":       ROOT / "clio-library" / "import_json.py",
                    "needs_folder": False,
                },
                {
                    "nr":           2,
                    "name":         "import-böcker",
                    "desc":         "Import books CSV → Notion",
                    "script":       ROOT / "clio-library" / "import_books.py",
                    "needs_folder": False,
                },
                {
                    "nr":           3,
                    "name":         "import-läsningar",
                    "desc":         "Import readings/ratings → Notion",
                    "script":       ROOT / "clio-library" / "import_lasningar.py",
                    "needs_folder": False,
                },
                {
                    "nr":           4,
                    "name":         "import-exemplar",
                    "desc":         "Import copies/locations → Notion",
                    "script":       ROOT / "clio-library" / "import_copies.py",
                    "needs_folder": False,
                },
                {
                    "nr":           5,
                    "name":         "prepare-import",
                    "desc":         "Prep import: GoodReads/Storytel → CSV",
                    "script":       ROOT / "clio-library" / "prepare_import.py",
                    "needs_folder": False,
                },
                {
                    "nr":           6,
                    "name":         "enrich",
                    "desc":         "Enrich year/ISBN/publisher via Google Books",
                    "script":       ROOT / "clio-library" / "enrich_books.py",
                    "needs_folder": False,
                },
                {
                    "nr":           7,
                    "name":         "match-bokid",
                    "desc":         "Fuzzy-match BOK-ID in ratings vs register",
                    "script":       ROOT / "clio-library" / "match_bokid.py",
                    "needs_folder": False,
                },
                {
                    "nr":           8,
                    "name":         "smakrådgivaren",
                    "desc":         "Book club recommendation via Notion + Claude",
                    "script":       ROOT / "clio-library" / "taste_recommender.py",
                    "needs_folder": False,
                },
                {
                    "nr":           9,
                    "name":         "library-excel",
                    "desc":         "Build library Excel from Notion",
                    "script":       ROOT / "clio-library" / "build_library_excel.py",
                    "needs_folder": False,
                },
            ],
        },
        {
            "nr":           7,
            "name":         "clio-rag",
            "desc":         "Local RAG — index docs, search with Claude",
            "status":       "active",
            "needs_folder": False,
            "submenu": [
                {
                    "nr":           1,
                    "name":         "förbered-ingest",
                    "desc":         "Prep corpus: find PDFs, register metadata",
                    "script":       ROOT / "clio-rag" / "ingest.py",
                    "args":         ["--prepare"],
                    "needs_folder": True,
                },
                {
                    "nr":           2,
                    "name":         "ingest",
                    "desc":         "Import PDFs to RAG index (Qdrant + Docling)",
                    "script":       ROOT / "clio-rag" / "ingest.py",
                    "needs_folder": True,
                },
                {
                    "nr":           3,
                    "name":         "query",
                    "desc":         "Search RAG index with Claude",
                    "script":       ROOT / "clio-rag" / "query.py",
                    "needs_folder": False,
                },
                {
                    "nr":           4,
                    "name":         "export-index",
                    "desc":         "Export RAG index to file",
                    "script":       ROOT / "clio-rag" / "export_index.py",
                    "needs_folder": False,
                },
            ],
        },
        {
            "nr":           8,
            "name":         "clio-vigil",
            "desc":         "Media monitor — RSS/YouTube → RAG",
            "status":       "active",
            "needs_folder": False,
            "odoo_release": "R3",
            "submenu": [
                {
                    "nr":           1,
                    "name":         "samla",
                    "desc":         "Collect new items (RSS + YouTube)",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--run"],
                    "needs_folder": False,
                },
                {
                    "nr":           2,
                    "name":         "transkribera",
                    "desc":         "Transcribe queue with Whisper",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--transcribe"],
                    "needs_folder": False,
                },
                {
                    "nr":           3,
                    "name":         "summera",
                    "desc":         "Summarize transcripts with Claude",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--summarize"],
                    "needs_folder": False,
                },
                {
                    "nr":           4,
                    "name":         "indexera",
                    "desc":         "Index in Qdrant (RAG)",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--index"],
                    "needs_folder": False,
                },
                {
                    "nr":           5,
                    "name":         "digest",
                    "desc":         "Send daily digest mail",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--digest"],
                    "needs_folder": False,
                },
                {
                    "nr":           6,
                    "name":         "statistik",
                    "desc":         "Show status overview per domain",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--stats"],
                    "needs_folder": False,
                },
                {
                    "nr":           7,
                    "name":         "kö",
                    "desc":         "Show transcription queue (top 20)",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--list-queued"],
                    "needs_folder": False,
                },
                {
                    "nr":           8,
                    "name":         "välj",
                    "desc":         "Pick episodes to transcribe next",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--pick"],
                    "needs_folder": False,
                },
                {
                    "nr":           9,
                    "name":         "rensa",
                    "desc":         "Clear queue and reset state",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--clear-queue"],
                    "needs_folder": False,
                },
                {
                    "nr":           10,
                    "name":         "källa",
                    "desc":         "Pick source (podcast/channel) to fetch",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--pick-source"],
                    "needs_folder": False,
                },
                {
                    "nr":           11,
                    "name":         "importera",
                    "desc":         "Import web page or PDF via URL",
                    "script":       ROOT / "clio-vigil" / "main.py",
                    "args":         ["--import-url"],
                    "needs_folder": False,
                },
            ],
        },
    ]},

    # ── AGENTS ────────────────────────────────────────────────────────────────
    {"name": "AGENTS", "tools": [
        {
            "nr":           9,
            "name":         "web-fetch",
            "desc":         "Web fetch → JSON (url/dir/file)",
            "script":       ROOT / "clio-fetch" / "clio_fetch.py",
            "status":       "active",
            "needs_folder": False,
        },
        {
            "nr":           10,
            "name":         "clio-agent-mail",
            "desc":         "AI mail — IMAP, rules, auto-reply",
            "script":       ROOT / "clio-agent-mail" / "main.py",
            "status":       "active",
            "needs_folder": False,
            "custom_runner": True,
        },
        {
            "nr":           11,
            "name":         "clio-agent-gmail",
            "desc":         "Gmail fetch — PDF attachments by sender",
            "script":       ROOT / "clio-agent-gmail" / "main.py",
            "status":       "active",
            "needs_folder": False,
            "custom_runner": True,
        },
        {
            "nr":           12,
            "name":         "emailfetch",
            "desc":         "IMAP backup → Dropbox",
            "script":       ROOT / "clio-emailfetch" / "imap_backup.py",
            "status":       "active",
            "needs_folder": False,
        },
        {
            "nr":           13,
            "name":         "clio-agent-job",
            "desc":         "Job search — career signals",
            "script":       ROOT / "clio-agent-job" / "run.py",
            "status":       "active",
            "needs_folder": False,
            "custom_runner": True,
            "odoo_release": "R1",
        },
        {
            "nr":           14,
            "name":         "clio-agent-obit",
            "desc":         "Obituary monitor — daily watch list",
            "script":       ROOT / "clio-agent-obit" / "run.py",
            "status":       "active",
            "needs_folder": False,
            "custom_runner": True,
            "odoo_release": "R2",
        },
        {
            "nr":           15,
            "name":         "clio-agent-odoo",
            "desc":         "Clio in Odoo Discuss — AI channel",
            "script":       ROOT / "clio-agent-odoo" / "run.py",
            "status":       "active",
            "needs_folder": False,
            "custom_runner": True,
        },
    ]},

    # ── ANALYSIS & DATA ───────────────────────────────────────────────────────
    {"name": "ANALYSIS & DATA", "tools": [
        {
            "nr":           16,
            "name":         "family-tree",
            "desc":         "Genealogy — GEDCOM → Wikidata → Notion",
            "script":       ROOT / "clio-research" / "research.py",
            "status":       "active",
            "needs_folder": False,
            "custom_runner": True,
        },
        {
            "nr":           17,
            "name":         "bankaccounts",
            "desc":         "Personal finance — statements, reports",
            "script":       ROOT / "clio-privfin" / "rapport.py",
            "status":       "active",
            "needs_folder": False,
            "custom_runner": True,
        },
        {
            "nr":           18,
            "name":         "clio-graph",
            "desc":         "Network graph — Odoo → Neo4j sync",
            "script":       ROOT / "clio-graph" / "run.py",
            "status":       "active",
            "needs_folder": False,
            "custom_runner": True,
        },
    ]},
]

# ── Importer från moduler ─────────────────────────────────────────────────────

from clio_menu    import load_state, show_menu, all_tools, _input, BackToMenu
from clio_runners import run_tool, run_submenu, run_setup, run_check, export_source_zip

# ── Dispatch ──────────────────────────────────────────────────────────────────

def _dispatch(raw: str, contexts: list, state: dict) -> bool:
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
        match = next((tool for tool in all_tools(contexts) if tool["nr"] == nr), None)
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
        show_menu(state, CONTEXTS, __version__, print_banner=_print_banner)
        try:
            raw = _input(t("menu_select") + " ")
        except (BackToMenu, KeyboardInterrupt):
            continue
        if not raw.strip():
            continue
        if not _dispatch(raw, CONTEXTS, state):
            break


if __name__ == "__main__":
    main()
