# clio-rag

Lokalt RAG-system för Arvas International — ställ frågor mot böcker, bibeln och dokument
och få svar med exakta källhänvisningar.

**Vektordatabas:** Qdrant på EliteDesk  
**Embeddings:** Ollama bge-m3 (1024 dim, lokal)  
**LLM:** Claude Sonnet

---

## Krav

- Python 3.11+
- Qdrant i Docker (körs på EliteDesk): `docker run -p 6333:6333 qdrant/qdrant`
- Ollama på EliteDesk med bge-m3 installerad: `ollama pull bge-m3`
- API-nycklar i `.env` (se nedan)

### Körmodell

Ingest och frågor körs direkt på EliteDesk — inte lokalt på Windows.

**LAN (standard):** `ssh clioadmin@192.168.1.189`  
**Tailscale (backup):** `ssh clioadmin@100.107.127.104`

På EliteDesk är Qdrant och Ollama nåbara via localhost utan tunnlar.

## Installation

```bash
pip install -r requirements.txt
```

## .env

```
ANTHROPIC_API_KEY=sk-ant-...
NOTION_TOKEN=secret_...
QDRANT_HOST=localhost
QDRANT_PORT=6333
OLLAMA_HOST=http://localhost:11434
CORPUS_PATH=/mnt/wd4tb1/clio-rag/corpus
LOCAL_DISK_MOUNT=/mnt/wd4tb1
```

På Windows med SSH-tunnel: `QDRANT_HOST=localhost`, `OLLAMA_HOST=http://localhost:11434`.  
På EliteDesk direkt: behövs inga tunnlar.

---

## Collections

| Collection   | Innehåll                       | Skript               |
|--------------|--------------------------------|----------------------|
| `clio_books` | PDF-böcker och dokument        | `ingest.py`          |
| `clio_ncc`   | Notion Context Cards           | `ingest_ncc.py`      |
| `clio_bible` | 1917 års svenska bibeln        | `ingest_bible.py`    |
| `clio_minne` | Personliga minnen              | `ingest_minne.py`    |

---

## Böcker och dokument (`clio_books`)

```bash
# Skapa collection (första gången)
python -c "from config import create_collection; create_collection()"

# Indexera en bok
python ingest.py --pdf /path/to/book.pdf

# Indexera en mapp
python ingest.py --folder /path/to/folder/

# Tvinga om-indexering
python ingest.py --force
```

---

## 1917 års bibeln (`clio_bible`)

```bash
# Skapa collection (första gången)
python -c "from config import create_bible_collection; create_bible_collection()"

# Ladda ner bibeltexten från getbible.net (~10 min, ~31 000 verser)
python ingest_bible.py --fetch

# Indexera i Qdrant
python ingest_bible.py --index

# Verifiera att API-anslutningen fungerar (hämtar bara 1 Mos 1)
python ingest_bible.py --test-fetch

# Visa chunks utan att indexera
python ingest_bible.py --simulate

# Lista alla 66 böcker
python ingest_bible.py --list-books
```

Källfilen sparas i `corpus/bibeln_1917.json` och behöver bara laddas ner en gång.

---

## Frågor

```bash
# Fråga mot böcker
python query.py --q "Vad säger Ulrika om ovillkorlig kärlek?"

# Fråga mot bibeln
python query.py --q "Vad händer när Elia möter ängeln?" --collection clio_bible
```

---

## Mappstruktur

```
clio-rag/
  config.py           Inställningar, Qdrant-anslutning, collection-definitioner
  ingest.py           PDF-böcker och dokument
  ingest_bible.py     1917 års svenska bibeln
  ingest_ncc.py       Notion Context Cards
  ingest_html.py      HTML-sidor
  ingest_minne.py     Personliga minnen
  query.py            CLI-frågor mot alla collections
  export_index.py     Exportera shareable JSON-index
  requirements.txt
  corpus/             Källfiler (PDF, bibeln_1917.json m.m.)
  schema/
    core.py           Dataklasser: CorePayload, LocationPayload, BookExt, FullPayload
  tests/
    test_ingest.py
    test_query.py
```
