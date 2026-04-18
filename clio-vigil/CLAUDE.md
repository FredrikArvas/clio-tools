# clio-vigil — CLAUDE.md
# Handover-paket till Claude Code
# Skapad: 2026-04-18 av Claude.ai (🧠 Design-läge)
# ADD: https://www.notion.so/34667666d98a811880b3ef8ed2d248c6

## Kontext

Läs ADD-länken ovan innan du gör något.
Ladda även NCC #clio: https://www.notion.so/33467666d98a8197a9d9f7b7d579e078

clio-vigil är en ämnesbaserad mediebevakning- och intelligence-pipeline.
Den bevakar podcasts, YouTube och nyheter, transkriberar relevant innehåll
och gör det sökbart via RAG (ChromaDB).

## Vad som är byggt (av Claude.ai på tåget)

```
clio-vigil/
├── main.py                    ✅ Klar — CLI och pipeline-koordinator
├── orchestrator.py            ✅ Klar — SQLite-schema + tillståndsmaskin
├── filter.py                  ✅ Klar — Relevansfilter (nyckelord MVP)
├── collectors/
│   ├── rss_collector.py       ✅ Klar — feedparser-baserad RSS-insamling
│   └── youtube_collector.py   ✅ Klar — yt-dlp metadata (ingen nedladdning)
├── config/
│   └── ufo.yaml               ✅ Klar — UFO/UAP domänkonfiguration
└── CLAUDE.md                  ✅ Detta dokument
```

## Vad Claude Code ska bygga härnäst

### Prioritet 1 — Transkription (transcriber.py)
Återanvänder clio-audio-edit som komponent.
Läs: clio-tools/clio-audio/clio-audio-edit.py

Ska hantera:
- Hämtar audio via yt-dlp (youtube) eller direkt URL (rss/podcast)
- Kör Whisper segment för segment (för preemptiv paus)
- Sparar transcript_path i vigil_items
- Uppdaterar whisper_segment vid paus
- Kallar orchestrator.transition(conn, id, "transcribed")

Preemptiv paus-logik:
- orchestrator.preempt_current(conn, current_id, reason, segment)
- Jobbet kan återupptas från whisper_segment

### Prioritet 2 — RAG-indexering (indexer.py)
Delar ChromaDB-instans med clio-books.
Collection-namn från domain_config["chroma_collection"] (t.ex. "vigil_ufo")

Metadata att spara per chunk:
- item_id, domain, source_name, source_maturity
- published_at, url, title
- segment_start, segment_end (tidsstämplar från Whisper)

### Prioritet 3 — Notifiering (notifier.py)
Daglig digest via clio@arvas.se (samma mönster som clio-obit).
Format: rubrik + 2-3 meningar (~8 ord/mening).
Länk till Odoo-listvy (http://192.168.1.189:8069) — URL specificeras när Odoo-addon finns.

### Prioritet 4 — Sammanfattning (summarizer.py)
Anropar Claude API med transkript-chunk.
Producerar summary-fältet i vigil_items (2-3 meningar).
Används i digest och Odoo-vy.

### Prioritet 5 — Odoo-addon (clio_vigil/)
Modell: clio.vigil.item
Fält: title, summary, url, domain, source_maturity, state, published_at, priority_score
Listvy med filter på domain och source_maturity.
JSON-RPC-skrivning via pyodoo-connect (redan i clio_odoo/).

## Installation och test

```powershell
# Beroenden
pip install feedparser yt-dlp pyyaml

# Testa orkestreraren
cd clio-tools/clio-vigil
python main.py --stats

# Testa RSS-insamling (UFO-domän)
python main.py --run --domain ufo

# Visa kön
python main.py --list-queued
```

## Designbeslut att respektera

1. YAML-konfiguration för MVP — Odoo i Release 1.5
2. Källkvalitet = metadata, blockerar ALDRIG insamling
3. Preemptiv transkriptionskö: pausa vid Whisper segment-gräns
4. Prioritetstal = relevansscore × källvikt × (1 / längd_normaliserad)
5. ChromaDB: separata collections per domän, delar instans med clio-books
6. Inga externa API-beroenden (Taddy, Pyannote etc.)
7. Webb-crawling (Archive for the Unknown) = Release 2

## Placering i clio-tools repot

```
clio-tools/
└── clio-vigil/        ← Denna modul
    ├── CLAUDE.md
    ├── main.py
    ├── orchestrator.py
    ├── filter.py
    ├── collectors/
    ├── config/
    └── data/          ← Skapas automatiskt (vigil.db)
```

## Relaterade moduler

- clio-audio-edit: clio-tools/clio-audio/ (transkription)
- clio-books: ChromaDB-infrastruktur (dela instans)
- clio-agent-mail: notifiering via mail
- clio_odoo: Odoo-connector (pyodoo-connect)
