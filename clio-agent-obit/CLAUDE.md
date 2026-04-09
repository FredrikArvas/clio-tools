# clio-agent-obit — CLAUDE.md

## Läs detta först

Hämta Context Card innan du gör något annat:
https://www.notion.so/33c67666d98a814c9d47f3cb2976b81b

---

## Miljö

- OS: Windows
- Shell: PowerShell (`$env:VARIABEL = "värde"`, inte `export`)
- Python: 3.x
- Repo placeras i: `clio-tools/clio-agent-obit/`
- Delade utilities: `clio-core`-paketet (pip install -e clio-core)

---

## Projektbeskrivning

Automatisk bevakning av svenska dödsannonser mot en personlig bevakningslista.
Körs 1×/dag (morgon). Notifierar via epost till clio@arvas.se.
Tyst under drift — logg visar senaste körning, inga outputs om inget händer.

---

## Filstruktur att bygga

```
clio-agent-obit/
├── CLAUDE.md                    ← den här filen
├── check_deps.py                ← verifiera beroenden (clio-tools-mönster)
├── requirements.txt             ← feedparser, python-gedcom, smtplib ingår i stdlib
├── run.py                       ← huvudscript, agent-ready
├── matcher.py                   ← namnmatchning med konfidenspoäng
├── notifier.py                  ← epost direkt (viktig) + daglig digest
├── state.db                     ← SQLite, skapas automatiskt vid första körning
├── obit.log                     ← körningslogg (datum, annonser lästa, träffar)
├── sources/
│   ├── __init__.py
│   ├── source_base.py           ← abstrakt basklass
│   └── source_familjesidan.py  ← RSS-läsare (primärkälla)
└── watchlist/
    ├── __init__.py
    ├── watchlist.csv            ← bevakningslistan (se format nedan)
    ├── import_gedcom.py         ← extraherar namn ur GEDCOM → watchlist.csv
    └── import_contacts.py       ← importerar adressbok CSV → watchlist.csv
```

---

## watchlist.csv — format

```csv
efternamn,förnamn,födelseår,hemort,prioritet,källa
Frisk,Göran,1945,Haninge,viktig,manuell
Arvas,Christer,1942,,viktig,gedcom
Andersson,Lars,,Nacka,normal,adressbok
```

Fält:
- `födelseår` — tomt om okänt. Obligatoriskt för prioritet `viktig`.
- `hemort` — tomt om okänt.
- `prioritet` — `viktig | normal | bra_att_veta`
- `källa` — `manuell | gedcom | adressbok`

---

## Matchningslogik — konfidenspoäng

| Signal | Poäng |
|--------|-------|
| Exakt efternamnsträff | +40 |
| Exakt förnamnsträff | +30 |
| Förnamnsträff fuzzy (smeknamn, variant) | +20 |
| Födelseår känt i annons, matchar ±5 år | +20 |
| Hemort matchar | +10 |
| **Tröskelvärde för notis** | **≥ 60** |

Falska positiver är OK. Falska negativa är INTE OK.

---

## Notifieringsstrategi

- `viktig` → epost direkt vid träff
- `normal` + `bra_att_veta` → samlas i daglig digest (skickas om det finns träffar)
- Epost: clio@arvas.se
- Autentisering via `.env` (aldrig i kod eller CLAUDE.md)

`.env`-variabler att förvänta sig:
```
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASSWORD=
NOTIFY_TO=clio@arvas.se
```

---

## Körningslogg — obit.log

Varje körning skriver en rad:
```
2026-04-08 08:15:02 | annonser: 143 | träffar: 0 | digest: nej
2026-04-08 08:15:14 | annonser: 156 | träffar: 1 | digest: ja | VIKTIG: Frisk Göran
```

Senaste rad visas av clio-tools environment-check.

---

## Primärkälla — multi-source via sources.yaml (0.2.0)

Sprint 1 antog att familjesidan.se hade RSS. Verifiering 2026-04-08 visade
att inga svenska dödsannonskällor exponerar publik RSS. Designprincipen
omformulerades till "**stable-source-first via pluggable adaptrar**".

Aktiva källor definieras i `sources.yaml` i clio-agent-obit-roten:

```yaml
version: 1
sources:
  - name: familjesidan-stockholm
    enabled: true
    adapter: source_familjesidan_html.FamiljesidanHtmlSource
    config:
      base_url: https://www.familjesidan.se
      newspapers: [461]
  - name: fonus-national
    enabled: true
    adapter: source_fonus.FonusSource
    config:
      url: https://minnessidor.fonus.se/
```

Lägga till en ny källa:

```powershell
python sources/discover.py probe https://example.se --add example
# Editera sources.yaml, sätt enabled: true, justera selektorer
python run.py --dry-run
```

Den deprekerade RSS-adaptern finns kvar i `sources/source_familjesidan_rss.py`
för framtiden om RSS skulle dyka upp.

---

## state.db — SQLite

Tabell `seen_announcements`:
```sql
CREATE TABLE seen_announcements (
    id TEXT PRIMARY KEY,       -- unik identifierare från RSS-item (guid/link)
    first_seen TEXT,           -- ISO-datum
    matched INTEGER DEFAULT 0  -- 1 om den triggade notis
);
```

Undviker att samma annons notifierar flera körningar.

---

## Agent-ready-krav (alla scripts)

```python
def parse_args(argv=None):
    ...

def main(argv=None):
    args = parse_args(argv)
    ...

if __name__ == "__main__":
    main()
```

Inga hårdkodade `sys.argv`. Inga oundvikliga interaktiva prompts.

---

## check_deps.py

Verifiera:
- feedparser
- python-gedcom (för import_gedcom.py)
- sqlite3 (stdlib)
- smtplib (stdlib)
- clio_core (från clio-core-paketet)
- .env-fil finns
- watchlist.csv finns och är läsbar

---

## Designprinciper

- **Stable-source-first via pluggable adaptrar:** Källor är HTML eller RSS,
  registreras i `sources.yaml`. Adaptrar är utbytbara, gränssnittet stabilt.
- **Watchlist är kärnan:** Källor byts ut. Bevakningslistan lever i decennier.
- **Tyst under drift:** Inga outputs om inget händer.
- **Felhantering externt:** Tysta krascher fångas av clio-tools environment-check.
- **Födelseår på viktiga:** Manuellt inlagt för `viktig`. Övriga matchas på namn + ort.
- **Logg alltid:** Varje körning loggar även om inga träffar.

---

## Testperson

**Göran Frisk** — referenscase. Verifiera att systemet *skulle ha hittat* hans annons
om det hade körts veckan 2026-04-08. Används för regressionstestning av matcher.py.

---

## Arbetsfördelning

- **Claude.ai:** Arkitektur, resonemang, Context Card-uppdateringar
- **Claude Code:** All implementation

Uppdatera Context Card i Notion efter varje sprint:
https://www.notion.so/33c67666d98a814c9d47f3cb2976b81b
