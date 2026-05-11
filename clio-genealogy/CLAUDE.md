# clio-genealogy — CLAUDE.md

## Syfte
Persondata-pipeline för Clio Relationsminne. Samlar data från GEDCOM, Wikidata, Wikipedia och Libris, sparar till Notion Personregister med fullständig proveniering per fält.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
copy .env.example .env           # Fyll i NOTION_TOKEN
python research.py --gedcom-id "@I294@" --gedcom-file "...ged" --dry-run
python research.py --gedcom-id "@I294@" --gedcom-file "...ged"
python research.py --approve <notion-page-id>
python research.py --batch --gedcom-file "..." --filter-surname Arvas
python research.py --status
```

## Nyckelkod
- `research.py` — CLI entry point
- `pipeline.py` — Källorkestrering och konfidensmodell
- `notion_writer.py` — Notion Personregister-writer
- `sources/gedcom.py` — GEDCOM-läsare
- `sources/wikidata.py` — SPARQL mot query.wikidata.org
- `sources/wikipedia.py` — REST API (sv + en)
- `sources/libris.py` — SRU API
- `docs/adr/` — Arkitekturbeslut (10 låsta ADR:er)

## Beroenden
Externa: gedcom, requests, notion-client
Interna: clio-core

## Relaterade moduler
clio-core, clio_access, clio-partnerdb

## Gotchas
GEDCOM-ID för Dag Gustaf Christer Arvas är @I294@ (inte @I379@). Libris-syntax: `"EFTERNAMN" AND "FÖRNAMN"` (inte dc.creator=). Levande personer får minimerad data + GDPR-flagga. Se docs/adr/ för 10 låsta designbeslut.
