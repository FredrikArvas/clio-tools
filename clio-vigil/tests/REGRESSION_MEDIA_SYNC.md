# Regressionstest: vigil → clio.media.article sync

## Syfte

Verifiera att `sync_items_to_media()` i `odoo_writer.py` mappar alla fält
korrekt från `vigil_items` (SQLite) till `clio.media.article` (Odoo).

Testet är designat för att vara visuellt verifierbart: varje testposts titel
innehåller de fält och värden som ska kontrolleras i Odoo-gränssnittet, utan
att behöva referera till dokumentation.

---

## Testdatabas

| Parameter | Värde |
|-----------|-------|
| Odoo-databas | `clio_media_test` |
| URL | `https://uap.arvas.international` |
| Credentials | `ODOO_USER` / `ODOO_PASSWORD` ur `.env` |
| vigil.db | In-memory SQLite (skapas i testet, lämnar inga spår i produktion) |

Testposterna i Odoo **tas inte bort** efter testkörning — de är avsiktligt
persistenta för visuell inspektion i gränssnittet.

URL-prefix för alla testposter: `https://test.vigil/case-0N-*`

---

## Körning

```bash
# På servern (~/18.0/clio-tools/clio-vigil):
VIGIL_ODOO_DB=clio_media_test pytest tests/test_media_sync.py -v

# Lokalt (kräver VPN/Tailscale mot uap.arvas.international):
cd clio-vigil
VIGIL_ODOO_DB=clio_media_test pytest tests/test_media_sync.py -v
```

---

## Testfall

### CASE-01 — RSS-artikel, domän ufo

**Testar:** Grundläggande RSs-mappning utan enclosure.

| SQLite-fält | Värde | Förväntat Odoo-fält | Förväntat värde |
|-------------|-------|---------------------|-----------------|
| `url` | `https://test.vigil/case-01-rss-article` | `url` | samma |
| `title` | `[CASE-01] media_type=article \| data_source=vigil_ufo \| state=indexed` | `title` | samma |
| `source_name` | `Källa-01: source_name→source` | `source` | samma |
| `source_type` | `rss` (ingen enclosure) | `media_type` | `article` |
| `domain` | `ufo` | `data_source` | `vigil_ufo` |
| `published_at` | `2026-01-15T10:00:00+00:00` | `published` | `2026-01-15 10:00:00` |
| `published_at` | (samma) | `first_seen` | `2026-01-15 10:00:00` |
| `state` | `indexed` | `vigil_state` | `indexed` |
| `relevance_score` | `0.8500` | `relevance_score` | `0.8500` |
| `priority_score` | `0.7200` | `priority_score` | `0.7200` |
| `source_maturity` | `etablerad` | `source_maturity` | `etablerad` |
| `summary` | `Sammanfattning case-01…` | `body_snippet` | samma |

---

### CASE-02 — RSS-podcast med enclosure

**Testar:** Att `raw_metadata.enclosure_url` triggar `media_type=podcast`.

| SQLite-fält | Värde | Förväntat Odoo-fält | Förväntat värde |
|-------------|-------|---------------------|-----------------|
| `url` | `https://test.vigil/case-02-rss-podcast` | `url` | samma |
| `title` | `[CASE-02] media_type=podcast \| enclosure_url satt \| duration=3600` | `title` | samma |
| `source_type` | `rss` | — | — |
| `raw_metadata` | `{"enclosure_url": "https://test.vigil/ep02.mp3"}` | `media_type` | `podcast` |
| `duration_seconds` | `3600` | `duration_seconds` | `3600` |
| `domain` | `ufo` | `data_source` | `vigil_ufo` |
| `published_at` | `2026-02-20T14:30:00+00:00` | `published` | `2026-02-20 14:30:00` |
| `state` | `transcribed` | `vigil_state` | `transcribed` |
| `relevance_score` | `0.6300` | `relevance_score` | `0.6300` |

---

### CASE-03 — YouTube-video, domän ai

**Testar:** Att `source_type=youtube` ger `media_type=video` och att
domän `ai` ger `data_source=vigil_ai`.

| SQLite-fält | Värde | Förväntat Odoo-fält | Förväntat värde |
|-------------|-------|---------------------|-----------------|
| `url` | `https://test.vigil/case-03-youtube-video` | `url` | samma |
| `title` | `[CASE-03] media_type=video \| source_type=youtube \| data_source=vigil_ai` | `title` | samma |
| `source_type` | `youtube` | `media_type` | `video` |
| `domain` | `ai` | `data_source` | `vigil_ai` |
| `published_at` | `2026-03-10T09:00:00+00:00` | `published` | `2026-03-10 09:00:00` |
| `duration_seconds` | `1800` | `duration_seconds` | `1800` |
| `state` | `notified` | `vigil_state` | `notified` |
| `priority_score` | `0.4100` | `priority_score` | `0.4100` |

---

### CASE-04 — Null publiceringsdatum, fallback till created_at

**Testar:** Att `first_seen` aldrig sätts till körningens nuvarande tidpunkt
när `published_at=NULL` — rätt fallback är `created_at`.

| SQLite-fält | Värde | Förväntat Odoo-fält | Förväntat värde |
|-------------|-------|---------------------|-----------------|
| `url` | `https://test.vigil/case-04-null-published` | `url` | samma |
| `title` | `[CASE-04] published=False \| first_seen←created_at (ej today)` | `title` | samma |
| `published_at` | `NULL` | `published` | `False` (ej satt) |
| `created_at` | `2026-04-05T08:00:00` | `first_seen` | `2026-04-05 08:00:00` |
| `source_type` | `rss` | `media_type` | `article` |
| `domain` | `ufo` | `data_source` | `vigil_ufo` |
| `state` | `filtered_in` | `vigil_state` | `filtered_in` |

**Kritisk assertion:** `first_seen != datetime.now().date()` — värdet ska
vara `2026-04-05`, inte det datum testet kördes.

---

### CASE-05 — Audio nedladdad, audio_downloaded computed

**Testar:** Att `archive_path` → `audio_path` och att computed-fältet
`audio_downloaded` blir `True`.

| SQLite-fält | Värde | Förväntat Odoo-fält | Förväntat värde |
|-------------|-------|---------------------|-----------------|
| `url` | `https://test.vigil/case-05-with-audio` | `url` | samma |
| `title` | `[CASE-05] audio_downloaded=True \| archive_path→audio_path` | `title` | samma |
| `archive_path` | `/audio/test/case-05-episode.mp3` | `audio_path` | `/audio/test/case-05-episode.mp3` |
| — | (computed) | `audio_downloaded` | `True` |
| `domain` | `ufo` | `data_source` | `vigil_ufo` |
| `source_type` | `rss` | `media_type` | `article` |
| `published_at` | `2026-05-01T12:00:00+00:00` | `published` | `2026-05-01 12:00:00` |
| `state` | `queued` | `vigil_state` | `queued` |

---

## Mappningsöversikt

```
vigil_items (SQLite)          clio.media.article (Odoo)
────────────────────────      ──────────────────────────────────────
url                      →    url                (upsert-nyckel)
title                    →    title
source_name              →    source
published_at             →    published          (False om NULL)
published_at / created_at→    first_seen         (aldrig today om det kan undvikas)
"vigil_{domain}"         →    data_source
summary                  →    body_snippet

source_type + raw_metadata → media_type
  youtube                →    video
  rss + enclosure_url    →    podcast
  övriga rss             →    article

state                    →    vigil_state
duration_seconds         →    duration_seconds
relevance_score          →    relevance_score
priority_score           →    priority_score
source_maturity          →    source_maturity
archive_path             →    audio_path
(computed)               →    audio_downloaded   (bool: bool(audio_path))
```

---

## Begränsningar

- Testet kräver nätverksåtkomst till `https://uap.arvas.international` och
  giltiga `ODOO_USER`/`ODOO_PASSWORD` i `.env`. Det är inte ett rent
  enhetsttest — det är ett integrations-/regressionstest.
- `transcript_snippet` är inte mappat från något SQLite-fält och testas
  därför inte här. Fältet finns i `clio.media.article` via `clio_vigil`-arvet
  men skrivs enbart av transkriptionssteget, inte av `odoo_writer.py`.
