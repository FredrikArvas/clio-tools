# clio-rag

Lokalt RAG-system för böcker — subprojekt i clio-tools.  
Ställ frågor mot PDF-böcker via kommandoraden och få svar med källhänvisning (bok + sida).

## Krav

- Python 3.11+
- Qdrant i Docker (körs på EliteDesk): `docker run -p 6333:6333 qdrant/qdrant`
- API-nycklar i `.env`

## Installation

```bash
pip install -r requirements.txt
```

## .env

```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
CORPUS_PATH=/mnt/wd4tb1/clio-rag/corpus
LOCAL_DISK_MOUNT=/mnt/wd4tb1
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

## Första körning

```bash
# 1. Skapa Qdrant-collection
python -c "from config import create_collection; create_collection()"

# 2. Placera PDF-filerna i CORPUS_PATH:
#    ovillkorlig.pdf
#    egenanstallning.pdf
#    mba_umbrella_companies.pdf

# 3. Indexera
python ingest.py

# 4. Fråga
python query.py --q "Vad säger Ulrika om ovillkorlig kärlek?"

# 5. Exportera shareable index
python export_index.py
```

## Omindexering

```bash
python ingest.py --force          # tvinga om-indexering av alla böcker
python ingest.py --pdf book.pdf   # indexera enskild bok
```

## Mappstruktur

```
clio-rag/
  config.py          Inställningar, Qdrant-anslutning
  ingest.py          Ingestion-pipeline
  query.py           CLI-frågor
  export_index.py    Exportera shareable JSON-index
  requirements.txt
  schema/
    core.py          Dataklasser: CorePayload, LocationPayload, BookExt, FullPayload
  tests/
    test_ingest.py
    test_query.py
```

## Collections (ADD v1.0 §3.3)

| Collection     | Innehåll          | Status      |
|----------------|-------------------|-------------|
| clio_books     | Böcker/dokument   | MVP         |
| clio_ncc       | Notion Context Cards | Sprint 2 |
| clio_audio     | Whisper-transkript | Sprint 3   |
| clio_images    | Fotografier/grafik | Sprint 4   |
| clio_finance   | Fakturor/rapporter | Sprint 5   |
| clio_email     | Mailkorrespondens  | Sprint 6   |
