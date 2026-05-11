# clio-odoo-gsf — CLAUDE.md

## Syfte
Importerar och uppdaterar GSF-ägare från Excel till Odoo res.partner. Upserterar baserat på ref="gsf-{Unikt ID}".

## Status
Aktiv

## Snabbstart
```powershell
python sync_agare.py <xlsx-fil>              # Live
python sync_agare.py <xlsx-fil> --dry-run    # Ingen skrivning
```

## Nyckelkod
- `sync_agare.py` — Excel-parser, Odoo-upserter

## Beroenden
Externa: openpyxl, xmlrpc
Interna: clio-core, clio_odoo

## Relaterade moduler
clio-core, clio_odoo

## Gotchas
Upsert-nyckel: ref="gsf-{Unikt ID}". Kräver ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD i .env.
