# clio-fetch — CLAUDE.md

## Syfte
Webb-hämtare: laddar ned URL:er, sparar HTML/text och kan skicka innehållet till Claude för analys och sammanfattning.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python clio_fetch.py <url>
python clio_fetch.py <url> --analyse    # Skicka till Claude
python clio_fetch.py <url> --clean      # Flytta gamla filer till papperskorgen
```

## Nyckelkod
- `clio_fetch.py` — HTTP-hämtare, Claude-integration

## Beroenden
Externa: requests, anthropic
Interna: clio-core

## Relaterade moduler
clio-core, clio-fetch-contacts, clio-ssf-klubb

## Gotchas
Kräver ANTHROPIC_API_KEY i .env för Claude-analys. Sparar HTML och text lokalt för senare bearbetning.
