# PLAN — Skills för media, uap och vigil (v1.0, 2026-11-07)

## Mål
Ersätta manuell NCC-hämtning från Notion med skills som laddas när uppgiften matchar.
Notion-korten blir arkiv och beslutslogg. Varje fakta har ett hem.

## Utgångsläge (kontrollerat 2026-11-07)
| Del | Finns idag | Kommentar |
|---|---|---|
| skill `uap-encounter` | 26 rader, klassificeringsfält + uap_enrich | Behålls, utökas inte med allt |
| `clio-vigil/CLAUDE.md` | 254 rader | Över riktvärdet ~200, delvis procedurer |
| `clio-uap/CLAUDE.md` | saknas | Ska skapas (kort) |
| media | ingen modulmapp i repot, ingen `odoo-addons/clio_media` | Källa att fastställa: servern? annan repo? |
| Notion-kort | vigil (nytt), uap, media | UAP-kortet är daterat 2026-09-27 |

## Arbetsfördelning (var hör vad hemma)
- **Modul-CLAUDE.md** (kort, <100 rader): miljö, sökvägar, ett par fällor som alltid gäller i mappen.
- **Skill**: procedurer och domänkunskap (kommandon, fältdokumentation, deploy, felsökning).
- **Hook**: kontroll att rätt Odoo-databas används (VIGIL_ODOO_URL, inte ODOO_URL).
- **Notion**: arkiv, beslutslogg, sprintlogg. Länk till skillen.

## Skills som skapas
| Skill | Innehåll | Källa |
|---|---|---|
| `clio-uap` | Encounter-datamodell, anomalier, transmorf, enrichment-kommandon, harvest fas 0–3, importskript | UAP-kortet + `uap-encounter` + PLAN_fas0_stadning/klassificering |
| `clio-vigil` | Pipeline, tillståndskedja, timers, kommandon, Odoo-modeller, stuck-items, deploy | vigil-kortet + gamla kortets modell/deploy + `clio-vigil/CLAUDE.md` |
| `clio-media` | clio_media-modeller (article, event), importflöde, backfill-ordning (vigil_item_id före vigil_state) | media-kortet + ICER-avsnittet i UAP-kortet |
| delat avsnitt | `.env`-fällan, OLLAMA_VULKAN, GPU-gräns, pausa vigil-timer | Referens till befintliga server-admin-kort (parkerat) |

`uap-encounter` slås ihop med `clio-uap` som sidofil (`encounter-fält.md`) så att det inte blir två skills för samma sak.

## Faser
**Fas 0 — Inventera (läsning, ingen ändring)**
- Läs `clio-vigil/CLAUDE.md` och media-kortet. Avgör var clio_media-koden bor.
- Lista motstridigheter mellan kort och kod (t.ex. tabellnamn `vigil_items`, port 8079 vs domän).
- Klart när: tabell över källa → mål finns för varje faktablock.

**Fas 1 — clio-uap**
- `~/.claude/skills/clio-uap/SKILL.md` (<200 rader) + sidofiler `encounter-falt.md`, `enrichment.md`, `harvest.md`.
- Ny `clio-uap/CLAUDE.md` (<100 rader).
- Uppdatera status i Notion-kortet till dagens läge och länka skillen.
- Klart när: ny session i `clio-uap/` svarar på "hur startar jag berikning" utan Notion-uppslag.

**Fas 2 — clio-vigil**
- Skill `clio-vigil` med sidofiler `pipeline.md`, `odoo.md`, `drift.md`.
- Korta `clio-vigil/CLAUDE.md` till <100 rader, flytta procedurer till skillen.
- Klart när: CLAUDE.md < 100 rader, ingen information förlorad (diff granskad).

**Fas 3 — clio-media**
- Skill efter fas 0:s beslut om var koden bor.
- Flytta ICER/event-avsnittet från UAP-kortet till media-kortet.

**Fas 4 — Hook och uppstädning**
- PreToolUse-hook (Bash) som varnar när ett uap/vigil-kommando körs mot fel Odoo-databas.
- `/doctor prompt-audit` på de tre modulerna. Kontrollera triggerbeskrivningar mot varandra så att skills inte krockar.
- Korta Notion-korten till arkiv + länk. Uppdatera NCC-kodord så att `#ncc uap` m.fl. pekar på skillnamnet i kortets första rad.

## Beslut som behövs
1. En skill per modul (rekommenderas) eller en gemensam `clio-uap-vigil`?
2. Var bor clio_media-koden, och ska den få egen modulmapp i repot?
3. Ska skillarna ligga i `~/.claude/skills` (bara EliteBook2) eller i repot (`.claude/skills`, delas via git, kräver att repot är publikt-säkert)? Repot är publikt, så inga serveradresser eller hemligheter får in i skillfilerna.

## Risker
- Dubbelunderhåll kort/skill om inte Notion-korten kortas i fas 4.
- Skills på laptopen finns inte på servern. Serversessioner behöver kopior eller repo-skills.
- Publikt repo: ingen Tailscale-IP, inga nycklar i skillfiler som committas.

## Verifiering
Per fas: ny session i modulmappen, tre kontrollfrågor ur kortets gotchas, inget Notion-anrop. Jämför svaren mot kortet.

---

## Fas 0 — resultat (2026-11-07)

### Var koden och instruktionerna bor
| Modul | Python/pipeline (clio-tools) | Odoo-addon (clio-odoo-addons, eget repo) |
|---|---|---|
| uap | `clio-uap/` — ingen CLAUDE.md | `clio_uap/CLAUDE.md` (69 rader, stannar vid Sprint 3 / v19.0.1.4.0) |
| vigil | `clio-vigil/CLAUDE.md` (254 rader) | `clio_vigil/` — ingen CLAUDE.md (v19.0.1.10.0) |
| media | ingen modulmapp, men `clio-research/odoo_media_writer.py` och `clio-agent-job` skriver hit | `clio_media/CLAUDE.md` (113 rader, **föråldrad**) |
| reco (konsument) | — | `clio_reco/` — ingen CLAUDE.md (v19.0.2.0.0) |

Alla Odoo-addons ligger i `C:\Users\fredr\git\clio-odoo-addons` (remote `FredrikArvas/clio-odoo-addons`),
inte i clio-tools. Rot-CLAUDE.md i clio-tools nämner `clio-uap/CLAUDE.md` som finns inte.

### Fel i befintliga instruktioner
1. `clio_media/CLAUDE.md` beskriver bara artikelbanken (Odoo 18-sökvägar `~/18.0/`). Koden har `clio.media.work`,
   `work.type`, `work.identifier`, `genre`, `event` (verk/identifierare, beslut 13–19 i media-kortet). Modulen
   nämner `clio_vigil → clio_media (planerat)` men det är redan genomfört.
2. `clio_uap/CLAUDE.md` saknar: Sprint 4 (clio_media events), `uap.transmorf.entity`, ICER-import, `is_fiction`,
   `uap_harvest`/fas 0–3, `eth_origin`/observables-fält (finns i skillen `uap-encounter`).
3. `clio-vigil/CLAUDE.md`: summarize-timern är **pausad** sedan 2026-10-18 (CLAUDE.md), men det nya Notion-kortet
   listar den som "alla aktiva". Notion-kortet är fel. Tillståndskedjan skiljer sig mellan CLAUDE.md
   (`downloaded`, `uap_classified`) och Notion (`filtered_in`, `summarized`) — CLAUDE.md stämmer med
   vyerna i koden, kortet inte.
4. Port/URL: Notion-vigil anger `http://<server-tailscale-ip>:8079`; CLAUDE.md kräver värdnamnet
   `https://uap.arvas.international` (dbfilter). IP:port ger "Authentication failed". Kortet är farligt.
5. Notion-vigil: "Synk-gap 14 221 artiklar saknar vigil_item_id" är utpekad grundorsak i CLAUDE.md
   (IP i VIGIL_ODOO_URL, löst 2026-10-18) — kortets öppna punkt är troligen avslutad.
6. Namnkrock: "media" betyder verk (media-kortet) men nyhetsartiklar/källor i `clio_media`/vigil. Hanteras i skillbeskrivningar.
7. Media-kortet: "provisoriskt, städas ihop med #reco och #bok" (beslut 2026-10-25). UAP-kortets ICER-avsnitt hör till clio.media.event.

### Konsekvenser för planen
- `clio-media`-skill ska täcka både artikelbank (clio_media) och verk/betyg (clio_media + clio_reco). Rimligare namn: `clio-media` (kärna) + referera `clio_reco`.
- Skills hör i huvudsak till clio-odoo-addons-repot (addon-kunskap) respektive clio-tools (pipeline).
- Fas 1–3 ska börja med att **rätta** modul-CLAUDE.md (de är den närmaste sanningen), inte kopiera Notion.
- Vilken Notion-statistik som är färsk måste verifieras mot servern (encounters-antal, timers) — ej gjort i fas 0.

### Beslut som återstår (ersätter tidigare 1–3)
1. Skill-uppdelning: `clio-uap`, `clio-vigil`, `clio-media` (rekommenderas), eller färre.
2. Placering: `~/.claude/skills` (bara laptop), `clio-tools/.claude/skills` eller `clio-odoo-addons/.claude/skills` (publika repon, inga IP/nycklar).
3. Rotordning: rätta modul-CLAUDE.md först (rekommenderas) eller skapa skills först.
4. Ska serverstatus (timers, antal) verifieras via SSH innan skillarna skrivs?

---

## Läge 2026-11-08 — databasvalet i pipelinen

### Åtgärdat
- `--classify-uap` i 19.0 kopplade upp via `clio_odoo.connect()` → rot-`.env` `ODOO_URL`/`ODOO_DB` = **aiab**.
  Klassificering och heartbeat gick till aiab t.o.m. 2026-11-08 01:16 (inga encounters skapade enligt loggarna).
- Fix `34c580b` (fanns bara på `feat/ncc-sync`) cherry-pickad till 19.0 som `2de223f` och driftsatt.
  Handpatchen i serverns `main.py` ersatt (backup `main.py.bak-handpatch-20261108-0800`).

### Kvar (före skill-arbetet)
1. `clio-uap/`-skripten har tre olika regler för databasval: bara rot-`.env` (aiab: `uap_pipeline.py`,
   `uap_web_enrich.py`, `uap_import_sefaa.py`, `auto_import.py`), `clio-uap/.env` (uap) eller
   `VIGIL_ODOO_*` med `ODOO_URL` som reserv. Förslag: en gemensam anslutningsfunktion som kräver
   `VIGIL_ODOO_*` utan reserv — ersätter hooken i fas 4.
2. `clio-uap-harvest.service` failar (203/EXEC): `~/19.0/venv/bin/python3` finns inte.
3. Cron 02:30 kör `~/clio-tools/clio-uap/uap_nightly.sh` — sökvägen finns inte.
4. `clio-vigil-uap.service` (avstängd) pekar fortfarande på `~/18.0/`.
