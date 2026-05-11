# clio-neo4j — CLAUDE.md

## Syfte
Synkroniserar bevakade kontakter och familjerelationer från Odoo till Neo4j-grafdatabasen. Idempotent via MERGE.

## Status
Aktiv

## Snabbstart
```powershell
python sync_odoo_to_neo4j.py
python sync_odoo_to_neo4j.py --dry-run
python sync_odoo_to_neo4j.py --clear    # Tar bort alla Clio-noder först
```

## Nyckelkod
- `sync_odoo_to_neo4j.py` — Odoo → Neo4j synkronisering

## Beroenden
Externa: neo4j, xmlrpc
Interna: clio-core, clio_odoo, clio-graph

## Relaterade moduler
clio-core, clio_odoo, clio-graph

## Gotchas
MERGE gör operationen idempotent — kan köras flera gånger säkert. Kräver NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD + Odoo-inställningar i .env.
