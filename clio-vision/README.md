# clio-vision

Bildanalys med Claude Vision API eller lokal Ollama/llava. Genererar beskrivningar, nyckelord och metadata som skrivs direkt till bildens EXIF/XMP — synlig i DigiKam.

## Körning

```powershell
python clio_vision.py <mapp-med-bilder>
python clio_vision.py <mapp> --engine claude   # Claude Sonnet (standard)
python clio_vision.py <mapp> --engine haiku    # Claude Haiku (snabbare)
python clio_vision.py <mapp> --engine ollama   # Lokalt via Ollama/llava (gratis)
python clio_vision.py <mapp> --no-write-back   # Analysera utan att skriva metadata
python clio_vision.py <mapp> --recursive       # Inkludera undermappar
```

**Utdata:** `bildnamn_VISION.md` + XMP-metadata inbäddad i bildfilen.

## Beroenden

```powershell
pip install -r requirements.txt
python check_deps.py
```

Kräver exiftool (lokal kopia finns i `exiftool-13.54_64/`).
För Ollama: `winget install Ollama.Ollama` + `ollama pull llava`.

## DigiKam-flöde

Clio skriver till bildens XMP → DigiKam läser vid "Read metadata from files" → databasen uppdateras.

## Konfiguration

Kräver `ANTHROPIC_API_KEY` i `.env` för Claude-motorer.
