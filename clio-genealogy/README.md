# clio-research

Persondata-pipeline för Clio Relationsminne (CRM).
Samlar data från GEDCOM → Wikidata → Wikipedia → Libris.
Sparar till Notion Personregister med full provenans per fält.

## Kom igång

```powershell
cd clio-tools\clio-research
pip install -r requirements.txt
copy .env.example .env
# Fyll i NOTION_TOKEN i .env
```

## Användning

```powershell
# Testa utan att spara (rekommenderat första gången)
python research.py --gedcom-id "@I294@" --gedcom-file "..\..\..\..\Documents\Dropbox\ulrika-fredrik\släktforskning\släkten Fredrik arvas\släktträdsfiler\ChristersFredriksSammanslagna - 2010-09-20.ged" --dry-run

# Kör och spara till Notion
python research.py --gedcom-id "@I192@" --gedcom-file "..\..\..\..\Documents\Dropbox\ulrika-fredrik\släktforskning\släkten Fredrik arvas\släktträdsfiler\ChristersFredriksSammanslagna - 2010-09-20.ged" --syfte guldboda-75

# Godkänn ett granskningskort
python research.py --approve <notion-page-id>

# Batch — alla Arvas-personer
python research.py --batch --gedcom-file "..\..\..." --filter-surname Arvas --syfte guldboda-75

# Visa väntande granskningskort
python research.py --status
```

## Tester

```powershell
# Enhetstester (snabba, ingen nätverkstrafik)
python -m pytest tests/test_confidence.py tests/test_gedcom.py -v

# Integrationstester (kräver internet, ~30 sek)
python -m pytest tests/test_pipeline.py -v

# Alla tester
python -m pytest tests/ -v
```

## Testpersoner

| Person | GEDCOM-ID | Förväntat resultat |
|---|---|---|
| Dag Gustaf Christer Arvas | `@I294@` | Alla fält ≥ 0.70, sparas direkt |
| Birgitta Arvas | `@I192@` | Wikipedia saknas → granskningskort |
| Fredrik Johan Gustaf Arvas | `@I411@` | Levande person → minimerad data, GDPR-flagga |

> **OBS:** Handover-dokumentet angav felaktigt `@I379@` för Dag Arvas.
> Korrekt GEDCOM-ID i filen `ChristersFredriksSammanslagna - 2010-09-20.ged` är `@I294@`.

## Arkitektur

| Fil | Syfte |
|---|---|
| `research.py` | CLI entry point (argparse) |
| `pipeline.py` | Orchestrerar källorna och konfidens |
| `confidence.py` | ConfidenceModel-klass |
| `notion_writer.py` | Skriver till Personregistret, skapar granskningskort |
| `sources/gedcom.py` | GedcomSource — läser .ged-fil |
| `sources/wikidata.py` | WikidataSource — SPARQL mot query.wikidata.org |
| `sources/wikipedia.py` | WikipediaSource — REST API (sv + en) |
| `sources/libris.py` | LibrisSource — SRU API |

## Designbeslut

Se `DECISIONS.md` för de 10 låsta arkitekturbesluten (ADR-001–010).

Viktigaste avvikelserna från handover-spec:
- **Libris SRU-frågesyntax:** `dc.creator="..."` returnerar 0 träffar i nuvarande API.
  Korrekt syntax är `"EFTERNAMN" AND "FÖRNAMN"`.
- **Dag Arvas GEDCOM-ID:** Handover anger `@I379@` (Ervin Molin). Korrekt är `@I294@`.
- **Wikipedia-filtrering:** Sökning filtrerar artiklar vars titel inte matchar personnamnet,
  för att undvika falska träffar (t.ex. utställningssidor).

## Miljövariabler

```
NOTION_TOKEN=secret_xxx      # Obligatorisk (utan --dry-run)
GEDCOM_DEFAULT_FILE=...      # Valfri default-sökväg
```
