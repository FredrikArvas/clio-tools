# clio-partnerdb

Partnerdatabas med genealogiskt stöd. Hanterar bevakningslistor av personer, ägarskap, GEDCOM-import och granskningslogg (audit log).

## Körning

```powershell
python cli.py list                     # Lista alla poster
python cli.py show <id>                # Visa en post
python cli.py add                      # Lägg till ny post
python cli.py import-csv <fil.csv>     # Importera från CSV
python cli.py export-csv               # Exportera till CSV
python cli.py stats                    # Statistik
python import_gedcom.py <fil.ged>      # Importera GEDCOM-fil
```

## Beroenden

```powershell
pip install -r requirements.txt
python check_deps.py
```

## Databas

SQLite (`clio_access/partnerdb.sqlite`). Skapas automatiskt vid första körningen. Stöder schemamigrering.
