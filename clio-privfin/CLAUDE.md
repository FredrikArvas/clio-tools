# clio-privfin — CLAUDE.md

## Syfte
Privatekonomin — importerar Danske Bank-kontoutdrag, kategoriserar och analyserar familjens utgifter med SQLite och regelbaserad kategorisering.

## Status
Aktiv

## Snabbstart
```powershell
cd clio-privfin
python import.py "F:\Dropbox\...\kontoutdrag\Danskebank\...-20260409.xml" \
    --konto "Fredriks privatkonto" --agare "Fredrik"
python rapport.py sammanstallning
```

## Nyckelkod
- `import.py` — XML/CSV-parser, SQLite-import
- `rapport.py` — Rapportgenerator
- `regler.json` — Kategoriseringsregler (redigeras direkt)
- `schema.sql` — Databasschema

## Beroenden
Externa: sqlite3, openpyxl
Interna: clio-core

## Relaterade moduler
clio-core

## Gotchas
Kategoriseringsregler är substring-match, case-insensitive — redigeras direkt i regler.json. Kontoutdrag från Danske Bank är XML-format. familjekonomi.db skapas automatiskt (gitignorerad).
