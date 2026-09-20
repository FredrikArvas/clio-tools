"""
clio_geo_map.py
Fetches all clio.location records from Odoo and generates a Leaflet HTML
map with one pin per location. Opens the result in the default browser.

Usage:
    python clio_geo_map.py [output.html]
"""

import json
import os
import sys
import webbrowser
import xmlrpc.client
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR.parent / ".env")

ODOO_URL = os.environ["ODOO_URL"].rstrip("/")
ODOO_DB = "aiab"
ODOO_USER = os.environ["ODOO_USER"]
ODOO_PASSWORD = "AIABOdoo2026"


def fetch_locations():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        raise RuntimeError("Odoo-autentisering misslyckades")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "clio.location", "search_read",
        [[["active", "=", True], ["lat", "!=", 0]]],
        {"fields": ["id", "name", "display_name_geo", "lat", "lon",
                    "radius_m", "category", "city"]},
    )


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8"/>
<title>clio_geo — Platser</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; }}
  #header {{ padding: 12px 16px; background: #16213e; border-bottom: 1px solid #0f3460; }}
  #header h1 {{ font-size: 1rem; font-weight: 600; color: #e0e0e0; }}
  #header p {{ font-size: 0.8rem; color: #8899aa; margin-top: 2px; }}
  #map {{ height: calc(100vh - 52px); }}
  .popup-box {{ font-size: 13px; min-width: 180px; }}
  .popup-box strong {{ font-size: 14px; display: block; margin-bottom: 4px; }}
  .popup-box .coords {{ color: #666; font-size: 11px; }}
  .popup-box a {{ display: inline-block; margin-top: 6px; color: #0078d4;
                  text-decoration: none; font-size: 12px; }}
</style>
</head>
<body>
<div id="header">
  <h1>clio_geo — Kända platser</h1>
  <p>{count} platser · Klicka på en nål för detaljer · Dubbelklicka för att zooma</p>
</div>
<div id="map"></div>
<script>
const locations = {locations_json};
const map = L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© OpenStreetMap',
  maxZoom: 19,
}}).addTo(map);

const categoryColor = {{
  home: '#e74c3c',
  work: '#3498db',
  vacation: '#2ecc71',
  other: '#f39c12',
}};

const bounds = [];
locations.forEach(loc => {{
  if (!loc.lat || !loc.lon) return;
  const color = categoryColor[loc.category] || '#f39c12';
  const icon = L.divIcon({{
    className: '',
    html: `<div style="width:14px;height:14px;background:${{color}};border:2px solid white;
            border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>`,
    iconAnchor: [7, 7],
  }});
  const osmUrl = `https://www.openstreetmap.org/?mlat=${{loc.lat}}&mlon=${{loc.lon}}#map=16/${{loc.lat}}/${{loc.lon}}`;
  const popup = `<div class="popup-box">
    <strong>${{loc.display_name_geo}}</strong>
    ${{loc.name !== loc.display_name_geo ? '<em style="color:#888;font-size:12px">' + loc.name + '</em><br/>' : ''}}
    <span class="coords">${{loc.lat.toFixed(5)}}, ${{loc.lon.toFixed(5)}} &nbsp;·&nbsp; r=${{loc.radius_m}}m</span><br/>
    <a href="${{osmUrl}}" target="_blank">Öppna i OSM ↗</a>
  </div>`;
  L.marker([loc.lat, loc.lon], {{icon}}).bindPopup(popup).addTo(map);
  bounds.push([loc.lat, loc.lon]);
}});

if (bounds.length > 0) {{
  map.fitBounds(bounds, {{padding: [40, 40]}});
}} else {{
  map.setView([59.0, 18.0], 8);
}}
</script>
</body>
</html>"""


def generate(output_path):
    print("Hämtar platser från Odoo …")
    locs = fetch_locations()
    print(f"  {len(locs)} platser hämtade")

    html = HTML_TEMPLATE.format(
        count=len(locs),
        locations_json=json.dumps(locs, ensure_ascii=False),
    )
    output_path = Path(output_path)
    output_path.write_text(html, encoding="utf-8")
    print(f"Karta sparad: {output_path}")
    webbrowser.open(output_path.as_uri())


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else str(SCRIPT_DIR / "clio_geo_map.html")
    generate(out)
