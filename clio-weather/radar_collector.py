#!/usr/bin/env python3
import io
import logging
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import (
    MUSKO_CENTER_LAT, MUSKO_CENTER_LON,
    ZOOM, TILES_WIDE, TILES_TALL,
    OSM_TILE_URL, OSM_USER_AGENT,
    FRAMES_DIR, LOG_FILE, RETENTION_DAYS,
)

MAP_CACHE = Path(__file__).parent / "map_background.png"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

TILE_SIZE = 256
RAIN_PIXEL_THRESHOLD = 0.015

# Bounds för Nordic radar-bilden (från Leaflet imageOverlay i regnradar.se)
RADAR_SW_LAT, RADAR_SW_LON = 53.0841628421789, -8.03410177882381
RADAR_NE_LAT, RADAR_NE_LON = 73.0558890312605, 40.787194494374
RADAR_API = "https://api.regnradar.se/radar"


def deg2tile(lat, lon, zoom):
    lat_r = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    return x, y


def tile_to_latlonnw(tx, ty, zoom):
    """Nordvästra hörnet av tile (tx, ty)."""
    n = 2 ** zoom
    lon = tx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    return lat, lon


def merc_y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def latlon_to_radar_px(lat, lon, r_w, r_h):
    """Konverterar lat/lon till pixelkoordinat i Nordic-radarbilden."""
    y_sw = merc_y(RADAR_SW_LAT)
    y_ne = merc_y(RADAR_NE_LAT)
    y_p  = merc_y(lat)
    px_x = (lon - RADAR_SW_LON) / (RADAR_NE_LON - RADAR_SW_LON) * r_w
    px_y = (y_ne - y_p) / (y_ne - y_sw) * r_h
    return int(px_x), int(px_y)


def fetch_tile(url, session, retries=3):
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                return Image.open(io.BytesIO(resp.content)).convert("RGBA")
            if resp.status_code == 404:
                return None
        except Exception as e:
            if attempt == retries - 1:
                log.warning(f"Failed {url}: {e}")
            time.sleep(1)
    return None


def fetch_radar():
    """Hämtar senaste radar-PNG (obs, ej fcst) från api.regnradar.se."""
    resp = requests.get(RADAR_API, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    images = data["nordic"]["images"]
    obs = [i for i in images if i.get("type") != "fcst"]
    latest = obs[-1] if obs else images[-1]
    url = "https:" + latest["image_url"]
    r2 = requests.get(url, timeout=30)
    r2.raise_for_status()
    img = Image.open(io.BytesIO(r2.content)).convert("RGBA")
    log.info(f"Radar image: {url} ({latest['time_utc']})")
    return img


def detect_rain(radar_img):
    """Returnerar True om radarbilden innehåller tillräckligt med regnpixlar."""
    arr = np.array(radar_img.convert("RGB"))
    chroma = arr.max(axis=2).astype(int) - arr.min(axis=2).astype(int)
    ratio = (chroma > 40).sum() / chroma.size
    return bool(ratio > RAIN_PIXEL_THRESHOLD)


def build_composite(now):
    cx, cy = deg2tile(MUSKO_CENTER_LAT, MUSKO_CENTER_LON, ZOOM)
    log.info(f"Center tile: ({cx}, {cy}) zoom={ZOOM}")

    half_w = TILES_WIDE // 2
    half_h = TILES_TALL // 2
    x_start = cx - half_w
    y_start = cy - half_h

    img_w = TILES_WIDE * TILE_SIZE
    img_h = TILES_TALL * TILE_SIZE

    # Steg 1: OSM-karta som bakgrund (cachas på disk)
    if MAP_CACHE.exists():
        canvas = Image.open(MAP_CACHE).convert("RGB")
        log.info("Map loaded from cache")
    else:
        canvas = Image.new("RGB", (img_w, img_h), (200, 200, 200))
        session = requests.Session()
        session.headers["User-Agent"] = OSM_USER_AGENT
        fetched = 0
        for dy in range(TILES_TALL):
            for dx in range(TILES_WIDE):
                tx = x_start + dx
                ty = y_start + dy
                tile = fetch_tile(OSM_TILE_URL.format(z=ZOOM, x=tx, y=ty), session)
                if tile:
                    canvas.paste(tile.convert("RGB"), (dx * TILE_SIZE, dy * TILE_SIZE))
                    fetched += 1
        log.info(f"Map tiles fetched: {fetched}/{TILES_WIDE * TILES_TALL}")
        canvas.save(MAP_CACHE, "PNG")
        log.info(f"Map cached to {MAP_CACHE}")

    # Steg 2: Radar-overlay från api.regnradar.se
    has_rain = False
    try:
        radar_full = fetch_radar()
        r_w, r_h = radar_full.size

        # Beräkna tile-gridens geografiska hörn
        nw_lat, nw_lon = tile_to_latlonnw(x_start, y_start, ZOOM)
        se_lat, se_lon = tile_to_latlonnw(x_start + TILES_WIDE, y_start + TILES_TALL, ZOOM)

        rx1, ry1 = latlon_to_radar_px(nw_lat, nw_lon, r_w, r_h)
        rx2, ry2 = latlon_to_radar_px(se_lat, se_lon, r_w, r_h)

        # Clamp
        rx1 = max(0, rx1); ry1 = max(0, ry1)
        rx2 = min(r_w, rx2); ry2 = min(r_h, ry2)
        log.info(f"Radar crop: ({rx1},{ry1}) → ({rx2},{ry2}) from {r_w}x{r_h}")

        # Stega upp radarcroppen via en mellanstorlek med BILINEAR för mjukare interpolation,
        # sedan Gaussian blur för att eliminera kantiga radarblock
        raw_crop = radar_full.crop((rx1, ry1, rx2, ry2))
        mid_w, mid_h = raw_crop.width * 16, raw_crop.height * 16
        radar_crop = raw_crop.resize((mid_w, mid_h), Image.BILINEAR)
        radar_crop = radar_crop.filter(ImageFilter.GaussianBlur(radius=mid_w // 8))
        radar_crop = radar_crop.resize((img_w, img_h), Image.LANCZOS)

        # Skapa mask: 255 = regn (färgade pixlar), 0 = bakgrund (vitt/grått)
        arr = np.array(radar_crop.convert("RGB"))
        chroma = arr.max(axis=2).astype(int) - arr.min(axis=2).astype(int)
        brightness = arr.mean(axis=2)
        is_rain = (chroma > 30) & (brightness < 235)
        mask = Image.fromarray((is_rain * 200).astype(np.uint8))

        canvas.paste(radar_crop.convert("RGB"), (0, 0), mask)
        has_rain = bool(is_rain.sum() / is_rain.size > RAIN_PIXEL_THRESHOLD)
        log.info(f"Radar overlay applied, rain pixels: {is_rain.sum()}, has_rain: {has_rain}")
    except Exception as e:
        log.warning(f"Radar overlay failed: {e}")

    # Skala ner till 1000px bred
    target_w = 1000
    target_h = int(img_h * target_w / img_w)
    canvas = canvas.resize((target_w, target_h), Image.LANCZOS)
    return canvas, has_rain


def add_timestamp(img, dt):
    draw = ImageDraw.Draw(img)
    text = dt.strftime("%Y-%m-%d  %H:%M")
    font = None
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    ]:
        try:
            font = ImageFont.truetype(path, 20)
            break
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()
    x, y = 12, img.height - 34
    draw.text((x + 1, y + 1), text, fill=(0, 0, 0, 220), font=font)
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    return img


def cleanup_old_frames():
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    removed = 0
    for f in FRAMES_DIR.glob("*.png"):
        try:
            stem = f.stem.rsplit("_", 1)[0] if f.stem.endswith(("_rain", "_dry")) else f.stem
            ts = datetime.strptime(stem, "%Y-%m-%d_%H%M")
            if ts < cutoff:
                f.unlink()
                removed += 1
        except ValueError:
            pass
    if removed:
        log.info(f"Removed {removed} frames older than {RETENTION_DAYS} days")


def main():
    FRAMES_DIR.mkdir(exist_ok=True)

    now = datetime.now()
    base = now.strftime("%Y-%m-%d_%H%M")

    if any(FRAMES_DIR.glob(f"{base}_*.png")):
        log.info(f"Frame {base} already exists, skipping")
        return

    log.info(f"Building composite for {now.strftime('%Y-%m-%d %H:%M')}")
    img, has_rain = build_composite(now)

    suffix = "rain" if has_rain else "dry"
    log.info(f"Rain detected: {has_rain} → _{suffix}")

    img = add_timestamp(img, now)
    out_path = FRAMES_DIR / f"{base}_{suffix}.png"
    img.save(out_path, "PNG", optimize=True)
    log.info(f"Saved {out_path} ({img.size[0]}x{img.size[1]})")

    cleanup_old_frames()


if __name__ == "__main__":
    main()
