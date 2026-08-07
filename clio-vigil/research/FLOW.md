# Podcast → Vigil Pipeline — Flödesdokumentation

**Senast uppdaterad:** 2026-08-07  
**Utfört på:** Multiverse 5D Podcast (999 avsnitt)

---

## Syfte

Identifiera engelska vittnesmålsavsnitt från en bred spiritualitets/UAP-kanal
och importera dem som `clio.vigil.item` i Odoo (uap-databasen) för vidare
bearbetning i vigil-pipelinen (transkription → RAG-indexering).

---

## Steg 1 — Hämta metadata

Kör på servern med `yt-dlp` eller en RSS-scraper.  
Metadata sparas som en JSON-lista med fälten:

```json
[
  {
    "title": "...",
    "pub_date": "Mon, 03 Aug 2026",
    "duration_s": 2392,
    "description": "...",
    "audio_url": "https://...",
    "guid": "..."
  }
]
```

**Output:** `research/<podd>_metadata.json`

---

## Steg 2 — Tagga med Claude Haiku

**Verktyg:** `research/podcast_tagger.py`

Kör tre faser (eller `--phase all` för allt på en gång):

```bash
cd ~/19.0/clio-tools
python3 clio-vigil/research/podcast_tagger.py \
    --input  clio-vigil/research/<podd>_metadata.json \
    --output clio-vigil/research/<podd>_tagged.json
```

### Fas 1 — Språk (`--phase lang`)
- Modell: `claude-haiku-4-5-20251001`
- Batch: 20 avsnitt per anrop
- Taggar: `lang` — `en` | `pt` | `other`

### Fas 2 — Innehåll (`--phase full`)
- Taggar: `format`, `topic`, `witness_score` (0.0–1.0)
- `keep` beräknas lokalt (deterministisk regel, se nedan)

### Fas 3 — Geo + bakgrund (`--phase geo`)
- Taggar: `geo` (lista), `witness_background` (lista)

### Keep-kriterier
```python
keep = (
    lang == "en"
    and (format == "testimony"
         or (format == "interview" and witness_score >= 0.5))
    and topic not in ("channeling_msg", "audiobook")
    and witness_score >= 0.4
)
```

**Resume-säker:** progress sparas i `<output>.progress.json` efter varje batch.

**Kostnad:** ~$0.05–0.15 per 999 avsnitt (100 API-anrop × 3 faser).

---

## Steg 3 — Odoo-förberedelse (en gång per podd-typ)

### 3a. Addon-ändringar i `clio_vigil`

Nya modeller i `clio_vigil/models/clio_podcast_tags.py`:
- `clio.podcast.geo` — geografiska taggar med `code` + `name`
- `clio.podcast.background` — vittnesbakgrundstaggar med `code` + `name`

Nya fält på `clio.vigil.item`:
| Fält | Typ | Beskrivning |
|------|-----|-------------|
| `language` | Selection (en/pt/sv/other) | Avsnittets innehållsspråk |
| `podcast_format` | Selection | testimony/interview/channeling/lecture/audiobook/other |
| `podcast_topic` | Selection | uap_sighting/contact_experience/nde/… |
| `podcast_witness_score` | Float | 0.0–1.0 vittnespoäng |
| `podcast_keep` | Boolean | Vigil-kandidat (uppfyller keep-kriterierna) |
| `podcast_geo_ids` | Many2many → clio.podcast.geo | Geografisk kontext |
| `podcast_background_ids` | Many2many → clio.podcast.background | Vittnesbakgrund |

### 3b. Uppgradera addon

```bash
docker exec odoo19-odoo-1 odoo -c /etc/odoo/odoo.conf \
    -u clio_vigil -d uap --stop-after-init
docker restart odoo19-odoo-1
```

---

## Steg 4 — Importera till Odoo

**Verktyg:** `research/import_to_odoo.py`

```bash
cd ~/19.0/clio-tools

# Torrtest först
python3 clio-vigil/research/import_to_odoo.py \
    --input clio-vigil/research/multiverse5d_tagged.json \
    --dry-run

# Full import (alla 999)
python3 clio-vigil/research/import_to_odoo.py \
    --input clio-vigil/research/multiverse5d_tagged.json

# Eller bara keep=true (107 avsnitt)
python3 clio-vigil/research/import_to_odoo.py \
    --input clio-vigil/research/multiverse5d_tagged.json \
    --keep-only
```

Skriptet:
1. Skapar/verifierar geo- och bakgrunds-taggar i Odoo
2. Skapar/verifierar `clio.vigil.source` för podden
3. Upsert:ar alla avsnitt som `clio.vigil.item` (nyckel: `audio_url`)
4. Sätter `state = filtered_in` (keep=true) eller `filtered_out` (keep=false)

---

## Steg 5 — Pipeline-körning

Avsnitt med `state = filtered_in` + `language = en` kan köas direkt:

```bash
cd ~/19.0/clio-vigil
# Kö för transkription (Whisper)
python main.py --transcribe --max 10

# Summering (Claude)
python main.py --summarize --max 10

# RAG-indexering (Qdrant vigil_ufo)
python main.py --index --max 10
```

---

## Resultat — Multiverse 5D (2026-08-07)

| Mätetal | Värde |
|---------|------:|
| Avsnitt totalt | 999 |
| Engelska (en) | 547 (54.8%) |
| Portugisiska (pt) | 449 (44.9%) |
| keep=true | 107 |
| Militär/underrättelse + keep | 34 |
| Vittnespoäng ≥ 0.7 | 74 |

### Geo-fördelning (keep=true)
Rymden: 121 · Nordamerika: 102 · Annan planet: 27 · Under jord: 15

### Vittnesbakgrund (keep=true, militärrelaterade)
military_program: 37 · military: 26 · intelligence: 14

---

## Återanvändning för ny podd

1. Hämta metadata → `research/<ny_podd>_metadata.json`
2. `podcast_tagger.py --input <ny_podd>_metadata.json --output <ny_podd>_tagged.json`
3. Anpassa `SOURCE_NAME`, `SOURCE_URL`, `SOURCE_LANG` i `import_to_odoo.py`
4. `import_to_odoo.py --input <ny_podd>_tagged.json --dry-run`
5. `import_to_odoo.py --input <ny_podd>_tagged.json`

Addon-uppgradering (steg 3) behöver **inte** göras om — tag-modellerna är generiska.

---

## Filer

| Fil | Plats |
|-----|-------|
| Taggverktyg | `~/19.0/clio-tools/clio-vigil/research/podcast_tagger.py` |
| Importskript | `~/19.0/clio-tools/clio-vigil/research/import_to_odoo.py` |
| Flödesdokumentation | `~/19.0/clio-tools/clio-vigil/research/FLOW.md` |
| Taggmodeller (Odoo) | `~/clio-odoo-addons/clio_vigil/models/clio_podcast_tags.py` |
| Multiverse metadata | `~/19.0/clio-tools/clio-vigil/research/multiverse5d_metadata.json` |
| Multiverse taggad | `~/19.0/clio-tools/clio-vigil/research/multiverse5d_tagged.json` |
