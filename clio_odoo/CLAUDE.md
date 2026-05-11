# clio_odoo — CLAUDE.md

## Syfte
Delat Odoo-kopplingsbibliotek för alla clio-odoo-* moduler. Hanterar anslutning, autentisering och grundläggande XML-RPC-operationer mot Odoo 18.

## Status
Aktiv

## Snabbstart
```python
from clio_odoo import OdooConnector, connect

connector = OdooConnector(url="...", db="...", user="...", password="...")
# eller
connector = connect()      # Läser ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD från .env
```

## Nyckelkod
- `connection.py` — OdooConnector-klass
- `__init__.py` — Offentlig API-exponering

## Beroenden
Externa: xmlrpc (stdlib)
Interna: clio-core

## Relaterade moduler
clio-core, clio-agent-odoo, clio-odoo-gsf, clio-odoo-ssfta, clio-ssf-klubb, clio-fetch-contacts, clio-neo4j

## Gotchas
Inga kända. Alla Odoo-moduler importerar härifrån — ändra inte API utan att kontrollera alla beroenden.
