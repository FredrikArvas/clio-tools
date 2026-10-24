# import_songs.py — CLAUDE.md

Importerar låtar från `death_songs.json` till `clio.reco.item` (item_type=link) via XML-RPC.

## Köra

```bash
cd clio_reco/importers
cp .env.example .env   # fyll i ODOO_PASSWORD
python import_songs.py --dry-run   # se vad som skulle hända
python import_songs.py             # kör på riktigt
```

## Fältmappning

| JSON-fält   | Odoo-fält   | Kommentar                                      |
|-------------|-------------|------------------------------------------------|
| title       | name        | Kombineras med artist: "Titel — Artist"        |
| artist      | author      |                                                |
| spotify_url | url         | Upsert-nyckel (primär)                         |
| genre       | genre_ids   | Splittas på "/" — "Rock/Folk" → två genrer     |
| theme       | description | HTML-paragraf                                   |

## Upsert-logik

1. Om `spotify_url` finns: sök på url
2. Annars: sök på name (title — artist)
3. Hittas post → UPDATE, annars → CREATE

## Lägga till fler låtar

Lägg till nya objekt i `tracks`-arrayen i JSON-filen och kör scriptet igen.
Redan importerade låtar uppdateras (namn/beskrivning), nya skapas.

## Genre-hantering

Genre-strängar som "Rock/Folk" splittas automatiskt till två separata genre-taggar.
Genrer skapas om de inte finns, och återanvänds om de redan finns.
