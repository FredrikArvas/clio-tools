# clio-uap

UAP Tracking — migration och CLI för Notion → Odoo 18 + Neo4j + Qdrant, samt videoanalys av slow-motion-inspelningar.

## Modulöversikt

| Fil | Syfte |
|-----|-------|
| `main.py` | CLI-dispatcher (argparse) |
| `config.py` | Alla inställningar och env-variabler |
| `migrate.py` | Läser Notion CSV-export (sources, witnesses, encounters, verifications) |
| `odoo_sync.py` | Upsert-logik mot Odoo (uap.*-modeller) + `create_draft_encounter()` |
| `neo4j_sync.py` | Synkar encounters till Neo4j |
| `qdrant_index.py` | Indexerar encounters i Qdrant |
| `frame_extractor.py` | Extraherar frames ur video med ffmpeg/ffprobe |
| `video_analyzer.py` | Frame-by-frame UAP-analys med Claude Vision |
| `pipeline/__init__.py` | Markörfil — gör pipeline till Python-paket |
| `pipeline/motion_delta.py` | Pixeldifferens-analys för att hitta anomali-frames |
| `pipeline/ollama_screen.py` | LLaVA-förfiltrering via Ollama (lokal, kostnadsfri) |
| `pipeline/main.py` | CE5-pipeline CLI: motion-delta → LLaVA → Claude |
| `bible_encounters.json` | 52 bibliska encounters (OT+NT), strukturerad JSON med source_ref och bible_url |
| `uap_import_bible.py` | Importerar bible_encounters.json → Odoo; skapar uap.source-rader per kapitel |
| `uap_bible_sources.py` | Engångsskript: skapar/länkar Bible.com-källor för befintliga records |
| `afu_create_encounters.py` | Skapar encounters från AFU-checkpoint-data |

## Beroenden

- `clio_odoo/connection.py` — Odoo-anslutning via pyodoo-connect
- `ffmpeg` / `ffprobe` — frame-extraction (måste vara installerat i PATH)
- `anthropic` — Claude Vision API för videoanalys
- `clio-neo4j/` — Neo4j-synk-mönster
- `clio-rag/` — Qdrant-klientmönster

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

# Enkel videoanalys — alla frames direkt till Claude Vision
python main.py analyze --video C:/path/to/slowmo.mov
python main.py analyze --video slowmo.mov --fps 1 --no-odoo --keep-frames
python main.py analyze --video slowmo.mov --start 1:30 --end 2:00

# CE5-pipeline — motion-delta + LLaVA + Claude (kör på servern)
# Kör från clio-uap/-katalogen:
python -m pipeline.main analyze --video /mnt/dropbox-disk/uap/inbox/ce5.mov
python -m pipeline.main analyze --folder /mnt/dropbox-disk/uap/inbox/
python -m pipeline.main analyze --video ce5.mov --no-ollama --fps 8
python -m pipeline.main analyze --video ce5.mov --no-claude --keep-frames
python -m pipeline.main analyze --video ce5.mov --delta-threshold 8 --gap-frames 6
```

## Videoanalys — flöde

1. `ffprobe` hämtar metadata (längd, real FPS, inspelningstid)
2. `ffmpeg` extraherar frames till temporär katalog (`%TEMP%\uap_frames_*`)
3. Varje frame skickas som base64-JPEG till Claude Vision (`claude-sonnet-4-6`)
4. Claude returnerar JSON: objekt, kategorier, `unknown_detected`
5. Rapport skrivs till terminal med flaggade frames markerade
6. Valfritt: skapa `uap.encounter`-utkast i Odoo med JSON-sammanfattning

Inställningar kan styras via env-variabler:
- `UAP_FRAMES_PER_SEC` — frames per speluppspelningssekund (standard: 2)
- `UAP_VISION_MODEL` — Claude-modell (standard: claude-sonnet-4-6)
- `UAP_CONFIDENCE_THRESHOLD` — oanvänd i klassificeringen, reserverad (standard: 0.7)

## CE5-pipeline — flöde

Används för analys av kända UAP-videor (t.ex. CE5-kursmaterial). Körs på EliteDesk-servern där Ollama+GPU finns.

```
[1] ffmpeg frame-extraction
      ↓
[2] Motion-delta (PIL + numpy, cellbaserat 8×8-nät)
      → Identifierar frames med ovanlig pixeldifferens
      → Klustrar konsekutiva anomali-frames till "events"
      ↓
[3] LLaVA pre-screen (Ollama localhost:11434, gratis)
      → Skickar peak-framen per event till llava:latest
      → Filtrerar bort fåglar, flygplan, artefakter
      ↓
[4] Claude deep-analyze (claude-sonnet-4-6, kostar tokens)
      → Analyserar bara events som klarade LLaVA-filtret
      → JSON: objekt, kategorier, unknown_detected
      ↓
[5] Rapport + valfritt Odoo-utkast
```

Notera: `--no-ollama` skickar alla events direkt till Claude. `--no-claude` stannar efter LLaVA.

## Odoo-addon

Addon-repo (produktion): `~/clio-odoo-addons/clio_uap/` → monterat som `/mnt/addons/arvas/` i `odoo19-odoo-1`.
Dev-kopia (för PR/review): `clio-tools/odoo-addons/clio_uap/` — synkas manuellt till servern vid behov.

**Modeller:**
- `uap.encounter` — huvudmodell, inkl. entity_type (Modern UAP + Transmorf/biblisk taxonomi)
- `uap.encounter.passage` — passage i källa (position, citat, talare)
- `uap.source` — källkatalog med URL-fält (tier_1 = primärkälla)
- `uap.anomaly` + `uap.anomaly.source` — fenomenindex
- `uap.encounter.classification` — multi-klassificering (skywatcher/hynek/transmorf/eth)

**Entity-typer (entity_type):**
Modern UAP: Nordic, TallGray, ShortGray, LongGray, Reptilian, Mantid, Hybrid, Energy
Transmorf/biblisk: Angel (mal'ak), AngelOfLord (teofani), Cherub, Seraph, Nephilim / Giant
Obestämd: Unknown

**Uppgradering:**
```bash
docker restart odoo19-odoo-1 && sleep 20
docker exec odoo19-odoo-1 odoo --database uap --update clio_uap --stop-after-init --no-http
```
⚠️ Alltid `docker restart` FÖRE `--update` — annars laddar Odoo inte om nya fält.

## Källdata

`C:\Users\fredr\Dropbox\projekt\UAP\UAP Research project\`
- Incidents.zip — 904 encounters (primär, föredras av migrate.py)
- Notion Export/Sources 2.zip — 64 sources (hittad via rglob)
- NHI-disclousreProject.zip — 26 witnesses
- VerificationLog.zip — 141 verifications (13 kopplade till PPXL-encounters)
- Notion Export/Incidents 2.zip — 58 encounters (äldre delmängd, ignoreras)

## Server — miljö

```
SERVER:  clioadmin@100.107.127.104
Odoo:    https://uap.arvas.international (db=uap), modul clio_uap
Scripts: ~/19.0/clio-tools/clio-uap/
.env:    ~/19.0/clio-tools/.env  ← VIGIL_ODOO_URL + VIGIL_ODOO_DB
GPU:     GTX 1050 Ti 4 GB | qwen2.5:3b (1,79 GB, 100 % GPU)
```

## Enrichment-kommandon (server)

```bash
# Ny batch (byt N)
cd ~/19.0/clio-tools
nohup python3 -u clio-uap/uap_enrich.py --model qwen2.5:3b --max 10000 > /tmp/uap_enrich_fullN.log 2>&1 &

# Kolla logg
tail -5 /tmp/uap_enrich_fullN.log

# Pausa vigil-timer under berikning
sudo systemctl start/stop clio-vigil.timer

# Modul-update
docker exec odoo19-odoo-1 odoo --database uap --update clio_uap --stop-after-init --no-http
```

## Gotchas

- **ETH-prompt (2026-08-18):** eth≥3 kräver fysisk evidens/radar/multi-vittnen. eth=5 = officiella bekräftade dokument. Abduktionspåstående ensamt ger EJ eth=5.
- **description_sv/en/original** skrivs bara om värde finns — undviker `False`-överskrivning.
- **VIGIL_ODOO_URL** i parent .env → uap-db. `ODOO_URL` → aiab (fel).
- **OLLAMA_VULKAN=1 SKA EJ ANVÄNDAS** — CUDA körs automatiskt. `qwen2.5:14b` för stor (GPU+CPU-split).
- **Ollama kan kräva restart** efter lång inaktivitet: `systemctl restart ollama`
- **Moduluppgradering kräver omstart** — nya fält syns inte förrän containern startats om innan `--update`.
- **Två addon-repos** — redigera alltid `~/clio-odoo-addons/` på servern, inte `clio-tools/odoo-addons/`.

## Fältdokumentation — uap.encounter

**Standardklassificering:** `encounter_class` (1–5), `discourse_level` (1–5), `official_response` (A–E)

**ETH-hypotes:** `eth_origin` (0–5), `intelligence_indicator` (0–3)

**Pentagon Five Observables:** `obs_antigravity`, `obs_instant_accel`, `obs_hypersonic`, `obs_low_observability`, `obs_transmedium`, `observables_count` (0–5)

**Multi-klassificering:** `classification_ids` → `uap.encounter.classification` (system: skywatcher/transmorf_entity/hynek/eth/custom)

## Fältdokumentation — uap.anomaly

**Typ:** `anomaly_type` — biological/atmospheric/contact/geographic/military/cosmological/transmorf/vehicle/other

**Bedömning:** `confidence` (0–5), `eth_relevance` (0–5)

**Geografi:** `geo_lat`, `geo_lng`, `radius_km`, `location`

**Tidsperiod:** `date_first`, `date_last`

**Spårbarhet:** `source_ids` → `uap.anomaly.source` (source_type, source_ref, timestamp_in_source, quote)

**Encounters:** `encounter_ids` M2M → `uap.encounter`
