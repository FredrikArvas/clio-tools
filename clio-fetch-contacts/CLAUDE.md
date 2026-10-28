# clio-fetch-contacts — CLAUDE.md

## Syfte
Scrapar styrelse och ledning från bolagswebbplatser, extraherar personer med Claude och importerar till Odoo som res.partner.

## Status
Aktiv

## Snabbstart
```powershell
python main.py --company norion --url https://norionbank.se/om-oss/styrelse/
python main.py --company lindab --url https://... --dry-run
python main.py --company norion --step push --db aiab
```

## Nyckelkod
- `main.py` — CLI entry point, steg-orchestrering (fetch → parse → push)

## Beroenden
Externa: requests, anthropic, xmlrpc
Interna: clio-core, clio_odoo

## Relaterade moduler
clio-core, clio_odoo, clio-ssf-klubb, clio-fetch

## Gotchas
Pipeline: fetch hämtar HTML, parse extraherar personer med Claude, push upserterar res.partner. Kan skapa moderbolag med --create-parent. 41 kontakter inne (Norion+Lindab) per 2026-04-xx.
