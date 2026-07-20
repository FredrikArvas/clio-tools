# clio-audio-edit — CLAUDE.md

## Vad modulen gör

Transkriberar, annoterar och klipper ljudinspelningar i en pipeline:

```
Ljudfil → Språkdetektering → Whisper/KB-Whisper → Claude → ffmpeg
```

1. **Språkdetektering** — `faster-whisper tiny` analyserar de första 30 sek
2. **Transkribering** — väljer modell baserat på detekterat språk:
   - Svenska (`sv`) → `KBLab/kb-whisper-{small,medium,large}`
   - Övriga språk → `large-v3` (standard Whisper)
3. **Annotering** — Claude läser transkriptet och lägger in klippmarkeringar
4. **Klippning** — ffmpeg klipper originalet mot det godkända manuset

## Filer

| Fil | Ansvar |
|-----|--------|
| `clio-audio-edit.py` | CLI, mappval, filval, flödeskontroll |
| `transcribe.py` | Språkdetektering + transkribering (faster-whisper) |
| `annotate.py` | Claude API-annotering, klippförslag |
| `editor.py` | Manus-parsning, ffmpeg-klippning |
| `profiles.py` | Klipp-profiler per användningsfall |
| `state.py` | RTF-kalibrering, senaste mapp, historik |
| `check_deps.py` | Beroendevalidering |

## Modellval

```python
_KB_MODELS = {
    "small":  "KBLab/kb-whisper-small",
    "medium": "KBLab/kb-whisper-medium",
    "large":  "KBLab/kb-whisper-large",
}
_FALLBACK_MODEL = "large-v3"
```

- KB-Whisper ger upp till 47 % lägre felrate på svenska jämfört med standard-Whisper
- Modellvalet är automatiskt — ändra via `--model` (tiny/small/medium/large)

## CLI-användning

```bash
# Automatisk språkdetektering (default)
python clio-audio-edit.py --input session.wav

# Tvinga språk (om källan är känd)
python clio-audio-edit.py --input session.wav --language sv

# Utan Claude-annotering
python clio-audio-edit.py --input session.wav --no-claude

# Applicera befintligt annoterat manus
python clio-audio-edit.py --apply session_annotated.txt --input session.wav

# Lista klipp-profiler
python clio-audio-edit.py --list-profiles
```

## Stödda format

`.wav` `.mp3` `.m4a` `.ogg` `.flac` `.webm` `.mp4`

## Beroenden

```
faster-whisper>=1.0.0   # Transkribering + språkdetektering
anthropic               # Claude API för annotering
ffmpeg-python           # Python-wrapper
ffmpeg                  # Binär i PATH
python-dotenv           # .env-hantering
```

Kontroll: `python check_deps.py`

## RTF-kalibrering

Modulen mäter verklig transkriberingshastighet per modell och språk och sparar
den i `state.json` under `audio_edit_perf`. ETA-uppskattningen förbättras efter
varje körning. Historik: 10 senaste mätpunkter per modell+språk-kombination.

## Utdatafiler (skapas bredvid källfilen)

| Suffix | Innehåll |
|--------|----------|
| `_transcript.txt` | Råtranskript med tidsstämplar |
| `_annotated.txt` | Transkript med Claude-klippmarkeringar |
| `_edited.*` | Klippt ljudfil |
| `_cutlog.txt` | Lista över utförda klipp |

## Tester

```bash
pytest tests/unit/test_audio_edit_transcribe.py -v
```

Täcker: `detect_language()`, `transcribe()` med `language="auto"` (svenska →
KB-Whisper, övriga → fallback), explicit `language="sv"` oförändrat.

## NCC

Kodord: `#audioedit`
NCC: https://www.notion.so/33f67666d98a81b1ba81f1a7097820ee
