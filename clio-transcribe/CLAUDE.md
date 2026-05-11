# clio-transcribe — CLAUDE.md

## Syfte
Batch-transkribering av ljudfiler med Whisper. Konverterar MP3, MP4, WAV, M4A, OGG, FLAC och WebM till tidsstämplad text i Markdown.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python clio-transcribe-batch.py <fil-eller-mapp>
python clio-transcribe-batch.py <mapp> --lang sv       # Svenska (standard)
python clio-transcribe-batch.py <mapp> --model large   # Större modell (noggrannare)
```

## Nyckelkod
- `clio-transcribe-batch.py` — Whisper-transkribering, batch-processing

## Beroenden
Externa: openai-whisper, pydub
Interna: clio-core

## Relaterade moduler
clio-core, clio-audio-edit, clio-narrate, clio-vigil

## Gotchas
Använder KB-Whisper för svenska, standard Whisper för övriga språk. Utdata: filnamn_TRANSKRIPT.md med tidsstämplar per segment.
