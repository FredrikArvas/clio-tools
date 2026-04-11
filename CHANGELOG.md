# Changelog

All notable changes to clio-tools are documented here.

Format: [version] – date – description

---

## [2.1.1] – 2026-04-11

### Fixed
- Moved repo from `Documents\git\clio-tools` to `git\clio-tools` (root user folder)
- Updated PowerShell profile: `clio` function now points to new path
- Reinstalled `clio-core` as editable install in all three Python environments:
  - System Python 3.14
  - `venv-ollama` (Python 3.12, used by clio-vision)
  - `clio-install/.venv`
- Updated Windows User PATH in registry to new location

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
