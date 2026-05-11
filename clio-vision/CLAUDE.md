# clio-vision — CLAUDE.md

## Syfte
Bildanalys med Claude Vision API eller lokal Ollama/llava. Genererar beskrivningar, nyckelord och metadata som skrivs direkt till bildens EXIF/XMP — synlig i DigiKam.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python clio_vision.py <mapp-med-bilder>
python clio_vision.py <mapp> --engine claude      # Claude Sonnet (standard)
python clio_vision.py <mapp> --engine haiku       # Claude Haiku (snabbare)
python clio_vision.py <mapp> --engine ollama      # Lokalt (gratis)
python clio_vision.py <mapp> --no-write-back      # Analysera utan EXIF-skrivning
python clio_vision.py <mapp> --recursive          # Inkludera undermappar
```

## Nyckelkod
- `clio_vision.py` — Motor-dispatcher, vision-analys, EXIF-skrivning

## Beroenden
Externa: anthropic, piexif, requests, exiftool (lokal kopia i exiftool-13.54_64/)
Interna: clio-core

## Relaterade moduler
clio-core, clio-docs

## Gotchas
Exiftool ligger lokalt i `exiftool-13.54_64/` (gitignorerad). För Ollama: `winget install Ollama.Ollama && ollama pull llava`. DigiKam läser XMP vid "Read metadata from files".
