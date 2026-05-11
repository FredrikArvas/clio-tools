# [Projektnamn] — CLAUDE.md
# Instruktioner för Claude Code. Läs detta innan du gör något i repot.
#
# Detta är en mall. Kopiera till CLAUDE.md och fyll i era egna detaljer.
# CLAUDE.md är gitignorerad (stannar lokalt) — CLAUDE.template.md committeras.

## Projektkontext

[Beskriv projektet kortfattat: vad det gör, vem som äger det, vilken roll
Claude har i arbetet.]

Styrningsdokument: [Länk eller sökväg till er handbok/playbook om sådan finns]

---

## Repo-struktur

```
[projekt]/
├── [modul-1]/     [Kort beskrivning]
├── [modul-2]/     [Kort beskrivning]
└── [delad-lib]/   Delade verktyg — duplicera aldrig härifrån
```

Kodstandard: [sökväg till kodstandard om sådan finns]

---

## Säkerhetsregler (absoluta, inga undantag)

- API-nycklar och lösenord skrivs ALDRIG i kod eller i git
- Alla hemligheter lever i .env-filer
- .env är alltid i .gitignore
- Externa inputs valideras alltid (webhooks, mail, API-svar)
- Tysta undantag är förbjudna: `except: pass` utan loggning är en bugg

---

## AI/LLM-regler (anpassa eller ta bort om projektet inte använder LLM)

- Modellnamn är ALLTID konstanter, aldrig hårdkodade strängar
  ```python
  MODEL_PRIMARY   = "[modell-id]"
  MODEL_SECONDARY = "[modell-id]"
  ```
- Prompts separeras från anropslogik (egna variabler eller filer)
- API-anrop hanterar rate limits och timeouts explicit

---

## Namnstandard

[Fyll i er namnstandard. Exempel för Python/PEP 8:]

| Element            | Standard         | Exempel                   |
|--------------------|------------------|---------------------------|
| Moduler/paket      | snake_case       | my_module, data_loader    |
| Klasser            | PascalCase       | DataStore, ApiClient      |
| Funktioner/metoder | snake_case       | run_query, send_email     |
| Konstanter         | UPPER_SNAKE_CASE | MAX_TOKENS, BASE_URL      |
| Privata attribut   | _snake_case      | _load_config              |
| Booleans           | is_/has_/can_    | is_valid, has_data        |

Förbjudet: förkortningar (cfg, ctx, auth), synonymer för samma koncept.

---

## Kodstruktur

- Funktioner: max ~50 rader, ett ansvar
- Nästlingsdjup: max 3 nivåer
- Delade verktyg: [delad-lib] — duplicera aldrig
- Separation: affärslogik, datalagring och notifiering i separata moduler
- Döda kod tas bort direkt

---

## Tester

- [Testramverk, t.ex. pytest]
- Kör [testkommando] före push
- Tester bevisar BÅDE lyckade och misslyckade vägar
- [Eventuell CI/pre-push hook]

---

## Infrastruktur

- Produktionsmiljö: [server/plattform]
- Utvecklingsmiljö: [lokal maskin/IDE]
- Versionskontroll: [repo-URL]

Deploy: [deploy-kommando]
Rollback: [rollback-kommando]

---

## Arkitekturbeslut (ADR)

Alla betydande beslut dokumenteras som ADR i [verktyg/plats].
ADR innehåller: problemformulering, valt alternativ, förkastade alternativ,
påverkan på arkitektur/säkerhet/drift.

---

## Definition of Done — snabbversion

En ändring får pushas till main ENDAST om:

**Kod och säkerhet**
- [ ] Alla tester gröna
- [ ] Inga hårdkodade hemligheter
- [ ] .env utanför git
- [ ] API-fel hanteras explicit

**Tester**
- [ ] Nya funktioner täcks av tester
- [ ] Både lyckad och misslyckad väg testas
- [ ] Befintliga tester bryter inte

**Dokumentation**
- [ ] [Kunskapssystem] uppdaterat med sessionsbeslut
- [ ] CLAUDE.md uppdaterad om install/usage ändrats
- [ ] Arkitekturbeslut dokumenterade som ADR

**[Lägg till era egna sektioner här]**

Kör `/dod-check` för interaktiv genomgång mot aktuella ändringar.

---

## Modul-specifika CLAUDE.md

[Lista moduler med egna CLAUDE.md-filer om sådana finns:]
- [modul]/CLAUDE.md

---

## Anpassningsguide

När du kopierar denna mall till CLAUDE.md:

1. Fyll i projektnamn och kontext (sektion 1)
2. Uppdatera repo-strukturen med era faktiska moduler
3. Lägg till er specifika infrastruktur (serveradresser, deploy-kommandon)
4. Anpassa namnstandarden till ert språk/ramverk
5. Lägg till projektsspecifika DoD-kriterier
6. Ta bort sektioner som inte är relevanta (t.ex. AI/LLM-regler)
7. Ta bort denna anpassningsguide
