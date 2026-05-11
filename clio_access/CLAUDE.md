# clio_access — CLAUDE.md

## Syfte
Delat behörighetspaket för clio-tools. Stöder rollbaserad åtkomstkontroll med Notion-matris och whitelist.

## Status
Aktiv

## Snabbstart
```python
from clio_access import AccessManager

am = AccessManager(notion_token="...", matrix_page_id="...", admin_identities={...})
# eller
am = AccessManager.from_config(config)   # ConfigParser-variant

am.get_level({"email": "..."})           # → "admin|write|coded|whitelisted|denied"
am.is_allowed({"email": "..."})          # → bool
am.get_accounts({"email": "..."})        # → list[str]
```

## Nyckelkod
- `access.py` — AccessManager-klass
- `__init__.py` — Offentlig API-exponering

## Beroenden
Externa: notion-client
Interna: clio-core

## Relaterade moduler
clio-core, clio-partnerdb, clio-genealogy

## Gotchas
Inga kända.
