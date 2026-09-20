# clio-vision — CLAUDE.md

## Syfte

Analyserar bilder med Claude Vision API (eller Ollama lokalt) och producerar en strukturerad
MD-fil per bild med beskrivning, taggar och masterdata. Från v2.3.0 slår modulen även upp
GPS-koordinater mot `clio.location` i Odoo för att ge Claude ett precist platsnamn.

## Arkitektur

```
clio_vision.py          Huvudmodul — CLI, flöde, engine-val
clio_geo_import.py      Extraherar GPS ur bilder → klustrar → skapar clio.location-poster i Odoo
clio_geo_backfill.py    Nominatim-berikening av befintliga clio.location-poster (adress, country_id)
clio_geo_map.py         Genererar Leaflet HTML-karta över alla kända platser
```

## GPS-flöde (v2.3.0)

1. `get_gps_coords(image_file)` — extraherar lat/lon ur PIL EXIF
2. `find_nearest_location(lat, lon)` — anropar `clio.location/find_nearest` via xmlrpc mot Odoo (db: aiab)
3. Fallback: `reverse_geocoder` om Odoo inte svarar
4. Platshint skickas till Claude i user-meddelandet: *"GPS coordinates indicate the location is: ..."*
5. `masterdata.location` sätts från GPS om Claude lämnar fältet tomt
6. `masterdata.gps` läggs alltid till med koordinaterna

Xmlrpc-anslutning cachas i `_odoo_conn` — en uppkoppling per session.

## clio.location — Odoo-modellen

Repo: `~/clio-odoo-addons/clio_geo` (branch 19.0), installerad i db `aiab`.

Fält: `name`, `display_name_geo`, `lat`, `lon`, `radius_m` (default 100m), `category`,
`street`, `street_number`, `zip`, `city`, `country_id`, `notes`, `active`.

Metod: `find_nearest(lat, lon)` — haversine-sökning, returnerar `name`-strängen på närmaste
post inom `radius_m`, eller `False` om ingen träff.

Import-flöde:
```
python clio_geo_import.py  # extraherar GPS ur bildmapp → klustrar per 100m → skapar poster
python clio_geo_backfill.py  # Nominatim → street/city/country_id på alla poster
python clio_geo_map.py  # Leaflet-stickprov
```

## Köra modulen

```bash
# Interaktivt (välj engine i menyn)
python clio_vision.py "C:\Users\fredr\Dropbox\bilder\Camera uploads 2026"

# Agent-läge (ingen interaktivitet)
python clio_vision.py <mapp> --engine haiku --write-back --recursive --yes
```

Output per bild: `<bildnamn>_VISION.md` i samma mapp.

## Beroenden

```
anthropic / ANTHROPIC_API_KEY   Claude Vision
Pillow (PIL)                    EXIF-läsning + bildnedskalning
python-dotenv                   .env-hantering
requests                        Nominatim i backfill-skriptet
reverse_geocoder                Fallback-geokodning (optional)
pyexiftool + exiftool.exe       DigiKam XMP-metadata (optional)
```

Miljövariabler (`.env` i clio-tools-roten):
- `ANTHROPIC_API_KEY`
- `ODOO_URL` — t.ex. `https://aiab.arvas.international`
- `ODOO_USER`
- `ODOO_PASSWORD`
- `ODOO_DB` — default `aiab`

## Gotchas

- **EXIF-buggar**: negativ longitud kan placera en bild i fel hemisfär (kända fall: post [143]
  på Muskö fick lon = -18.06 → Vestmannaeyjar, Island). Kontrollera alltid bilder som hamnar
  utanför Sverige/Norden mot `clio_geo_map.py`.
- **Nominatim rate limit**: 1 anrop/s enligt OSM-policy. `clio_geo_backfill.py` använder
  2.0s sleep + 60s retry vid 429. Kör aldrig två instanser parallellt.
- **Python-buffring**: backfill-skriptet är långkörande — starta med `nohup` och läs loggen
  efter avslut (`/tmp/geo_backfill.log`), inte under körning.
- **Ollama-modell**: kör `ollama pull llava` och `ollama serve` lokalt innan engine=ollama.

## Versionshistorik

| Version | Datum      | Förändring |
|---------|------------|------------|
| 2.3.0   | 2026-09-20 | GPS-lookup via clio.location + Odoo xmlrpc-fallback |
| 2.0.1   | 2026-09-20 | DigiKam XMP-integration, bildnedskalning, date-checks |
