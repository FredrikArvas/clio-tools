from pathlib import Path

# Muskö center — WGS84
MUSKO_CENTER_LAT = 59.01
MUSKO_CENTER_LON = 18.08

# Tile settings
ZOOM = 12          # Zoom 12 ≈ 5 km/tile vid 59°N
TILES_WIDE = 7     # Antal tiles horisontellt (7 ≈ 17 km)
TILES_TALL = 7     # Antal tiles vertikalt

# Tile URL templates
RADAR_TILE_URL = "https://d-tiles.vackertvader.se/tiles/regnradar/{z}/{x}/{y}.png"
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_USER_AGENT = "clio-weather/1.0 (arvas.international)"

# Storage
FRAMES_DIR = Path(__file__).parent / "frames"
LOG_FILE = Path(__file__).parent / "radar_collector.log"
RETENTION_DAYS = 365
