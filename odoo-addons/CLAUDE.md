# odoo-addons — CLAUDE.md

## Syfte
Samling av Odoo 18-tillägg för clio-tools. Varje undermapp är en separat Odoo-app med eget __manifest__.py.

## Status
Aktiv

## Snabbstart
```bash
# Installeras i Odoo 18 (på EliteDeskGPU, Docker)
cp -r odoo-addons/* /path/to/odoo/addons/
python -m odoo -d aiab -i clio_cockpit
```

## Nyckelkod
- `clio_aiab/` — AIAB-specifik konfiguration
- `clio_cockpit/` — Dashboard för Clio-status
- `clio_discuss/` — Odoo-kanalintegration (clio-agent-odoo webhook)
- `clio_event_log/` — Händelseloggning
- `clio_graph/` — Graf-visualisering
- `clio_interview/` — Intervjuhantering
- `clio_job/` — Jobbhantering
- `clio_ncc_project/` — NCC-projektkoppling

## Beroenden
Externa: Odoo 18 Community
Interna: clio_odoo (för Python-skript utanför Odoo)

## Relaterade moduler
clio_odoo, clio-agent-odoo

## Gotchas
Ändringar i __manifest__.py kräver Odoo-omstart och modul-uppgradering: `python -m odoo -d aiab -u clio_cockpit`. clio_discuss hanterar webhook-payloaden från clio-agent-odoo — dessa måste vara synkroniserade.
