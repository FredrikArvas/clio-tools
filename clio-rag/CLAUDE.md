# clio-rag — CLAUDE.md

## Syfte
Lokalt RAG-system. Ställ frågor mot PDF-böcker och dokumentsamlingar via kommandoraden och få svar med källhänvisning (dokument + sida).

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python -c "from config import create_collection; create_collection()"
python ingest.py                       # Indexera corpus
python query.py --q "Din fråga här" --collection cap_ssf --top 6
python ingest.py --force               # Tvinga om-indexering
```

## Nyckelkod
- `config.py` — Qdrant-anslutning och inställningar
- `ingest.py` — Ingestion-pipeline (Docling + Qdrant)
- `query.py` — CLI-frågor
- `schema/core.py` — Dataklasser

## Beroenden
Externa: qdrant-client, anthropic, docling
Interna: clio-core

## Relaterade moduler
clio-core, clio-rag-mcp, clio-vigil

## Gotchas
Kräver Qdrant via Docker på EliteDeskGPU: `docker run -p 6333:6333 qdrant/qdrant`. Kräver ANTHROPIC_API_KEY i .env. Samlingar: cap_ssf (216 chunks), vigil_ai, vigil_ufo.
