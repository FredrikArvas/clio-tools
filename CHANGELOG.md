# Changelog

All notable changes to clio-tools are documented here.

Format: [version] – date – description

---

## [2.1.1] – 2026-04-11

### Changed
- `clio.py` delad i sex moduler för att hålla varje fil under ~300 rader (helt läsbar utan gissning):
  - `clio_menu.py` — färger, BackToMenu, _input, state-hantering, show_menu, select_folder
  - `clio_run_research.py` — GEDCOM-navigering (_scan_ged_files, select_gedcom, _search_gedcom_persons, _gedcom_has_asterisk, _pick_person) + run_research
  - `clio_run_mail.py` — mail-helpers (_mail_whitelist, _mail_log, _mail_insights) + run_mail
  - `clio_run_privfin.py` — privatekonomi-helpers (_privfin_db_status, _privfin_scan_folder, _privfin_ask_account_meta) + run_privfin
  - `clio_run_obit.py` — run_obit
  - `clio_runners.py` — run_tool, run_submenu, run_setup, run_check, export_source_zip, _python_for
- `clio.py` är nu en tunn launcher (~240 rader): .env-laddning, __version__, TOOLS-register och main()-loop
- `tests/unit/test_clio.py` uppdaterad med nya import-sökvägar och patch-targets:
  - `import clio` → `import clio_menu`, `import clio_run_research`, `import clio_runners`
  - patch-targets uppdaterade till respektive modul (t.ex. `clio_run_research.select_gedcom`)

### Rationale
clio.py var 1841 rader / ~70 KB — för stort för att läsas i ett kontextfönster. Med delningen ryms varje
modul helt i ett Read-anrop, vilket eliminerar gissningar vid framtida ändringar.

---

## [2.1.0] – 2026-03-29

### Added
- i18n support: `config/locales/sv.json` and `en.json` with 103 UI strings
- `t(key, **kwargs)` translation function in `clio_utils.py`
- Auto-detect language from environment (`LANG`, `LC_ALL`)

### Changed
- All scripts refactored to English (variables, comments, log messages)
- UI strings in clio.py and clio-narrate-batch.py now use `t()`

---

## [2.0.0] – 2026-03-29

### Added
- `clio_check.py` v2: OS detection (Windows/Mac/Linux) with platform-specific install instructions
- Automatic pip package fix with 5-second timeout prompt
- GPU detection and Whisper backend selection saved to `clio_state.json`
- Voice samples generated at `config/voice-samples/` during `clio_check`
- Piper voice download with disk space check
- ID3 tagging for all MP3 output (mutagen)
- `clio-vision-batch.py`: Ollama support as free local alternative to Claude Vision
- `clio-vision-batch.py`: DigiKam XMP integration (read face tags, write back metadata)
- File selection list in clio-narrate (choose 1,3,5 or Enter = all)
- Voice test saves samples to `filename_SAMPLES/` folder next to source file
- ElevenLabs quota check before batch run
- `◀` marker in menu for last-used tool

### Changed
- `clio-narrate-batch.py` v3: Piper, Edge-TTS and ElevenLabs as selectable engines
- Speed selection (5 levels) per narration run
- All prompts standardized to `[J/n]` / `[n/J]` bracket format
- `clio_utils.py`: added `has_non_ascii()` shared helper
- `clio.py`: shared recent-folders history across all tools

### Fixed
- Critical regex bug in `clio-docs-batch.py`: `[^-]` → `[^\x00-\x7F]` (temp was always used)
- Duplicate `**Source:**` in OCR MD metadata
- Piper WAV channel configuration error (`# channels not specified`)
- `clio_state.json` not saved when tool run was interrupted

---

## [1.2.0] – 2026-03-28

### Added
- `clio_utils.py`: `sanitize_filename()` shared across all tools
- Filename sanitation prompt before batch (remove forbidden characters)
- Heartbeat output every 30s during long OCR runs
- Sidecar-based text extraction for scanned PDFs (`--sidecar` flag)
- `--force-ocr` to handle vector-based PDFs (not just raster images)
- Temp file workaround for non-ASCII paths on Windows (OCRmyPDF limitation)
- `clio_check.py` v1: environment verification with install guidance

### Changed
- OCR encoding fix: UTF-8/Latin-1 detection for Swedish characters in sidecar
- `clio-transcribe-batch.py`: KB-Whisper auto-selected for Swedish (`KBLab/kb-whisper-medium`)

---

## [1.0.0] – 2026-03-28

### Added
- Initial release
- `clio-docs-batch.py`: batch OCR of scanned PDFs (OCRmyPDF + Tesseract)
- `clio-transcribe-batch.py`: batch audio transcription (faster-whisper)
- `clio-narrate-batch.py`: text to speech (Edge-TTS)
- `clio-vision-batch.py`: image analysis (Claude Vision API)
- `clio.py`: main menu with state persistence
- `clio_check.py`: environment check
- Project structure: clio-docs, clio-transcribe, clio-narrate, clio-vision, config, db
