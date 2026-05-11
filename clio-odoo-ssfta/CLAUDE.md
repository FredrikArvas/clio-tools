# clio-odoo-ssfta — CLAUDE.md

## Syfte
Synkroniserar SSF-tävlingsdata, funktionärer, tävlingsresultat och FIS-ranking från externa källor till Odoo-databasen ssf_t2.

## Status
Aktiv

## Snabbstart
```powershell
python run_full_sync.py                      # Kör alla synkar
python assign_groups.py                      # Tilldela IAM-grupper
python sync_competition_meta.py              # Bara tävlingsmetadata
python sync_competition_results.py           # Bara resultat
```

## Nyckelkod
- `run_full_sync.py` — Full sync-dispatcher
- `assign_groups.py` — IAM-grupptilldelning
- `sync_competition_meta.py` — Tävlingsmetadata
- `sync_competition_results.py` — Tävlingsresultat
- `sync_fis_from_results.py` — FIS-ranking
- `sync_functionaries.py` — Funktionärsdatabas

## Beroenden
Externa: xmlrpc, requests
Interna: clio-core, clio_odoo

## Relaterade moduler
clio-core, clio_odoo

## Gotchas
Kräver Odoo-anslutning för db=ssf_t2. Synkar kan köras isolerat eller tillsammans via run_full_sync.py.
