# clio_geo — Odoo-addon spec

## Syfte
Stödtabell för GPS-baserad platsuppslagning. Primär användning: clio_vision bildanalys.
Sekundär: postnummer-/ortregister för kontakter, fakturor, event.

## Bakgrund
clio_vision v2.2.0 reverse-geocodar med `reverse_geocoder` (stad-nivå, GeoNames).
Precisionen är otillräcklig — 58.9681°N 18.0636°E ger "Nynashamn" istället för "Muskö".
Lösning: en tabell med kända platser + toleransradie. Fallback till reverse_geocoder om inget träff.

## Odoo-miljö
- Server: clioadmin@100.107.127.104, port 8079
- Databas: aiab
- Repo: ~/clio-odoo-addons/
- Installerade geo-moduler: INGA (res.city finns ej, base_geolocalize ej installerad)
- res.country.state finns med svenska län (SE-AB etc.)

## Modell: clio.location

```python
class ClioLocation(models.Model):
    _name = "clio.location"
    _description = "Known GPS Location"
    _order = "name"

    name         = fields.Char(required=True)           # "Muskö/Hemma"
    display_name_geo = fields.Char(required=True)       # "Muskö, Sweden"  (ej att förväxla med _rec_name)
    lat          = fields.Float(digits=(10, 7))
    lon          = fields.Float(digits=(10, 7))
    radius_m     = fields.Integer(default=200)          # toleransradie i meter
    category     = fields.Selection([
                       ("home", "Home"),
                       ("work", "Work"),
                       ("vacation", "Vacation"),
                       ("other", "Other"),
                   ], default="other")
    zip          = fields.Char()
    city         = fields.Char()
    country_id   = fields.Many2one("res.country")
    state_id     = fields.Many2one("res.country.state")
    notes        = fields.Text()
    active       = fields.Boolean(default=True)
```

## Söklogik (Python/haversine)
Exponera via JSON-RPC-metod `clio.location/find_nearest`:
```
Input:  lat, lon
Output: display_name_geo | None
```

Algoritm:
1. Hämta alla aktiva platser (cachas lokalt i anropande skript)
2. Beräkna haversine-avstånd till varje post
3. Returnera `display_name_geo` för närmaste post inom sin `radius_m`
4. Ingen träff → returnera None (fallback till reverse_geocoder i clio_vision)

## Integration i clio_vision.py
Funktion `get_gps_location(image_file)` uppdateras:
1. Försök `query_odoo_known_location(lat, lon)` → om träff, returnera
2. Fallback: `reverse_geocoder.search([(lat, lon)])` → stad-nivå

Odoo-anropet görs en gång per session (alla platser hämtas och cachas som lista i minnet).

## Startdata att lägga in
- Muskö/Hemma: 58.9681°N 18.0636°E, radius 300m
- (fler läggs till manuellt i Odoo-UI)

## Modulnamn
`clio_geo` — eget repo eller i `clio-odoo-addons/`

## Beroenden
- `base` (inget mer)
- Ingen OCA-modul behövs bygga på

## Filer att skapa
```
clio_geo/
  __manifest__.py
  __init__.py
  models/
    __init__.py
    clio_location.py
  views/
    clio_location_views.xml
    menu.xml
  security/
    ir.model.access.csv
  data/
    clio_location_data.xml   # Muskö som startpost
```

## Nästa steg i ny session
1. Bygg modulen enligt spec ovan
2. Installera i aiab-databasen
3. Uppdatera `get_gps_location()` i clio_vision.py (v2.3.0)
4. Testa med testbilden (58.9681°N 18.0636°E → "Muskö, Sweden")
