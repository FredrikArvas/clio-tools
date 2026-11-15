# 🔬 clio-research — Körinstruktion för Claude Code

> Autonomt, multi-lingualt evidensverktyg.
> Söker i globala forskningskällor, analyserar med Opus, granskar i oberoende session.

---

## Arkitektur (v2)

```
inbox/<run_id>.md   (ifylld PROMPT_TEMPLATE v2)
        │
        ▼
main.py (orkestrerare, state i ~/clio-research-runs/<run_id>/state.json)
        │
  S1 Insamling    Python-connectors  +  claude -p (Sonnet 4.6, WebSearch/WebFetch)
        │         → 01_sources.md + 01_sources.json
  S2 Analys       claude -p (Opus, inga nätverksverktyg)
        │         → 02_draft_v1.md  [kan begära EN extra sökning med NEEDS_SEARCH:]
  S3a Refcheck    Python, deterministisk: DOI→CrossRef, URL 200/3xx, [n]↔källlista
        │         → 03_refcheck_v1.md
  S3b Granskning  claude -p (Opus, NY session, inga verktyg utom WebFetch)
        │         → 03_review_v1.md  PASS / REVISE / FAIL
        │
        ├─ REVISE → S2 revision → v2.md → S3a/S3b (max 2 varv)
        ├─ FAIL   → needs_human, statusmail, ingen leverans
        ▼ PASS
  S4 Leverans     final.md → md2docx --profile aiab → final.docx
                  Dropbox-kopia + mail (clio-agent-mail) + Qdrant
```

**Statuser:** `inbox → collecting → analysing → reviewing → revising → ready_for_human → delivered`
(samt `needs_human`, `paused_limit`)

---

## Modellkonstanter

```python
MODEL_COLLECTOR = "claude-sonnet-4-6"   # S1
MODEL_ANALYST   = "claude-opus-5-5"     # S2, S3b
MODEL_REVIEWER  = MODEL_ANALYST
```

Opus-alias `opus` → 5.5, verifierat på servern 2026-10-28.

---

## Starta en körning

1. Lägg protokollfil i `inbox/`:

```
inbox/clio-research-NNN.md
```

2. Kör från `clio-tools/`-roten:

```bash
python3 clio-research/main.py --protocol clio-research-NNN
```

> **Server:** clio-tools-roten är `~/19.0/clio-tools/`, **inte** `~/clio-tools/`
> Bakgrundsstart:
> `nohup python3 clio-research/main.py --protocol clio-research-NNN > ~/logs/clio-research-NNN.log 2>&1 &`

---

## Körkatalog (utanför repot)

```
~/clio-research-runs/<run_id>/
  state.json            tillstånd (atomisk skrivning)
  protocol.md           kopia av inboxfilen
  01_sources.md/.json   insamling
  02_draft_vN.md        utkast (alla versioner sparas)
  03_refcheck_vN.md     deterministisk referenskontroll
  03_review_vN.md       granskning
  final.md / final.docx
  run.log               steg, status, token-förbrukning per steg
```

Standardkatalog kan bytas med `CLIO_RESEARCH_RUNS_DIR`.

> **Viktigt:** körkatalogerna ligger **utanför** repot med avsikt — annars laddas
> repots CLAUDE.md in i `claude -p`-sessionerna.

---

## Säkerhetsmodell

- `ANTHROPIC_API_KEY` tas bort ur barnprocessens miljö → alltid prenumeration, aldrig API-debitering.
  Fällan: `.env` laddar nyckeln via `load_dotenv(override=True)` — `claude_runner.py` rensar den.
- Ingen roll har **både** filåtkomst och nätverk:
  - Insamlaren: `WebSearch, WebFetch` — inga filverktyg
  - Analytikern: inga verktyg
  - Granskaren: `WebFetch` — inga filverktyg
  - Python skriver alla filer. Injicerat kommando i en webbsida kan inte läsa `.env`.
- `--setting-sources project`: serverns globala `~/.claude/CLAUDE.md` (skämt, token-räkning) laddas inte.
- `--strict-mcp-config`: inga MCP-servrar från användarens konfiguration.

---

## Protokollfil (v2)

- Format: `.md` (ifylld PROMPT_TEMPLATE v2.0). Gammalt JSON-format stöds tills vidare.
- Gitignorerade på laptopen — skickas med `scp`:

```bash
scp inbox/clio-research-NNN.md clioadmin@100.107.127.104:~/19.0/clio-tools/clio-research/inbox/
```

- Numrering följer Dropbox-mappnumret (mapp `021_UFO_klassificeringar` → `clio-research-021.md`).

Styrfält i `output`-blocket:
- `word: true` → genererar `.docx` via `md2docx --profile aiab`
- `save_to: /mnt/wde2/Dropbox/...` → Dropbox på servern (Windows-sökvägar fungerar inte)
- `phase_summaries: true` → sparar mellanliggande `.md`-filer per fas

---

## Statuskommandon

```bash
python3 clio-research/main.py --list
python3 clio-research/main.py --status clio-research-021_20261029_142300
python3 clio-research/main.py --resume clio-research-021_20261029_142300
```

---

## Fulltextmoduler (FT0–FT1, klar 2026-11-14)

### `contact.py`
Hanterar kontaktadressen som Unpaywall och Crossref kräver i API-anrop. Läser ur
`CLIO_CONTACT_EMAIL` i miljön; returnerar `None` om variabeln saknas. `redact(text)`
ersätter adressen (och URL-kodade varianter) med `<kontaktadress>` i felmeddelanden och
loggar. Adressen får aldrig hamna i sparade filer, loggfiler eller testdata.

### `source_model.py`
Definierar källformatet för `01_sources.json` (kontraktet i PLAN_research_pipeline_v2.md
avsnitt 12). Konverterar rå API-träffar till källobjekt (`from_raw_hit`), validerar hela
listan mot kontraktet (`validate_sources`), och läser/skriver filen atomiskt. Fältnamnen
är bindande och får inte ändras; `FETCH_ROUTES` och `READ_LEVELS` speglar planens
terminologi exakt.

### `fulltext_fetcher.py`
Fulltextkedjan. Version 1.1.0, sprint FT0 + FT1 (PLAN_fulltext_v1.0.md avsnitt 5).

Nio steg i prioritetsordning, varav sex körs på `delbar`-nivå:
1. `openalex` – best_oa_location.pdf_url eller landningssida
2. `unpaywall` – url_for_pdf (kräver CLIO_CONTACT_EMAIL)
3. `core` – fullText eller downloadUrl
4. `semantic_scholar` – openAccessPdf.url via DOI-uppslag
5. `direct` – källans URL eller doi.org-länk
6. `wayback` – Internet Archive för URL:er som gav HTTP 403

`snabb` kör bara steg 1; `standard` kör 1–4 (utan semantic_scholar och wayback).
403-svar från innehållsanrop spåras i `_Context.got_403_urls` för Wayback-steget.
PDF extraheras med PyMuPDF, HTML med trafilatura. Nätverksfel kastas aldrig; de
skrivs i `fetch.error`. Inga omförsök och ingen förfalskad webbläsaridentitet.

### `connectors/metadata.py`
Gemensam tolkning av metadata för konnektorerna. `openalex_source_type` sätter
källtypen baserat på OpenAlex `type` och publaiceringsplatsens typ (journal/conference/
repository). `openalex_affiliations` och `crossref_affiliations` extraherar
landskoder och institutionsnamn ur `authorships`/`author`. `country_from_affiliation`
parsar ett affilieringssträngs sista kommaavgränsade led mot en lista på ~60 landsnamn.
Kodar inga gissningar: saknas uppgiften i API-svaret returneras `None` eller tom lista.

---

## Rapportsteget S2 (spår 2, 2026-11-15)

### `report_writer.py`
Analyssteget. Bygger prompten ur protokollet och `01_sources.json`, anropar
`claude_runner.run_claude` (roll `analyst`, `MODEL_ANALYST_QUICK` på nivå snabb, annars
`MODEL_ANALYST`) och delar svaret vid `<<<RAPPORT>>>`, `<<<REGISTER>>>` och `<<<SLUT>>>`.
Modellen skriver titel och avsnitten Kort svar till Luckor; Python skriver Metod,
Källförteckning (bara citerade källor, med läsnivå), Bilagor och sidfot. Filer:
`02_response_v<k>.txt`, `02_draft_v<k>.md`, `02_claims_v<k>.json`, `03_lint_v<k>.md`.
`revise()` tar en kravlista. Word via `clio-docx/md2docx.js --profile aiab` på nivå
standard och delbar (sökväg kan bytas med `CLIO_MD2DOCX`). Prompter: `config/prompts_v2.yaml`.

### `report_lint.py`
Deterministisk kontroll, regler R01–R20 (rubriker, tomma och avklippta avsnitt, avbrutet
svar, `[n]` mot källförteckning och underlag, obligatoriska avsnitt per nivå, tomma värden,
dubbla citat, negativa slutsatser, emojier, ställningstagande utan hypotes, läsnivå och
påståenderegistret). Ett MÅSTE ger `REVISE`. Avsnittsordningen per nivå
(`REQUIRED_SECTIONS`) är den enda källan för både prompt och kontroll.

---

## Flödet v2 (spår 5, 2026-11-15)

`main.py` kör v2 som standard; det äldre åttafasflödet ligger bakom `--legacy` tills v2 är provat.

```bash
python3 clio-research/main.py --protocol clio-research-NNN [--niva snabb|standard|delbar]
python3 clio-research/main.py --resume <run_id> [--force]   # efter paused_limit, avbrott (--force efter needs_human)
python3 clio-research/main.py --list | --status <run_id>
```

Slutkod: 0 `ready_for_human`, 2 protokollfel, 3 `paused_limit`, 4 `needs_human`.

- `protocol_parser.py` läser mallen (`inbox/<id>.md`, PROMPT_TEMPLATE v2.0) eller JSON. Nya fält:
  `Nivå` (standard om inget anges) och `Spridning` (intern). Huvudfråga, Del 3 och minst en sökterm krävs;
  kvarlämnade `{{…}}` ger fel. Det normaliserade protokollet sparas som `protocol.json` i körkatalogen.
- `collector.py` (S1): connectorer → källformat → grovsållning och kandidattak (40/80/120) → fulltextkedjan
  → kontrollpunkt `01_candidates.json` → insamlarmodellen (relevans per källa; webbfynd på standard och
  delbar, prompter i `config/prompts_s1.yaml`) → CrossRef-metadata för webbfynd med DOI (Python, aldrig
  modellens uppgifter) → nivåns tak (15/40/60) bland de relevanta, direkt före analogi före bakgrund
  → `01_sources.json`, `01_filtered.json`, `01_sources.md`, `kallor/`.
- S2: `report_writer.analyse`/`revise` + `check` (report_lint). MÅSTE → revision, högst `Max revisionsvarv`
  (2), sedan `needs_human`. Kravlistan per utkast sparas i `03_lint_v<k>.json`.
- S3a, S3b och S4 är platshållare i `run_pipeline` (ref_checker, granskaren, motbevisvarvet, leverans).
- Tokens och modell per anrop i `run.log`; kontaktadressen maskas.

## Aktuellt utvecklingsläge: v2, sprint P1

| Sprint | Status | Innehåll |
|--------|--------|----------|
| P0 Grund | ✅ Klar 2026-10-28 | `claude_runner.py`, `run_state.py`, 20 tester gröna |
| P1 Insamling | ✅ Byggd 2026-11-15 (spår 5) | `protocol_parser.py`, `collector.py`, flödet i `main.py` – ej provkört med modell |
| P2 Analys | Väntar P1 | S2-prompt, `NEEDS_SEARCH`-varv, versionerade utkast |
| P3 Granskning | Väntar P2 | `ref_checker.py`, S3b-prompt, revisionsloop, verdiktparser |
| P4 Leverans | Väntar P3 | `clio-docx` i git och på servern, Dropbox, mail, Qdrant |
| P5 Drift | Väntar P4 | systemd-timer, `paused_limit`-återupptag |

Plan: `C:\Users\fredr\Dropbox\projekt\Clio-projekt\Clio Resarch\PLAN_research_pipeline_v2.md`

---

## R1.x pipeline (aktiv på servern tills v2 är klar)

Den gamla 8-fas-pipelinen (`main.py`) körs fortfarande på servern och hanterar körningarna 001–022.

| Fas | Label |
|-----|-------|
| 1–4 | Scoping, Broad, Regional, Adversarial (Python-connectors) |
| 5 | Citation chase |
| 6/6.5 | Credibility scoring + relevansfilter (cosine ≥ 0.15, top 100) |
| 7 | Rapport (Sonnet via API) |
| 8 | Delivery (mail + Qdrant) |

### Kända begränsningar (R1.x)

- **Semantic Scholar:** API-nyckel ogiltig — returnerar 403
- **CyberLeninka:** JavaScript-SPA, scraping fungerar ej tills R1.5 / Playwright
- **Qdrant:** `vigil_research`-kollektionen måste återskapas på servern efter Ollama-migrationen (radera och återskapa med dim 1024 — matchar nu bge-m3). Körningar 001–022 behöver re-indexeras.
- **Relevanströskel:** `MIN_SIMILARITY = 0.20` (i `relevance_filter.py`). Om Ollama inte svarar fallbackar filtret tyst till `relevance_score=0.5` och tar upp till 60 källor utan filtrering.

---

## Backlog (v2)

- [ ] Ny Semantic Scholar API-nyckel ([semanticscholar.org/product/api](https://www.semanticscholar.org/product/api))
- [ ] Re-indexera körningar 001–022 mot ny Ollama-embedding (radera `vigil_research`, kör om `qdrant_indexer.index_report` per körning)
- [ ] Semantisk X/Y-scoring i kvadrantdiagrammet
- [ ] Höj relevanströskel → 0.25–0.30 efter Semantic Scholar-återkoppling (bge-m3 kan ge högre absoluta scores)

---

*Notion NCC: `research` → [NCC 2026-05-04](https://app.notion.com/p/35567666d98a81abb906fa728249c209)*
*Plan v2: `Dropbox/projekt/Clio-projekt/Clio Resarch/PLAN_research_pipeline_v2.md`*
