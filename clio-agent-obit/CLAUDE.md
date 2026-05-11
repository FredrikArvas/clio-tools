# clio-agent-obit — CLAUDE.md

## Syfte
Synkroniserar dödsfallsannonser och familjeuppgifter från Geni API till lokalt register via OAuth2.

## Status
Under uppbyggnad

## Snabbstart
```powershell
python geni_auth.py         # OAuth2-setup (engång, öppnar webbläsare)
python main.py              # Hämta och synka data
```

## Nyckelkod
- `geni_auth.py` — OAuth2-autentisering (lokal callback-server)
- `geni_client.py` — Geni API-klient
- `geni_family.py` — Familjerelationslogik

## Beroenden
Externa: requests, python-dotenv
Interna: clio-core

## Relaterade moduler
clio-core, clio-graph, clio_odoo

## Gotchas
Kräver GENI_APP_ID och GENI_APP_SECRET i .env. Engångskonfiguration via geni_auth.py.
