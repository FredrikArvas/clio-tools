# clio-transcribe

Batch-transkribering av ljudfiler med Whisper. Konverterar MP3, MP4, WAV, M4A, OGG, FLAC och WebM till tidsstämplad text.

## Körning

```powershell
python clio-transcribe-batch.py <fil-eller-mapp>
python clio-transcribe-batch.py <mapp> --lang sv      # Svenska (standard)
python clio-transcribe-batch.py <mapp> --model large  # Större modell
```

**Utdata:** `filnamn_TRANSKRIPT.md` med tidsstämplar per segment.

## Modeller

| Modell | Noggrannhet | Hastighet |
|---|---|---|
| small | God | Snabb |
| medium | Bättre | Medel |
| large | Bäst | Långsam |

Använder KB-Whisper för svenska, standard Whisper för övriga språk.

## Beroenden

```powershell
pip install -r requirements.txt
python check_deps.py
```
