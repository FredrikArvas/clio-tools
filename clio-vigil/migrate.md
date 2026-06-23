# clio-vigil — Migrationsguide

Checklista för att flytta clio-vigil till en ny Odoo-databas.

## Förutsättningar

- Måldatabasen måste ha `clio_vigil` och `clio_uap` installerade
- `VIGIL_ODOO_URL` och `VIGIL_ODOO_DB` i `.env` pekar på måldatabasen
- SSH-åtkomst till EliteDeskGPU (clioadmin@100.107.127.104)

## Data att flytta

### 1. Källor — `clio.vigil.source`
Nyckel: `url`

```python
fields = ['name','domain','source_type','url','maturity','weight','active','notes']
```

### 2. Vigil-items — `clio.vigil.item`
Nyckel: `url`

```python
fields = [
    'url','title','domain','source_type','source_name','source_maturity',
    'published_at','duration_seconds','relevance_score','priority_score',
    'state','summary','created_at','notified_at',
    'archive_downloaded','archive_path',
]
```

### 3. Prenumeranter — `clio.vigil.subscriber`
Nyckel: `partner_id` (matchas via `res.partner.email` eller `res.partner.name`)

```python
fields = ['partner_id','email','active','follows_ufo','follows_ai']
```

OBS: `res.partner`-poster skapas i måldatabasen om de saknas.

### 4. Leveranser — `clio.vigil.delivery`
Nyckel: kombination av `subscriber_id` + `item_id`

```python
fields = ['subscriber_id','item_id','delivered_at','digest_date']
```

Kräver att items (steg 2) och prenumeranter (steg 3) är kopierade först,
eftersom IDs skiljer sig mellan databaser — matchning sker via URL respektive partnernamn.

### 5. SQLite — `odoo_synced_state`
Nollställ efter migrering så att pipelinen synkar om allt mot måldatabasen:

```bash
sqlite3 ~/18.0/clio-tools/clio-vigil/data/vigil.db \
    'UPDATE vigil_items SET odoo_synced_state = NULL;'
```

## Migrationsordning

```
1. clio.vigil.source
2. clio.vigil.item
3. res.partner (skapas automatiskt vid behov)
4. clio.vigil.subscriber
5. clio.vigil.delivery
6. Nollställ odoo_synced_state i SQLite
7. Uppdatera VIGIL_ODOO_URL + VIGIL_ODOO_DB i .env
```

## Vad som INTE migreras

- `uap.encounter` — hanteras av `clio_uap`-modulen separat
- Ljudfiler i `/home/clioadmin/clio-archive/` — ligger på servern, inte i Odoo
- Transkriptfiler — likaså lokala
- Qdrant-index — byggs om via `--index` i pipelinen

## Exempel: kopiera från aiab till ny databas

```python
import sys; sys.path.insert(0, '..')
from clio_odoo import connect

src = connect(url='http://aiab.arvas.international', db='aiab')
dst = connect(url='http://ny-db.arvas.international', db='ny-db')

# Följ migrationsordningen ovan
```

Se sessionshistorik 2026-06-20 för fungerande kopieringsskript.
