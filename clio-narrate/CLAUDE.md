# clio-narrate — CLAUDE.md

## Syfte
Text-till-tal: konverterar .txt, .md och .docx-filer till MP3 med tre motoralternativ.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python clio-narrate-batch.py <fil-eller-mapp>
python clio-narrate-batch.py <fil> --engine edge     # Microsoft Edge TTS (standard, gratis)
python clio-narrate-batch.py <fil> --engine piper    # Lokal Piper (gratis, svenska)
python clio-narrate-batch.py <fil> --engine eleven   # ElevenLabs (betald, bäst kvalitet)
```

## Nyckelkod
- `clio-narrate-batch.py` — Motor-dispatcher, batch-processing

## Beroenden
Externa: edge-tts (Edge), piper-tts (Piper), elevenlabs (ElevenLabs), python-docx
Interna: clio-core

## Relaterade moduler
clio-core, clio-audio-edit, clio-transcribe

## Gotchas
Piper kräver nedladdning av röstmodell separat. ElevenLabs kräver ELEVENLABS_API_KEY i .env. Utdata: filnamn_NARRAT.mp3.
