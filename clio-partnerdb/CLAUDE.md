# clio-partnerdb — CLAUDE.md

## Syfte
Partnerdatabas med genealogiskt stöd. Hanterar bevakningslistor av personer, ägarskap, GEDCOM-import och fullständig revisionslogg.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python cli.py list                     # Lista alla poster
python cli.py show <id>                # Visa en post
python cli.py add                      # Lägg till ny post
python cli.py import-csv <fil.csv>     # Importera från CSV
python cli.py export-csv               # Exportera till CSV
python cli.py stats                    # Statistik
python import_gedcom.py <fil.ged>      # Importera GEDCOM-fil
```

## Nyckelkod
- `cli.py` — CLI-interface
- `import_gedcom.py` — GEDCOM-importer

## Beroenden
Externa: gedcom, sqlite3
Interna: clio-core

## Relaterade moduler
clio-core, clio-genealogy

## Gotchas
SQLite-databas skapas automatiskt. Stöder schemamigrering. Revisionsloggen spårar all ändringshistorik.
