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
