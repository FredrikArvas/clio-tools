# clio-tools

A suite of tools for digitizing, transcribing, and making content searchable.

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

| Tool | Description | Status |
|---|---|---|
| **clio-docs** | Scanned PDFs → searchable PDF + text | ✅ Active |
| **clio-transcribe** | Audio/video → text with timestamps | ✅ Active |
| **clio-narrate** | Text/DOCX → speech (audiobook) | ✅ Active |
| **clio-vision** | Images → description, tags, metadata | ✅ Active |
| **clio-fetch** | Web pages / HTTrack archives → JSON | ✅ Active |
| **clio-library** | Notion book database → enrich with Google Books metadata | ✅ Active |
| **clio-emailfetch** | IMAP email backup to Dropbox | ✅ Active |
| **clio-privfin** | Privatekonomi — importera kontoutdrag, kategorisera, rapporter | ✅ Active |

---

## Structure

```
clio-tools/
  ├── clio-docs/           ← PDF OCR pipeline
  ├── clio-transcribe/     ← audio transcription
  ├── clio-narrate/        ← text to speech
  ├── clio-vision/         ← image analysis
  ├── clio-fetch/          ← web page fetching → JSON
  ├── clio-library/        ← Notion book database enrichment (Google Books)
  ├── clio-emailfetch/     ← IMAP email backup to Dropbox
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
- **Tesseract OCR** – see `clio_check.py` for platform-specific instructions
- **pip packages** – installed via `pip install` (see Quick start)

### Optional but recommended
- **ffmpeg** – MP3 output for clio-narrate (see `clio_check.py`)
- **exiftool** – image metadata for clio-vision (see `clio_check.py`)

### API keys (set as environment variables)
- `ANTHROPIC_API_KEY` – for clio-vision (Claude Vision)
- `ELEVENLABS_API_KEY` – for ElevenLabs TTS in clio-narrate
- `NOTION_TOKEN` – for clio-library (set via `python clio-library/setup_credentials.py`)

Run `python config/clio_check.py` for full guidance on your platform.

---

## Three ways to work with Claude

| | Claude.ai | Claude Code (PS) | Python local |
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
| `_VISION.md` | clio-vision | Image analysis |
| `_SAMPLES/` | clio-narrate | Voice test clips |
