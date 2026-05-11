# clio-docs — CLAUDE.md

## Syfte
Batch-OCR av inscannade PDF-filer. Konverterar PDF till sökbar PDF med textlager och extraherar text som Markdown.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python clio-docs-batch.py <mapp-med-pdfer>
python clio-docs-batch.py <mapp> --lang swe+eng
```

## Nyckelkod
- `clio-docs-batch.py` — OCR-pipeline, Tesseract-integration
- `CODING_STANDARD.md` — Kodstandard för hela clio-tools (läs vid kodarbete)

## Beroenden
Externa: pytesseract, pdf2image, Tesseract OCR (systemberoende)
Interna: clio-core

## Relaterade moduler
clio-core, clio-vision

## Gotchas
Kräver Tesseract installerat: `winget install UB-Mannheim.TesseractOCR`. Standard är swe+eng. Hanterar icke-ASCII-filnamn automatiskt. Se CODING_STANDARD.md för hela clio-tools kodstandard.
