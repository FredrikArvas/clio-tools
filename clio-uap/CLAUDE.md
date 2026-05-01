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
