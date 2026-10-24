# import_psalms.py — CLAUDE.md

Importerar begravningspsalmer från `begravningspsalmer.json` till `clio.reco.item` (item_type=link) via XML-RPC.

## Köra

```bash
cd clio_reco/importers
cp .env.example .env   # fyll i ODOO_PASSWORD
python import_psalms.py --dry-run   # se vad som skulle hända
python import_psalms.py             # kör på riktigt
```

## Fältmappning

| JSON-fält       | Odoo-fält   | Kommentar                                      |
|-----------------|-------------|------------------------------------------------|
| title + psalm_nr| name        | Format: "Härlig är jorden (nr 297)"            |
| composer_text   | author      |                                                |
| spotify_url     | url         | Upsert-nyckel (primär)                         |
| genre           | genre_ids   | + alltid "Begravningspsalm" som fast genre     |
| subtitle        | description | Del av HTML-beskrivning                        |
| theme           | description | Del av HTML-beskrivning                        |
| mood            | description | Del av HTML-beskrivning                        |
| begravning_rank | description | Del av HTML-beskrivning                        |
| notes           | description | Del av HTML-beskrivning                        |

## Upsert-logik

1. Om `spotify_url` finns: sök på url
2. Annars: sök på namn med psalm_nr
3. Hittas post → UPDATE, annars → CREATE

## Lägga till fler psalmer

Lägg till nya objekt i `tracks`-arrayen i JSON-filen och kör scriptet igen.
Varje psalm får alltid genre-taggen "Begravningspsalm" automatiskt.

## Beroenden

```
pip install python-dotenv
```
