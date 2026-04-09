# clio-agent-obit — Release Notes

## 0.2.0 — "Multi-source" (2026-04-08)

### Bakgrund

Sprint 1 (0.1.0) byggdes på antagandet att familjesidan.se erbjuder publika
RSS-flöden. Vid faktisk verifiering 2026-04-08 visade det sig att **inga**
av de stora svenska dödsannonskällorna har publik RSS:

| Källa | RSS? |
|---|---|
| familjesidan.se | nej |
| begravning.se | nej |
| minnessidor.fonus.se | nej |
| minnesord.se | nej |

Hela primärkällan måste därför bytas. Designprincipen omformuleras från
"RSS-first" till **"stable-source-first via pluggable adaptrar"**.
Watchlist är fortfarande kärnan — källor är utbytbara.

### Vad är nytt

- **Källregistry** (`sources.yaml`) — nya källor läggs till genom att redigera
  YAML, ingen Python-ändring av `run.py` krävs.
- **Generisk HTML-adapter** (`source_html.HtmlListSource`) — CSS-selektor-driven
  så enkla sajter slipper egen Python-fil.
- **Två konkreta källor levererade**: `FamiljesidanHtmlSource`, `FonusSource`.
- **Discovery-CLI** (`sources/discover.py`):
  - `probe <url>` sonderar en URL för RSS, JSON-LD och listmönster och föreslår
    en `sources.yaml`-rad.
  - `probe <url> --add NAMN` appenderar förslaget till `sources.yaml` som
    `enabled: false` så användaren måste verifiera selektorerna manuellt.
  - `search --query "..."` är en stub med tydligt interface — 0.3.0 kan plugga
    in en riktig web-search bakom samma CLI utan att flödet ändras.
- **Delade extraktionshelpers** (`sources/parsers.py`) — birth year, location,
  date, name cleanup. Återanvänds av både RSS- och HTML-adaptrar.
- **Fix**: `check_deps.py` kraschade på Windows cp1252-konsol pga emoji-ikoner.
  Reconfigure till UTF-8 med ASCII-fallback.
- **Versionssträng**: `clio_obit.__version__ == "0.2.0"`.

### Brytande ändringar

- `sources/source_familjesidan.py` är omdöpt till `sources/source_familjesidan_rss.py`
  och markerad DEPRECATED. Den behålls för framtiden om RSS skulle dyka upp.
- `run.py` importerar inte längre `FamiljesidanSource` direkt — alla källor laddas
  via `registry.load_sources("sources.yaml")`. En kraschande källa stoppar inte
  längre hela körningen.
- `RSS_URLS` i `.env` är deprecated men ignoreras tyst för bakåtkompatibilitet.

### Migration från 0.1.0

```powershell
pip install -r requirements.txt        # nya beroenden: pyyaml, requests, beautifulsoup4
python check_deps.py                   # ska nu visa alla nya checks gröna
python sources/discover.py probe https://www.familjesidan.se
python run.py --dry-run                # verifiera att källorna går att hämta
```

### Vad EJ ingår i 0.2.0

- Faktisk web-search-implementation i `discover.py search` (stub + interface bara)
- Notion Context Card-uppdatering — det görs separat från Claude.ai
- Hemortsutvinning (NER) — kvarstår som Sprint-2-jobb
- Fler än två konkreta källadaptrar — använd `discover` för att lägga till själv

### Risk

- HTML-selektorer för familjesidan/fonus är ett första utkast och kan brytas vid
  sajt-uppdateringar. Kör då `discover.py probe <url>` igen för att hitta nya
  selektorer och uppdatera `sources.yaml`.

## 0.1.0 — Sprint 1 (2026-04-08, samma dag)

Initial scaffold: matcher med konfidenspoäng, watchlist-loader, GEDCOM-/adressboks-
import, SMTP-notifier, SQLite state, RSS-baserad familjesidan-källa
(visade sig inte fungera — se 0.2.0).
