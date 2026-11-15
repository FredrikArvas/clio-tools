# Arkitekturbeslut (ADR) — clio-tools

Alla strukturellt viktiga beslut dokumenteras här.
Format: datum, fråga, valt alternativ, förkastade alternativ, påverkan och belägg.

Beslutsloggar per projekt finns även i Context Cards i Notion.
Separata ADR-filer för framtida beslut skapas i `clio-genealogy/docs/adr/`.

---

## ADR-001 — Claude (Anthropic) som primär AI-leverantör

**Datum:** 2026-03-31 (härlett ur Context Card-skapandetid)
**Fråga:** Vilken LLM-plattform används för AI-anrop i plattformen?
**Valt:** Claude (Anthropic API) — `claude-sonnet-*` som standardmodell, `claude-haiku-*` för billiga anrop.
**Förkastade alternativ:** OpenAI GPT (inlåsning, prissättning), lokala modeller via Ollama (används för RAG-embedding men inte för primära anrop, kapacitetsbegränsad på GPU).
**Påverkan:** Modellnamn hanteras som konstanter i koden (`MODEL_SONNET`, `MODEL_HAIKU`). Alla AI-anrop i clio-tools förutsätter `ANTHROPIC_API_KEY` i `.env`.
**Belägg:** `clio-tools/CLAUDE.md` §AI/LLM-regler (V)

---

## ADR-002 — Python som primärt skriptspråk

**Datum:** 2026-03-31 (härlett)
**Fråga:** Vilket skriptspråk används för automatiseringsverktyg på servern?
**Valt:** Python 3 (3.10+). Vanilla PHP för clio-music (undantag, se ADR-007).
**Förkastade alternativ:** Node.js/Deno (används i slack-apps utanför clio-tools), Bash (används för enkla deploy-skript).
**Påverkan:** `pytest` som testramverk, `pathlib.Path` som standard för filhantering, `pip` för beroenden.
**Belägg:** `clio-tools/CLAUDE.md`, `clio-docs/CODING_STANDARD.md` (V)

---

## ADR-003 — Odoo som affärsplattform (CRM/ERP/portal)

**Datum:** 2026-03-31 (härlett)
**Fråga:** Vilken plattform används för fakturering, kundportal och affärsdata?
**Valt:** Odoo 19 (port 8079 på EliteDeskGPU). Odoo 18-containern avvecklas efter att SSF-uppdraget avslutas.
**Förkastade alternativ:** Zapier (användes tidigare för Bokio-synk, ersatt av egna moduler 2026-10).
**Påverkan:** Egna tillägg i `odoo-addons/` och `~/clio-odoo-addons`. Databaser per kund/projekt (`aiab`, `jessica`, `mrmusic`). Bokio-integration via `invoice_bokio`-modulen.
**Belägg:** Uppdragsram §9, ncc-codes.md `odoo19` (V)

---

## ADR-004 — Qdrant som vektordatabas för RAG

**Datum:** 2026-04-xx (härlett ur clio-rag/config.py)
**Fråga:** Vilket vektorlager används för RAG-pipeline?
**Valt:** Qdrant (körs som container `qdrant` på servern).
**Förkastade alternativ:** pgvector (Postgres-extension), Chroma (ej persistent over restart utan konfiguration), FAISS (ej server-baserat).
**Påverkan:** `clio-rag/config.py` konfigurerar Qdrant-anslutning. `clio-rag-mcp` exponerar RAG via MCP-protokoll.
**Belägg:** Uppdragsram §9 (container `qdrant`), `clio-rag/config.py` (V)

---

## ADR-005 — systemd timers (inte cron) som standard för schemaläggning

**Datum:** 2026-xx-xx (härlett)
**Fråga:** Hur schemaläggs återkommande jobb på servern?
**Valt:** systemd timers för nya jobb (vigil, uap-harvest, recruit). Befintliga cron-rader behålls tills vidare.
**Förkastade alternativ:** Enbart cron (befintlig rest, fragmenterad), Celery/APScheduler (overkill för en-persons miljö).
**Påverkan:** Schemaläggning är splittrad på tre ställen: systemd, cron och Windows Scheduler. Detta är ett känt problem — konsolidering är ett öppet arkitekturmål.
**Belägg:** Uppdragsram §9 (V); känd bugg: cronrad pekar på `~/clio-tools/clio-uap/uap_nightly.sh` som inte finns (V)

---

## ADR-006 — Notion som projektkällan, envägssynk till laptop

**Datum:** 2026-04-06 (Projektmasterlistan beskrivning: "Uppdaterad 2026-04-06")
**Fråga:** Var lever projektkoderna och Context Cards?
**Valt:** Notion (workspace ArvasClaudeStart) är master. `ncc_sync.ps1` synkar dagligen till `ncc-codes.md` på laptopen.
**Förkastade alternativ:** Excel/Dropbox som master (användes i Projektmasterlista v1.0–v1.3, ersatt av Notion).
**Påverkan:** Redigera aldrig `ncc-codes.md` för hand. Synken är envägs — Notion → laptop. Nya kodord läggs i Notion, inte i filen.
**Belägg:** `ncc-codes.md` header (V); Projektmasterlista Excel v1.0–v1.3 i Dropbox (V)

---

## ADR-007 — Vanilla PHP/JS för clio-music (inga ramverk)

**Datum:** 2026-xx-xx (härlett ur clio-music/CLAUDE.md)
**Fråga:** Vilket stack används för clio-music (meditationsljudspelaren)?
**Valt:** Vanilla PHP utan Composer, vanilla JS med Web Audio API. Inga npm-beroenden.
**Skäl:** Enkel driftsättning på PHP 8.3-FPM, inga ramverk att uppgradera, enkel läsbarhet för en-persons förvaltning.
**Förkastade alternativ:** Laravel/Symfony, React/Vue (overkill för enkel mediaspelare).
**Påverkan:** Inga beroenden utöver PHP 8.3. CSP är enforcing — inga inline-skript. Data till JS via `<script type="application/json">`-block.
**Belägg:** `clio-music/CLAUDE.md` (V)

---

## ADR-008 — Dropbox som resultatlager (kanal 2 av fyra)

**Datum:** 2026-03-31 (härlett)
**Fråga:** Var lagras resultat från AI-pipelines och dokument?
**Valt:** Dropbox under `C:\Users\fredr\Dropbox\projekt\Clio-projekt\` med blandad indelning per kontext och per verktyg.
**Förkastade alternativ:** OneDrive (Capgemini-konto, risk för kontextkorsning), lokal disk (ej synkat), Nextcloud på servern (finns men används inte för resultatlagring).
**Påverkan:** 21 Python-filer i clio-tools refererar Dropbox-sökvägar. `clio-docs-batch.py` har en fel sökväg (`\Documents\Dropbox`) som ska korrigeras.
**Belägg:** `Inventering_E_Information_styrning_v1.0.md` §2.5 (V)

---

## ADR-009 — NCC-kodordssystem för projektreferenser

**Datum:** 2026-04-06 (härlett ur Projektmasterlistan)
**Fråga:** Hur refereras projekt i chattar, CLAUDE.md och kod?
**Valt:** Korta kodord (`#vigil`, `#aiab`, `#clio`) kopplade till Notion Context Cards. Synkade dagligen till `ncc-codes.md`.
**Skäl:** Ger kortfattade projektreferenser i chattar utan att behöva upprepa kontext. Laddar rätt Context Card automatiskt.
**Påverkan:** 88 aktiva kodord per 2026-11-15. Nya kodord kräver rad i Notion + körning av `ncc_sync.ps1`. Moduler utan kodord bryter mot princip 6.
**Belägg:** `ncc-codes.md` (V); `~/.claude/CLAUDE.md` §NCC-kodord (V)

---

## ADR-010 — Känd bugg: ogiltig cron-sökväg för uap_nightly.sh

**Datum:** 2026-11-11 (identifierad i Uppdragsram)
**Fråga:** En cronrad på servern kör `~/clio-tools/clio-uap/uap_nightly.sh` — sökvägen finns inte.
**Status:** Öppen — inte åtgärdad per 2026-11-15.
**Påverkan:** UAP-nattkörseln misslyckas tyst (cron skickar troligen felmail om `MAILTO` är satt, annars ingen indikation). Rätt sökväg är `~/19.0/clio-tools/clio-uap/uap_nightly.sh`.
**Åtgärd:** Uppdatera crontab på servern: `crontab -e` → ändra sökvägen.
**Belägg:** Uppdragsram §9 (V)

---

*Uppdateras vid varje strukturellt beslut. Senast ändrad: 2026-11-15.*
