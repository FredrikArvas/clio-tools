# clio-vigil — CLAUDE.md

Medieövervakningspipeline: RSS, YouTube, webb → filter → transkription → RAG → digest.

## Körningsläge

**Server:** `clioadmin@100.107.127.104`
**Aktiv sökväg:** `~/19.0/clio-tools/clio-vigil/` (branch `19.0`, enda aktiva branchen)
**Schemaläggning:** systemd-timer `clio-vigil.service` — kör `--full --all-domains --max 10` dagligen 06:30

```bash
cd ~/19.0/clio-tools/clio-vigil
python main.py --run --domain ufo          # Samla in + filtrera
python main.py --transcribe --max 5        # Transkribera (GPU, Whisper)
python main.py --summarize --max 10        # Summera (Claude)
python main.py --index --max 10            # Indexera (Qdrant)
python main.py --digest                    # Skicka digest-mail
python main.py --full --all-domains        # Hela pipeline
python main.py --stats                     # Statistik
```

## Dataarkitektur (tre lager)

```
SQLite vigil.db           ← kanonisk pipeline-state (kör på server)
    ↓ sync_items_from_conn()
clio.vigil.item (Odoo)    ← pipeline-objekt, state machine, prioritet, transkript
    ↑ vigil_item_id
clio.media.article (Odoo) ← redaktionellt arkiv (lobbying, journalister, research)
```

**Viktig regel:** `clio.vigil.item` är sanningskällan i Odoo. `clio.media.article` innehåller
INTE egna vigil-fält — all vigil-data nås via `vigil_item_id`-länken.

## Källkonfiguration

**Källor lagras i Odoo** (`clio.vigil.source`) — inte i YAML.
`run_pipeline()` läser från Odoo via `read_sources(odoo_env, domain_id)`.
YAML (`config/ufo.yaml`) används bara för domänmetadata: keywords, thresholds, whisper_model.

Aktiva UFO-källor (2026-07-19): 29 st (13 rss, 7 youtube, 5 google_news, 3 web, 1 facebook)

## Odoo-modeller

| Modell | Syfte |
|---|---|
| `clio.vigil.source` | Bevakningskällor med source_type, channel_id, google_news_query m.m. |
| `clio.vigil.item` | Pipeline-objekt: state, relevance_score, priority_score, transcript_snippet |
| `clio.media.article` | Redaktionellt arkiv med `vigil_item_id → clio.vigil.item` |

## Nyckelnycklar — odoo_writer.py

- `read_sources(env, domain)` — hämtar aktiva källor från Odoo
- `build_sources_config(sources)` — konverterar till collectors-format
- `sync_items_from_conn(env, conn)` — upsert SQLite → clio.vigil.item
- `sync_items_to_media(env, conn)` — upsert basdata + vigil_item_id → clio.media.article
- `write_heartbeat(env, status, count, message)` — agenthälsa
- `write_sources(env, sources)` — upsert källor till clio.vigil.source

## Tillståndskedja

```
discovered → filtered_in / filtered_out
           → queued
           → downloaded        (audio nedladdad)
           → transcribing / transcribed / captioned
           → uap_classified
           → indexed
           → notified
           → failed            (markeras och hoppas över — blockerar inte kön)
```

## Collectors

| Modul | Trigger |
|---|---|
| `collectors/rss_collector.py` | RSS + Google News, läser `domain_config["sources"]["rss"]` |
| `collectors/youtube_collector.py` | yt-dlp, läser `domain_config["sources"]["youtube_channels"]` (kräver `channel_id`) |
| `collectors/google_news_collector.py` | Google News RSS, läser `domain_config["sources"]["google_news"]` |

## Gotchas

- YouTube-källors `channel_id` måste vara satt i Odoo (t.ex. `@theblackvault`) — annars ger yt-dlp HTTP 400
- Spotify-källors URL fungerar inte med youtube_collector — markera dem inaktiva i Odoo
- `run_pipeline()` tar `odoo_env` som parameter — det är INTE en global variabel
- `sync_items_to_media()` skriver bara basdata + länk — duplicera INTE vigil-fält i clio.media.article
- `build_sources_config()` hör hemma i `odoo_writer.py`, inte `main.py`
- Transkriptfiler lagras i `data/transcripts/vigil_{id}.json` på servern

## Odoo-addon

Repo: `~/clio-odoo-addons/clio_vigil/` (branch `19.0`)
Databas: `uap` (https://uap.arvas.international)
Uppgradera: `docker exec odoo19-odoo-1 odoo -c /etc/odoo/odoo.conf -u clio_vigil -d uap --stop-after-init`
Starta om efter uppgradering: `docker restart odoo19-odoo-1`

---

## Embedding-backend — GPU-problematik (dokumenterat 2026-07-20)

### Rotorsak: go runner saknar GPU-stöd

Ollama 0.20.7 använder två runners beroende på modellarkitektur:
- **llama runner** — för LLM-modeller (GPT, Llama etc.) → GPU-offload fungerar
- **go runner** — för BERT-arkitektur-modeller (inkl. bge-m3) → **GPU stöds ej**

`bge-m3` är en BERT-modell → go runner väljs alltid → 100% CPU → ~226 sek/objekt.

Bekräftat i loggar:
```
source=runner.go:965 msg="starting go runner"   ← BERT-path, ej llama-path
GPULayers:[]                                     ← noll GPU-lager tilldelade
device=CPU size="1.0 GiB"                        ← all vikt på CPU
```

CUDA-backends finns (`/usr/local/lib/ollama/cuda_v12/libggml-cuda.so`) men laddas aldrig för go runner.
Parametern `num_gpu` i API-anropet saknar effekt för embedding-modeller.

GPU-hårdvara: GTX 1050 Ti (4 GB), CUDA 12.5, drivrutin 555.42.06 — fungerar tekniskt men når aldrig go runner.

### Lösningsalternativ (ej genomförda)

**Alt 1 — Byt embedding-modell till llama-arkitektur**
`nomic-embed-text` (GPT-NeoX) → llama runner → GPU offload fungerar.
Nackdel: 768 dimensioner (mot bge-m3:s 1024) → kräver ny Qdrant-kollektion + full re-indexering.

**Alt 2 — text-embeddings-inference (TEI) container** ← rekommenderas om GPU krävs
HuggingFace TEI ger fullständigt GPU-stöd för BERT-modeller inkl. bge-m3:
```bash
docker run --gpus all -p 8080:80 \
  ghcr.io/huggingface/text-embeddings-inference:turing-1.5 \
  --model-id BAAI/bge-m3
```
Kompatibel API (OpenAI-format). GTX 1050 Ti = "turing"-bild (compute cap 6.1).
Nackdel: extra container, 1050 Ti är lågprioritet i TEI:s GPU-stöd.

**Alt 3 — Acceptera CPU** (nuvarande läge)
~226 sek/objekt, ca 40 objekt i kön = ~2,5 h för full re-indexering.
Fungerar men kan inte hinna med löpande inmatning vid högt flöde.

### Nuvarande körstatus (2026-07-20)

Nohup-körning av 40 `transcribed`-objekt startades föregående session.
Kolla status:
```bash
ps aux | grep indexer
# eller
python main.py --stats
```

### Beslut (2026-07-20): CPU räcker — ingen GPU-åtgärd krävs

Flödesanalys:
- Löpande drift: ~20 nya objekt/dag → ~75 min indexering → pipelinen klar långt innan nästa körning
- Engångsjobb (re-indexering): 50–100 objekt → 3–6 h nohup, stör inget

**CPU är tillräcklig. TEI-container och modellbyte är onödig komplexitet för detta flöde.**
Återöppna frågan först om objekt/dag ökar till hundratals.

Snabbstart vid framtida felsökning:
```
# Kolla Qdrant-läge
curl -s http://localhost:6333/collections/vigil_ufo | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['points_count'])"

# Kolla pipeline-state
sqlite3 data/vigil.db "SELECT state, count(*) FROM vigil_items GROUP BY state ORDER BY count(*) DESC;"

# Re-indexera (kör i bakgrunden, från clio-vigil-mappen)
nohup ../.venv/bin/python indexer.py --run --domain ufo --max 100 >> ~/logs/reindex_DATUM.log 2>&1 &
```

---

## Re-indexering — RSS/Google News-objekt med ofullständig text (TODO)

826 objekt i `uap_classified` (källa: rss + google_news) saknar fulltext och indexerades
med bara rubrik + beskrivning som fallback (genomfört 2026-07-20).

När RSS-scraping förbättras (fulltext från artikelsidor), re-indexera så här:

Steg 1 — hitta objekt indexerade utan transkript:
  sqlite3 data/vigil.db "SELECT id, title, source_type FROM vigil_items WHERE state='indexed' AND source_type IN ('rss','google_news') AND transcript_path IS NULL;"

Steg 2 — radera gamla Qdrant-punkter (annars dubbletter):
  Använd payload-filter på item_id (punkterna har uuid som ID, inte item_id):
  client.delete(collection_name="vigil_ufo", points_selector=FilterSelector(filter=Filter(must=[FieldCondition(key="item_id", match=MatchValue(value=ITEM_ID))])))

Steg 3 — återställ state för att trigga om-indexering:
  sqlite3 data/vigil.db "UPDATE vigil_items SET state='uap_classified' WHERE id IN (...);"

Steg 4 — kör indexer med lämpligt --max.

OBS: delete måste ske via payload-filter, inte punkt-ID.

---

---

## Watchdog (installerad 2026-07-20)

Script: `~/19.0/clio-tools/clio-vigil/vigil_watchdog.py`
Timer: `clio-vigil-watchdog.timer` — kör var 10:e minut via systemd
State: `~/logs/vigil_watchdog_state.json` (räknare per tjänst, nollställs dagligen)

Bevakar: `clio-vigil.service`, `clio-vigil-uap.service`, `clio-vigil-download.service`
Vid `failed`: startar om max 3 ggr/dag, mailar `fredrik@arvas.se` vid varje händelse.
Efter 3 misslyckanden: mailar "ger upp — manuell åtgärd krävs", stoppar omstarter för dagen.

Logg: `~/logs/vigil_watchdog.log`

---

## Odoo-vyer (uppdaterat 2026-07-20)

Alla tre menyval i Clio Vigil använder nu `clio.media.article` som modell:

| Meny | Filter |
|---|---|
| **Kö** | `data_source IN [vigil_ufo, vigil_ai]` + `vigil_item_id.state IN [queued, downloaded, transcribing, transcribed]` |
| **Klara objekt** | `data_source IN [vigil_ufo, vigil_ai]` + `vigil_item_id.state IN [indexed, notified, uap_classified, captioned]` |
| **Alla objekt** | `data_source IN [vigil_ufo, vigil_ai]`, grupperat på `vigil_state` som förval |

`clio.vigil.item`-vyerna (list/form/kanban/graph) är kvar för Pipeline-adminsidan.

`vigil_state` är ett `related`-fält på `clio.media.article` (via `vigil_item_id.state`) definierat i `clio_vigil/models/clio_media_article_ext.py`. Möjliggör group_by i Odoo.

Vyer: `list, kanban, graph, pivot, form` på alla tre.

---

## Cockpit — dubbel statuskälla

Cockpiten (`clio.vigil.pipeline`) visar två separata statusar:

| Fält | Källa | Uppdateras av |
|---|---|---|
| `heartbeat_last_run` | `clio.tool.heartbeat` | `write_heartbeat()` i slutet av timer-körning |
| `last_completed` | `.vigil_status`-fil på disk | trigger_runner.py (knapp-klick) + nu även main.py (timer) |

Fr.o.m. 2026-07-20 skriver `main.py` `.vigil_status` i slutet av varje körning med `triggered_by=systemd.timer`.
Status-filen: `~/19.0/clio-tools/clio-vigil/data/.vigil_status` (monterad som `/mnt/clio-tools/clio-vigil/data/.vigil_status` i Docker).
