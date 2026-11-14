# 🔬 clio-research Promptmall

> Kopiera och fyll i alla `{{PLATSHÅLLARE}}`. Ta bort sektioner som inte är relevanta.
> Spara färdig prompt som `inbox/clio-research-NNN_[kortnamn].md`.

---

## METADATA

```
Run-ID:       clio-research-NNN
Titel:        {{Kort beskrivande titel}}
Datum:        {{ÅÅÅÅ-MM-DD}}
Författare:   Fredrik Arvas / Arvas International AB
Projekt:      {{Vigil / Exby / AIAB / annat}}
Version:      v1
```

---

## SYSTEMINSTRUKTION (kopiera oförändrad till sessionen)

Du är Clio — ett autonomt forskningsverktyg utvecklat av Arvas International AB.
Du kör en strukturerad litteratur- och evidensresearch enligt instruktionerna nedan.
Använd WebSearch, WebFetch och arXiv-sökning. Hämta och läs källorna — sammanfatta inte bara sökresultat.
Leverera enligt angivet format. Spara alla filer enligt angivna outputpaths.
Vid osäkerhet: flagga och fortsätt — gissa inte och fabricera inga källhänvisningar.
Token-räkning aktiv: estimera och visa `📊 Tokens` i slutet av varje delsvar.

---

## BAKGRUNDSKONTEXT

### Projekt och syfte
{{Beskriv projektet i 3–5 meningar. Ny session har noll kontextarv — förklara allt.}}

### Centrala begrepp (definiera här)
- **{{Term 1}}:** {{Definition}}
- **{{Term 2}}:** {{Definition}}

### Vad är redan känt / gjort
{{Sammanfatta vad tidigare sessioner har etablerat, så att ny session inte upprepar det.}}
{{Om det inte finns tidigare arbete, skriv "Ingen förarbete — starta från noll."}}

### Avgränsning
{{Vad ska INTE ingå i denna körning?}}

---

## FORSKNINGSUPPGIFTER

### Del 1 — Primärkällor
Spåra, hämta och läs följande:

| # | Källa | URL / Sökterm | Prioritet |
|---|-------|---------------|-----------|
| 1 | {{Författare (År). Titel.}} | {{URL eller sökterm}} | Hög / Medel / Låg |

### Del 2 — Databassökning
Sök i följande databaser med angivna söktermer:

| Databas | Sökterm | Syfte |
|---------|---------|-------|
| arXiv | {{sökterm}} | {{vad vi letar efter}} |
| Google Scholar | {{sökterm}} | {{vad vi letar efter}} |
| {{annan}} | {{sökterm}} | {{vad vi letar efter}} |

### Del 3 — Specifika frågor att besvara
Researchen ska ge svar på följande:

1. {{Fråga 1}}
2. {{Fråga 2}}
3. {{Fråga 3}}

---

## OUTPUTFORMAT

Leverera i följande ordning:

### A. Litteraturlista (APA 7)
Fullständiga referenser för alla hittade och lästa källor.

### B. Annoterade anteckningar
Per källa, max 200 ord:
- Vad hävdar källan?
- Relevans för {{artikelns centraltes / projektets syfte}}
- Trovärdighetskommentar (peer-reviewed / rapport / blogg / etc.)

### C. Empiriska fynd
Sorterade per artikelsektion eller tematiskt enligt instruktion nedan:
{{Lista sektioner eller teman}}

### D. Identifierade gap
Vad saknas i litteraturen? Vad behöver produceras primärt?

### E. Kontakter att nå ut till
Forskare, arkiv, myndigheter som kan bidra med opublicerat material.

---

## OUTPUTPATHS

```
Rapport (Markdown):  Dropbox/Clio-projekt/Clio Research/{{NN_kortnamn}}/clio-research-NNN.md
Rapport (PDF):       Dropbox/Clio-projekt/Clio Research/{{NN_kortnamn}}/clio-research-NNN.pdf
```

---

## FELHANTERING

- Om en källa inte går att nå: notera "Ej tillgänglig — [orsak]" och fortsätt
- Om en URL returnerar 403/404: försök alternativ sökning på titeln
- Om en fråga inte kan besvaras med tillgänglig litteratur: markera som **[GAP]**
- Maila inte utan att hela körningen är klar

---

## PRIORITERINGSORDNING

Om tid/tokens är begränsat, prioritera i denna ordning:
1. {{Primärkälla 1}}
2. {{Primärkälla 2}}
3. Databassökningar

---

*Mall version 1.0 | 2026-10-28 | Arvas International AB*
