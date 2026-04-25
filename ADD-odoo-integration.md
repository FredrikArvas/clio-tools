# ADD — Odoo-integration för clio-agenter (Clio2)
**Version:** 0.2  
**Datum:** 2026-04-25  
**Författare:** Fredrik Arvas / Clio  
**Status:** Utkast

---

## 1. Bakgrund & syfte

clio-tools innehåller ett växande antal verktyg som idag körs via en TUI-meny (clio.py). Konfiguration ligger i YAML-filer, tillstånd i SQLite och schemaläggning i systemd-timers. Data är inte synlig i Odoo och kan inte hanteras av fler användare via ett GUI.

Beslutet är att Odoo successivt blir det primära gränssnittet. Den befintliga clio-TUI:n parkeras som **Clio1** och en ny **Clio2** tar vid — ett övergångsskal där verktyg försvinner ur menyn allteftersom de migreras till Odoo.

---

## 2. Krav

| Nr | Krav |
|----|------|
| 1 | Varje CLI-verktyg ska kunna köras standalone: `python clio-agent-job/run.py` |
| 2 | `python clio2.py` fungerar som samlat CLI under transitionsperioden |
| 3 | `clio_cockpit` i Odoo visar status och hälsa för alla agenter |
| 4 | Varje agent får sitt eget Odoo-addon med GUI för konfiguration och resultat |
| 5 | Befintlig data (YAML, SQLite) importeras till Odoo |

---

## 3. Clio1 vs Clio2

| | Clio1 (`clio1.py`) | Clio2 (`clio2.py`) |
|---|---|---|
| **Status** | Parkerad, fryst | Aktiv under transition |
| **Innehåll** | Alla verktyg, oförändrat | Alla verktyg — krymper när Odoo-addon är klart |
| **Version** | 2.1.1 (sista) | 2.0.0 → räknas upp per migration |
| **Syfte** | Referens, fallback | Primärt CLI tills Odoo täcker allt |

### Migrationsprincipen

```
clio2.py  →  verktyg A migreras till Odoo  →  clio2.py utan verktyg A
```

Varje verktyg i clio2.py är märkt med sin Odoo-destinationsstatus. Verktyget tas bort ur `clio2.py` **när** motsvarande Odoo-addon är verifierat i drift — inte innan.

### Migrationsordning och status

| Verktyg | Nr | Odoo-destination | Status |
|---|---|---|---|
| clio-agent-job | 14 | `clio_job` (addon finns) | 🔜 Release 1 |
| clio-agent-obit | 11 | `clio_obit` (addon finns) | 🔜 Release 2 |
| clio-vigil | 15 | `clio_vigil` (byggs) | 🔜 Release 3 |
| clio-graph | 16 | `clio_cockpit` / Neo4j | Planerad |
| clio-agent-odoo | 17 | Odoo-native | Planerad |
| clio-agent-mail | 10 | Odoo mail / Discuss | Planerad |
| clio-privfin | 12 | Odoo accounting? | Framtid |
| clio-rag | 13 | Delas med vigil-index | Framtid |
| clio-research | 9 | Kanske Odoo-wizard | Framtid |
| clio-docs | 1 | Stannar i CLI | Permanent CLI |
| clio-vision | 2 | Stannar i CLI | Permanent CLI |
| clio-transcribe | 3 | Stannar i CLI | Permanent CLI |
| clio-narrate | 4 | Stannar i CLI | Permanent CLI |
| clio-audio-edit | 5 | Stannar i CLI | Permanent CLI |
| clio-library | 6 | Stannar i CLI | Permanent CLI |
| clio-emailfetch | 7 | Stannar i CLI | Permanent CLI |
| clio-fetch | 8 | Stannar i CLI | Permanent CLI |

---

## 4. Arkitektur

### 4.1 Övergripande bild

```
Användare
  │
  ├── CLI (standalone):   python clio-agent-job/run.py [--odoo | --no-odoo]
  ├── CLI (samlat):       python clio2.py
  │
  └── Odoo GUI:           Kontakter → Jobbprofil / Bevakningslista / Vigil
                                │
                         [Odoo-addon: clio_job / clio_obit / clio_vigil]
                                │
                          Odoo-modeller (profiler, resultat, kö, tillstånd)
                                │
                    ←── XML-RPC ──→
                                │
                     Python-backend på EliteDesk GPU
                     (run.py, analyzer.py, filter.py, orchestrator.py ...)
                                │
                     Externa tjänster: RSS, YouTube, Whisper, Qdrant, SMTP
```

### 4.2 Principen: "Odoo äger data — server exekverar"

- **Odoo** äger konfiguration, profiler, prenumeranter, resultat
- **Python-backend** kör logiken (RSS-parsing, Claude, Whisper, Qdrant)
- Backend **läser** från Odoo via XML-RPC vid start
- Backend **skriver** resultat + heartbeat till Odoo vid slut
- **Fallback:** `--no-odoo` → YAML/SQLite (krav 1, standalone)

### 4.3 Det delade mönstret (etableras i Release 1, återanvänds)

Varje agent som migreras till Odoo får:

```
clio-agent-job/
  odoo_reader.py   # Läser profiler/config från Odoo via XML-RPC
  odoo_writer.py   # Skriver matchningar + heartbeat till Odoo
```

Befintlig `clio_odoo/connection.py` hanterar autentisering — återanvänds rakt av.

`run.py` väljer datakälla dynamiskt:

```python
if cfg.odoo_enabled:
    profiles = odoo_reader.load_profiles()
else:
    profiles = yaml_loader.load_profiles()  # befintligt fallback
```

### 4.4 Heartbeat (clio_cockpit)

Varje agent skriver en `clio.tool.heartbeat`-post efter körning:

```
tool_name | last_run | status (ok/warning/error) | items_processed | message
```

---

## 5. Befintligt läge

### clio_job (Odoo-addon v2.0.0)
- ✅ `clio.job.profile` — komplett modell
- ✅ `clio.job.match` — matchningshistorik
- ✅ Views och menystruktur
- ❌ `odoo_reader.py` saknas (Python-sidan läser fortfarande YAML)
- ❌ `odoo_writer.py` saknas
- ❌ `migrate_yaml_to_odoo.py` — skelett finns, ej komplett

### clio_obit (Odoo-addon v1.0.0)
- ✅ `res.partner`-utökning med bevakningsfält och prioritet
- ✅ `clio.partner.link` för familjerelationer
- ❌ `clio.obit.hit` — träffmodell saknas
- ❌ `odoo_reader.py` / `odoo_writer.py` saknas

### clio_vigil (Odoo-addon)
- ❌ Inget addon byggt ännu

### clio_cockpit (Odoo-addon v2.0.0)
- ✅ Grundstruktur och menystruktur klar
- ❌ `clio.tool.heartbeat`-modell saknas

---

## 6. Releaseplan

### Release 1 — clio-agent-job (mönsteretablering)

**Mål:** Odoo är primär datakälla. Matchningar syns i Odoo. Mönstret etableras.

**Python-sidan:**
- `odoo_reader.py` — hämtar `clio.job.profile` via XML-RPC
- `odoo_writer.py` — skapar `clio.job.match`-post + heartbeat
- `run.py` — `--odoo` / `--no-odoo` flagga

**Odoo-sidan:**
- Inga modellförändringar (redan kompletta)
- Eventuellt `ir.cron`-post för daglig körning

**Datamigration:**
- Färdigställ `migrate_yaml_to_odoo.py`
- Importera: richard, ulrika, elin, miracle, fredrik

**Verifiering:**
- [ ] `python run.py --dry-run` läser från Odoo
- [ ] Matchad artikel → `clio.job.match`-post i Odoo
- [ ] Heartbeat syns i clio_cockpit
- [ ] `python run.py --no-odoo` fungerar fortfarande (standalone)
- [ ] clio-agent-job tas **bort ur clio2.py**

---

### Release 2 — clio-agent-obit

**Odoo-sidan (clio_obit v2.0.0):**
- Ny modell: `clio.obit.hit` (partner_id, source_url, matched_name, confidence, found_at, notified)
- Ny vy: träfflista per kontakt

**Python-sidan:**
- `odoo_reader.py` — bevakningslista från res.partner
- `odoo_writer.py` — skapar `clio.obit.hit`-poster
- Heartbeat

**Datamigration:**
- `watchlist/`-YAML → res.partner med `clio_obit_watch=True`
- `state.db` träffar → `clio.obit.hit` (om möjligt)

**Verifiering:**
- [ ] Bevakningslista hanteras i Odoo
- [ ] Träff skapar post i Odoo
- [ ] clio-agent-obit tas **bort ur clio2.py**

---

### Release 3 — clio-vigil

**Odoo-sidan (clio_vigil, nytt addon):**

Modeller:
- `clio.vigil.source` — källdefinition (namn, URL, domän, aktiv, keyword-filter)
- `clio.vigil.item` — insamlat objekt med statusmaskin (discovered → queued → transcribed → indexed)
- `clio.vigil.summary` — sammanfattning per item
- `clio.vigil.domain` — domänkonfiguration (ufo, ai, ...)

Vyer:
- Källlista med aktivering/avaktivering
- Kö (lista med status)
- Summor per item
- Statistik per domän

**Python-sidan:**
- `odoo_reader.py` — källkonfiguration och domäner från Odoo
- `odoo_writer.py` — uppdaterar item-status, sparar summor
- `main.py` — `--odoo` / `--no-odoo`

**Datamigration:**
- `config/ufo.yaml`, `config/ai.yaml` → `clio.vigil.source`
- `state.db` → `clio.vigil.item`

**Verifiering:**
- [ ] Källkonfiguration hanteras i Odoo
- [ ] Item-status uppdateras i Odoo under pipeline
- [ ] Summor läsbara i Odoo
- [ ] clio-vigil tas **bort ur clio2.py**

---

### Release 4 — clio_cockpit (uppdatering)

**Ny modell:** `clio.tool.heartbeat`
- `tool_name`, `last_run`, `status` (ok/warning/error), `items_processed`, `message`
- Listvy med färgkodad status

Skrivs av alla agenter via delat mönster i `odoo_writer.py`.

---

## 7. Öppna frågor

| # | Fråga | Prioritet |
|---|-------|-----------|
| 1 | Ska `ir.cron` i Odoo ersätta systemd-timern, eller körs båda parallellt? | Medel |
| 2 | clio_cockpit: ska den trigga körningar (knapp → RPC) eller bara visa status? | Medel |
| 3 | Vigil-items: rensas efter viss tid eller arkiveras permanent i Odoo? | Låg |
| 4 | clio-privfin: Odoo accounting eller evig CLI? | Låg |

---

## 8. Nästa steg

1. ✅ `clio.py` → `clio1.py` (parkerad)
2. ✅ `clio2.py` skapad med alla verktyg
3. 🔜 `migrate_yaml_to_odoo.py` — importera job-profiler till Odoo
4. 🔜 `odoo_reader.py` för clio-agent-job
5. 🔜 `odoo_writer.py` för clio-agent-job (match + heartbeat)
6. 🔜 `clio.tool.heartbeat`-modell i clio_cockpit
7. 🔜 Verifiera end-to-end: profil i Odoo → körning → matchpost → heartbeat
