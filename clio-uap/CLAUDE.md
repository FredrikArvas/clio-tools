# clio-uap

UAP Tracking — migration och CLI för Notion → Odoo 18 + Neo4j + Qdrant.

## Beroenden

- `clio_odoo/connection.py` — Odoo-anslutning via pyodoo-connect
- `clio-neo4j/` — Neo4j-synk-mönster
- `clio-rag/` — Qdrant-klientmönster
- `clio-vigil/` — RSS/YouTube-collector-mönster (Fas 5)

## Körkommandon

```bash
# Validera CSV-data
python main.py validate --path "C:\Users\fredr\Dropbox\projekt\UAP\UAP Research project"

# Importera (dry-run)
python main.py import --dry-run

# Importera till Odoo
python main.py import

# Statistik
python main.py stats

# Neo4j-sync
python main.py sync-neo4j

# Qdrant-indexering
python main.py sync-qdrant
```

## Odoo-addon

Installeras på elitedeskgpu (aiab-db):
`Apps → Uppdatera applista → Sök "UAP" → Installera`

Addons-sökväg på servern: `~/git/clio-tools/odoo-addons/`

## Källdata

`C:\Users\fredr\Dropbox\projekt\UAP\UAP Research project\`
- Incidents 2.zip — 86 encounters
- Sources 2.zip — 63 sources
- NHI-disclousreProject.zip — 25 witnesses
- VerificationLog.zip — 153 verifications
