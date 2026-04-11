# clio-tools

A suite of tools for digitizing, transcribing, researching and making content searchable.

Built by Fredrik Arvas / Arvas International AB together with Clio (Claude, Anthropic).

---

## Quick start

**Ny installation**
```powershell
git clone https://github.com/FredrikArvas/clio-tools.git
cd clio-tools
python clio-install/install.py --venv --yes --check
# Fyll i ANTHROPIC_API_KEY i .env när installern är klar
```

**Flytta från en befintlig maskin**
```powershell
# På den gamla maskinen — exportera inställningar
python clio-install/env_transfer.py --export
# Kopiera clio-env-transfer.zip manuellt till nya maskinen

# På nya maskinen
git clone https://github.com/FredrikArvas/clio-tools.git
cd clio-tools
python clio-install/env_transfer.py --import clio-env-transfer.zip
python clio-install/install.py --venv --yes --check
```

Se `clio-install/README.md` för fullständig dokumentation.

Run `python config/clio_check.py` for a full dependency check with auto-fix for pip packages.

---

## Tools

### Media & documents

| Tool | Description | Status |
|---|---|---|
| **clio-docs** | Scanned PDFs → searchable PDF + text (OCRmyPDF + Tesseract) | ✅ Active |
| **clio-transcribe** | Audio/video → text with timestamps (faster-whisper, KB-Whisper) | ✅ Active |
| **clio-narrate** | Text/DOCX → speech — Piper, Edge-TTS, ElevenLabs | ✅ Active |
| **clio-audio-edit** | Audio recordings → transcribe, annotate with Claude, cut with ffmpeg | ✅ Active |
| **clio-vision** | Images → description, tags, metadata (Claude Vision or Ollama) | ✅ Active |

### Data & research

| Tool | Description | Status |
|---|---|---|
| **clio-fetch** | Web pages / HTTrack archives → cleaned JSON | ✅ Active |
| **clio-research** | Person research via Wikipedia, Wikidata, Libris → Notion | ✅ Active |
| **clio-library** | Notion book database — enrich, import, smakrådgivare (book club recommender) | ✅ Active |
| **clio-rag** | Local RAG for book corpus — ingest PDFs, query with Claude (Qdrant) | ✅ Active |
| **clio-partnerdb** | Family history database — GEDCOM import, graph queries | ✅ Active |

### Agents & automation

| Tool | Description | Status |
|---|---|---|
| **clio-agent-mail** | Incoming email agent — classify, respond, manage whitelist/blacklist | ✅ Active |
| **clio-agent-obit** | Obituary monitor — watch for named individuals across funeral sources | ✅ Active |
| **clio-emailfetch** | IMAP email backup to Dropbox | ✅ Active |

### Finance & system

| Tool | Description | Status |
|---|---|---|
| **clio-privfin** | Personal finance — import bank statements, categorize, report | ✅ Active |
| **clio-powershell** | PowerShell environment setup for clio-tools on Windows | ⚠️ Partial |

---

## Structure

```
clio-tools/
  ├── clio-audio-edit/     ← transcribe + annotate + cut audio (faster-whisper + Claude + ffmpeg)
  ├── clio-docs/           ← PDF OCR pipeline
  ├── clio-fetch/          ← web page fetching → JSON
  ├── clio-library/        ← Notion book database, enrichment, smakrådgivare
  ├── clio-narrate/        ← text to speech (Piper / Edge-TTS / ElevenLabs)
  ├── clio-partnerdb/      ← family history DB (GEDCOM import, graph)
  ├── clio-rag/            ← RAG for book corpus (Qdrant + Docling + Claude)
  ├── clio-research/       ← person research → Notion
  ├── clio-transcribe/     ← audio transcription (faster-whisper)
  ├── clio-vision/         ← image analysis (Claude Vision / Ollama + DigiKam)
  ├── clio-agent-mail/     ← email agent (IMAP poll, classify, respond)
  ├── clio-agent-obit/     ← obituary monitor
  ├── clio-emailfetch/     ← IMAP backup to Dropbox
  ├── clio-privfin/        ← personal finance
  ├── clio-powershell/     ← Windows PowerShell setup
  ├── clio-core/           ← shared library (banner, utils, locales)
  ├── clio-install/        ← installer, uninstaller, env_transfer
  ├── clio_access/         ← Notion data access layer
  ├── config/
  │   ├── clio_check.py    ← environment setup & dependency check
  │   ├── clio_utils.py    ← shared utilities
  │   ├── clio_state.json  ← remembered settings (auto-generated)
  │   ├── piper-voices/    ← local TTS voice models
  │   └── voice-samples/   ← TTS test clips
  ├── tests/
  │   ├── unit/            ← fast mocked tests (<5s)
  │   ├── system/          ← integration tests (Tesseract, internet)
  │   └── uat/             ← manual checklist before release
  ├── db/                  ← shared SQLite database (planned)
  ├── clio.py              ← main menu
  ├── clio_menu.py         ← menu rendering and navigation
  ├── clio_runners.py      ← generic run helpers
  ├── clio_run_*.py        ← per-tool launchers
  ├── requirements.txt
  └── README.md
```

---

## Tests

```bash
python tests/run_tests.py            # unit tests only (fast, <5s)
python tests/run_tests.py --system   # system tests (Tesseract, internet)
python tests/run_tests.py --all      # everything
python tests/run_tests.py -v utils   # single suite, verbose
```

The pre-commit hook in `.githooks/pre-commit` runs unit tests automatically. Activate with:

```bash
git config core.hooksPath .githooks
```

---

## Dependencies

### Required
- **Python 3.12+** – python.org
- **Tesseract OCR** – used by clio-docs and clio-vision
- **ffmpeg** – used by clio-narrate and clio-audio-edit
- **pip packages** – installed via `pip install` (see Quick start)

### Optional
- **exiftool** – image metadata for clio-vision
- **Ollama** – local alternative to Claude Vision in clio-vision
- **Docker** – runs Qdrant for clio-rag: `docker run -p 6333:6333 qdrant/qdrant`

### API keys
- `ANTHROPIC_API_KEY` – Claude API (clio-vision, clio-audio-edit, clio-agent-mail, clio-fetch, clio-narrate, clio-research, clio-rag)
- `ELEVENLABS_API_KEY` – ElevenLabs TTS in clio-narrate
- `NOTION_TOKEN` – Notion integration (clio-library, clio-agent-mail, clio-research)

Run `python config/clio_check.py` for full guidance on your platform.

---

## Three ways to work with Claude

| | Claude.ai | Claude Code | Python local |
|---|---|---|---|
| Persistent | No | Yes | Yes |
| Token cost | Yes | Yes | No |
| Your filesystem | No | Yes | Yes |
| Schedulable | No | Yes | Yes |
| Best for | Design + build | Test + debug | Production |

**Rule of thumb:** Design in chat, test in Claude Code, run production as plain Python scripts.

---

## Naming conventions

Output files use suffixes to distinguish them from originals:

| Suffix | Tool | Description |
|---|---|---|
| `_OCR.pdf` | clio-docs | Searchable PDF |
| `_OCR.md` | clio-docs | Extracted text |
| `_TRANSKRIPT.md` | clio-transcribe | Transcript with timestamps |
| `_NARRAT.mp3` | clio-narrate | Audio file |
| `_SAMPLES/` | clio-narrate | Voice test clips |
| `_VISION.md` | clio-vision | Image analysis |
| `_transcript.txt` | clio-audio-edit | Raw transcript |
| `_annotated.txt` | clio-audio-edit | Claude-annotated cut list |
| `_edited.wav` | clio-audio-edit | Cut audio file |
| `_cutlog.txt` | clio-audio-edit | Cut documentation |
