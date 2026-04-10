# clio-docs

Batch-OCR av inscannade PDF-filer. Konverterar till sökbara PDF:er med textlager och extraherar text som Markdown.

## Körning

```powershell
python clio-docs-batch.py <mapp-med-pdfer>
python clio-docs-batch.py <mapp> --lang swe+eng
```

**Utdata per fil:**
- `filnamn_OCR.pdf` — sökbar PDF med textlager
- `filnamn_OCR.md` — extraherad text som Markdown

## Beroenden

```powershell
pip install -r requirements.txt
python check_deps.py
```

Kräver även Tesseract OCR installerat på systemet:
```powershell
winget install UB-Mannheim.TesseractOCR
```

## Konfiguration

Standardspråk: svenska + engelska (`swe+eng`). Hantering av icke-ASCII-filnamn ingår automatiskt.
