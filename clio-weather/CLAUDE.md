# clio-weather

Radarbildsinsamlare för södra Muskö. Hämtar radardata från regnradar.se var 5:e minut och sparar PNG-frames med kartbakgrund + regnöverlagring.

## Syfte
Illustrera hur regnväder rör sig österut och "missar" södra Muskö.

## Arkitektur
- **Karta (cachad):** OSM-tiles hämtas en gång och sparas som `map_background.png`
- **Radar (per körning):** Senaste obs-bild från `https://api.regnradar.se/radar` (JSON API)
- **Komposit:** Radar croppas till tile-gridens geografiska bounds, skalas upp med Gaussian blur, maskeras (vitt/grått = transparent) och klistras på kartan

## Filer
- `radar_collector.py` — huvudskript: karta + radar → 1000px PNG med tidsstämpel
- `create_animation.py` — skapar MP4 eller GIF från sparade frames
- `config.py` — koordinater, zoom, sökvägar
- `map_background.png` — cachad OSM-karta (tas bort för att tvinga omhämtning)
- `frames/` — tidsstämplade PNG:er (`YYYY-MM-DD_HHMM_rain.png` / `_dry.png`)

## Konfiguration (config.py)
- Center: 59.01°N, 18.08°E (södra Muskö)
- Zoom: 12 (≈ 5 km/tile) — 7×7 tiles → 1000×1000 px output
- Retention: 365 dagar

## Radar-API
- Endpoint: `https://api.regnradar.se/radar`
- Returnerar JSON med lista av Nordic radar-bilder (obs + fcst)
- Bildens geografiska bounds: SW=(53.084°N, -8.034°E) NE=(73.056°N, 40.787°E)
- Filnamnsuffixes: `_rain` (regn detekterat) / `_dry` (uppehåll)

## Cron
Tjänsten är för närvarande pausad (cron borttagen 2026-06-16).
För att återaktivera:
```
*/5 * * * * cd ~/18.0/clio-tools/clio-weather && /home/clioadmin/18.0/clio-tools/.venv/bin/python3 radar_collector.py >> radar_collector.log 2>&1
```

## Animation
```bash
python3 create_animation.py --last 288 --format mp4           # ett dygn
python3 create_animation.py --last 288 --format mp4 --only-rain  # bara regnframes
```

## Samba-share
Share: `clio-weather` → monteras som `W:` på FA_Elitebook2
