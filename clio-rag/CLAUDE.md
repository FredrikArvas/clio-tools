# clio-rag — CLAUDE.md

Tekniska instruktioner för Claude Code. Läs vid arbete i denna mapp.

## Vad är clio-rag

Lokalt RAG-system (Retrieval-Augmented Generation) för Arvas International.
Vektordatabas: Qdrant på EliteDesk (Tailscale: 100.107.127.104, port 6333).
Embeddings: Ollama `bge-m3` (1024 dim, cosine distance) — körs lokalt på EliteDesk.
LLM: `claude-sonnet-4-6` (via Anthropic API).

### Körmodell — skripten körs på EliteDesk

Ingest och frågor körs alltid direkt på EliteDesk, inte lokalt på Windows.
Från Claude Code på Windows: SSH in och kör skriptet där.

**Standardanslutning (LAN):**
```
ssh clioadmin@192.168.1.189
```
**Backup (Tailscale, om LAN inte når):**
```
ssh clioadmin@100.107.127.104
```

På EliteDesk är Qdrant (6333) och Ollama (11434) nåbara direkt via localhost — inga tunnlar behövs.

---

## Collections

| Collection    | Innehåll                        | Ingestion-skript     | Status     |
|---------------|---------------------------------|----------------------|------------|
| `clio_books`  | PDF-böcker och dokument         | `ingest.py`          | Aktiv      |
| `clio_ncc`    | Notion Context Cards (NCC)      | `ingest_ncc.py`      | Aktiv      |
| `clio_bible`  | 1917 års svenska bibeln         | `ingest_bible.py`    | Klar, ej indexerad |
| `clio_minne`  | Personliga minnen (Ulrika)      | `ingest_minne.py`    | Aktiv      |

Skapa collection: `python -c "from config import create_X_collection; create_X_collection()"`

---

## Skript och deras syfte

### `ingest.py` — PDF-böcker
- Läser PDF med PyMuPDF, chunkar 500 ord / 20% överlapp
- Metadataregister: `BOOK_METADATA` i `config.py` + `metadata.json`
- `--pdf path/to/book.pdf` | `--folder mapp/` | `--force`

### `ingest_bible.py` — 1917 års bibeln
- Källa: getbible.net v2 API (`swedish`, public domain)
- Flöde: `--fetch` → `corpus/bibeln_1917.json` → `--index` → Qdrant `clio_bible`
- Chunk: 10 verser, 3 överlapp, korsar aldrig bokgränser
- Payload-fält: `ext_testament`, `ext_book_code`, `ext_book_name`,
  `ext_chapter_start/end`, `ext_verse_start/end`
- `--test-fetch` verifierar API-anslutning (hämtar bara 1 Mos 1)
- `--simulate` visar chunks utan att indexera
- `--list-books` listar alla 66 böcker med kapitelantal

### `ingest_ncc.py` — Notion Context Cards
- Hämtar alla NCC från Notion (parent page `NCC_PARENT_PAGE_ID` i config)
- Re-indexerar vid ändrat `last_edited_time`

### `ingest_html.py` — HTML-sidor
- Indexerar nedladdade HTML-mappar (t.ex. SSF-webbplats)
- URL-filter: `RELEVANT_URL_PATTERNS`-lista

### `ingest_minne.py` — Personliga minnen
- Specialformat för Ulrikas minnesanteckningar

### `query.py` — Frågor
- `--q "fråga"` ger svar med källhänvisningar
- Stöd för `--collection` för att välja collection

### `config.py` — Central konfiguration
- Alla collection-namn och skapandefunktioner
- `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `LLM_MODEL`
- `get_qdrant_client()`, `is_local_available()`

### `schema/core.py` — Dataklasser
- `CorePayload`, `LocationPayload`, `BookExt`, `NccExt`, `FullPayload`
- `FullPayload.to_dict()` → platt dict för Qdrant (prefix `loc_`, `ext_`)
- `BibleExt` finns INTE som dataclass — `ingest_bible.py` bygger payload manuellt

---

## Payload-konvention (FullPayload.to_dict)

Qdrant-payloaden är ett platt dict:
- **Core-fält direkt:** `title`, `content_type`, `source_id`, `chunk_index`, ...
- **Location-fält:** prefix `loc_` → `loc_storage_tier`, `loc_local_path`, ...
- **Extension-fält:** prefix `ext_` → `ext_author`, `ext_year`, `ext_book_code`, ...

Bibel-specifika ext-fält: `ext_testament`, `ext_book_name`, `ext_book_code`,
`ext_book_idx`, `ext_chapter_start`, `ext_verse_start`, `ext_chapter_end`,
`ext_verse_end`, `ext_copyright_status`.

---

## Idempotens och om-indexering

Alla ingestion-skript är idempotenta via SHA-256:
- `ingest.py` / `ingest_ncc.py`: chunk-hash per `(source_id, chunk_index)`
- `ingest_bible.py`: chunk-hash per `chunk_key` (`BOK.K:V-K:V`)

`--force` tar bort alla befintliga punkter med samma `source_id` och indexerar om.

---

## Miljövariabler (.env)

```
ANTHROPIC_API_KEY=sk-ant-...
NOTION_TOKEN=secret_...
QDRANT_HOST=localhost
QDRANT_PORT=6333
OLLAMA_HOST=http://localhost:11434
CORPUS_PATH=/mnt/wd4tb1/clio-rag/corpus
LOCAL_DISK_MOUNT=/mnt/wd4tb1
```

På Windows dev med SSH-tunnel: `QDRANT_HOST=localhost`, `OLLAMA_HOST=http://localhost:11434`.  
`OPENAI_API_KEY` behövs inte längre.

---

## Viktiga begränsningar

- Lägg ALDRIG till nya collection-typer utan att uppdatera `config.py`
- `schema/core.py` ändras sällan — påverkar alla befintliga punkter
- `SCHEMA_VERSION` i config höjs manuellt vid strukturändring
- `ingest_bible.py` återanvänder **inte** `FullPayload` — bygger dict direkt
  (bibeln har unika ext-fält som inte passar in i `BookExt`)
