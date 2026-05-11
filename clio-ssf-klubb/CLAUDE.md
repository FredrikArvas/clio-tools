# clio-ssf-klubb — CLAUDE.md

## Syfte
Hämtar SSF-klubbar från skidor.com API, scrapar deras webbplatser för kontakter och pushar till Odoo.

## Status
Aktiv

## Snabbstart
```powershell
python main.py                         # Alla steg, alla distrikt, db=ssf
python main.py --step fetch            # Bara hämta klubbar
python main.py --step scrape           # Bara scrapa webbplatser
python main.py --step push             # Bara pusha till Odoo
python main.py --district Värmland     # Ett distrikt
python main.py --db ssf_t2             # Annan databas
```

## Nyckelkod
- `main.py` — Steg-orchestrering
- `fetch_clubs.py` — skidor.com API-klient
- `scrape_contacts.py` — Webbscrapning
- `push_to_odoo.py` — Odoo-upserter

## Beroenden
Externa: requests, xmlrpc, beautifulsoup4
Interna: clio-core, clio_odoo

## Relaterade moduler
clio-core, clio_odoo, clio-fetch-contacts

## Gotchas
Mellanfiler: clubs.json och contacts.json. Default db=ssf, åsidosätts via --db eller env ODOO_DB.
