# clio-bookrev — CLAUDE.md

## Syfte
Identifiera stycken i en svensk bokversion som är konceptuellt bättre än originalet
på engelska, och föreslå förbättrad engelsk text baserat på den svenska versionen.

Bearbetningen sker lokalt i Claude Code (prenumerationsmodell, inte API-tokens).

---

## Arbetsflöde

### Steg 1 — Extrahera stycken (Python)
```
python reader.py --en boken_en.docx --sv boken_sv.docx \
  --chapter 3 --title-en "Awakening" --title-sv "Uppvaknandet" \
  --out testdata/chapter_03.json
```

Om böckerna inte är i Word-format: skapa JSON-filen manuellt enligt testdata/chapter_01.json.

### Steg 2 — Analysera (Claude Code-session)
Öppna en Claude Code-session och kör:
```
Analysera testdata/chapter_03.json enligt CLAUDE.md och spara resultatet till
testdata/chapter_03_improvements.json
```

Claude Code läser paren och identifierar förbättringar (se Analysinstruktioner nedan).

### Steg 3 — Generera Word-fil (Python)
```
python output.py \
  --improvements testdata/chapter_03_improvements.json \
  --out output/chapter_03_review.docx
```

---

## Analysinstruktioner (för Claude Code i steg 2)

Läs chapter_NN.json och analysera varje par (en + sv).

### Vad är en förbättring?
En förbättring föreligger när den svenska texten är **konceptuellt rikare** än originalet —
inte bara annorlunda p.g.a. idiom eller naturlig översättningsskillnad.

Tecken på förbättring:
- SV tillägger en insikt, ett exempel eller ett led i argumentet som EN saknar
- SV omstrukturerar argumentet till en starkare logisk ordning
- SV lägger till emotionell djup eller nyans som EN hoppar över
- SV korrigerar en otydlighet eller ett logiskt gap i EN

**Inte förbättring:**
- Friare formulering av samma innehåll
- Idiomatisk anpassning till svenska
- Längre text utan tillräckseende nytt innehåll

### Bedömningsskala
- **Klar förbättring**: ta med i improvements
- **Marginell skillnad**: hoppa över (lägg i unchanged)
- **Bara omformulering**: hoppa över

### Output-format (improvements JSON)

```json
{
  "chapter": "1",
  "title_en": "Awakening",
  "analysis_date": "YYYY-MM-DD",
  "improvements": [
    {
      "id": 2,
      "en_original": "Reality is not what we think it is. We construct our experience from incomplete data.",
      "sv_improved": "Verkligheten är inte vad vi tror att den är. Vi konstruerar vår upplevelse utifrån ofullständig data – men det intressanta är att vi aldrig märker bristerna, eftersom hjärnan fyller i luckorna med det den förväntar sig att se.",
      "motivation": "Swedish adds the key insight about the brain's gap-filling mechanism — this is the conceptual heart of the argument and was missing from the English.",
      "en_proposed": "Reality is not what we think it is. We construct our experience from incomplete data — and the remarkable thing is that we never notice the gaps, because the brain fills them with what it expects to see."
    }
  ],
  "all_pairs": [
    { "id": 1, "en": "..." },
    { "id": 2, "en": "..." },
    ...
  ]
}
```

`all_pairs` innehåller **alla** stycken (för att output.py ska kunna återge hela kapitlet,
inklusive oförändrade partier).

### Riktlinjer för en_proposed
- Behåll Roger originalröst och rytm
- Lägg in det som saknades — lägg inte till mer
- Kortare är bättre: om EN-meningen kan utökas med en bisats, gör det så
- Skriv på engelska med en lätt litterär ton (icke-akademisk)

---

## Filstruktur

```
clio-bookrev/
  reader.py               # docx → JSON
  output.py               # improvements JSON → Word
  CLAUDE.md               # detta dokument
  testdata/
    chapter_01.json       # konstruerat testkapitel (5 par)
    chapter_01_improvements.json   # produceras av Claude Code-session
  output/
    chapter_01_review.docx         # produceras av output.py
```

---

## Beroenden
Ingenting utöver vad som redan finns i clio-tools/requirements.txt:
- `python-docx>=0.8.11`
- `python-dotenv` (ej nödvändigt, men konsekvent med resten)
