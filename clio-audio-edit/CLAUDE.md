# clio-audio-edit — CLAUDE.md

## Syfte
Transkriberar, annoterar och klipper ljudinspelningar. Använder faster-whisper för transkription, Claude API för annotationsförslag och ffmpeg för klippning.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python clio-audio-edit.py --input session.wav --profile remote_viewing
python clio-audio-edit.py --list-profiles
```

## Nyckelkod
- `clio-audio-edit.py` — CLI entry point, arbetsflöde-orchestrator
- `editor.py` — Manuell redigering av annoterat manus
- `annotate.py` — Claude-baserade annotationsförslag
- `profiles.py` — Inställningsprofiler per sessionstyp

## Beroenden
Externa: faster-whisper, subprocess (ffmpeg), anthropic
Interna: clio-core

## Relaterade moduler
clio-core, clio-transcribe, clio-narrate, clio-vigil (återanvänder Whisper-logiken)

## Gotchas
subprocess används istället för ffmpeg-python (designbeslut). Klipp skapar nya WAV-filer baserat på godkänt annoterat manus.
