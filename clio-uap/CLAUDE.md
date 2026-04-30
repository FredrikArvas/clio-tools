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

# Analysera iPhone slow-motion-video (standard 2 frames/s, frågar om Odoo-utkast)
python main.py analyze --video C:/path/to/slowmo.mov

# Analysera utan Odoo, 1 frame/s, behåll frames
python main.py analyze --video slowmo.mov --fps 1 --no-odoo --keep-frames
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

## Odoo-addon

Installeras på elitedeskgpu (aiab-db):
`Apps → Uppdatera applista → Sök "UAP" → Installera`

Addons-sökväg på servern: `~/git/clio-tools/odoo-addons/`

## Källdata

`C:\Users\fredr\Dropbox\projekt\UAP\UAP Research project\`
- Incidents.zip — 904 encounters (primär, föredras av migrate.py)
- Notion Export/Sources 2.zip — 64 sources (hittad via rglob)
- NHI-disclousreProject.zip — 26 witnesses
- VerificationLog.zip — 141 verifications (13 kopplade till PPXL-encounters)
- Notion Export/Incidents 2.zip — 58 encounters (äldre delmängd, ignoreras)
