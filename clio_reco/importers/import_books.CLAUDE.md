# import_books.py — CLAUDE.md

Importerar böcker från `books_about_death.json` till `clio.reco.item` (item_type=book) via XML-RPC.

## Köra

```bash
cd clio_reco/importers
cp .env.example .env   # fyll i ODOO_PASSWORD
python import_books.py --dry-run   # se vad som skulle hända
python import_books.py             # kör på riktigt
```

## Fältmappning

| JSON-fält       | Odoo-fält       | Kommentar                        |
|-----------------|-----------------|----------------------------------|
| title           | name            |                                  |
| author          | author          |                                  |
| year            | year            |                                  |
| isbn            | isbn            | Upsert-nyckel (primär)           |
| category        | genre_ids       | Skapas automatiskt som genre-tagg |
| theme           | description     | Del av HTML-beskrivning          |
| description     | description     | Del av HTML-beskrivning          |
| relevance       | description     | Del av HTML-beskrivning (kursiv) |

## Upsert-logik

1. Om `isbn` finns: sök på `isbn + item_type=book`
2. Annars: sök på `title + author + item_type=book`
3. Hittas post → UPDATE, annars → CREATE

## Lägga till fler böcker

Lägg till nya objekt i `books`-arrayen i JSON-filen och kör scriptet igen.
Redan importerade böcker uppdateras (title/author/description), nya skapas.

## Beroenden

```
pip install python-dotenv
```
