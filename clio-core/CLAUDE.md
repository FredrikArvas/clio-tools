# clio-core — CLAUDE.md

## Syfte
Delat bibliotek för hela clio-tools-ekosystemet. Innehåller gemensamma utilities, CLI-banner och lokaliseringsdata. Importeras av alla andra moduler.

## Status
Aktiv

## Snabbstart
```powershell
pip install -e .            # Lokal editable-installation (rekommenderat)
python check_deps.py        # Kontrollera beroenden
```

## Nyckelkod
- `clio_core/utils.py` — Delade hjälpfunktioner (sökvägar, strängar m.m.)
- `clio_core/banner.py` — CLI-bannerutskrift
- `clio_core/locales/sv.json` — Svenska UI-strängar
- `clio_core/locales/en.json` — Engelska UI-strängar

## Beroenden
Externa: Inga (enbart Python stdlib)
Interna: Ingen

## Relaterade moduler
Importeras av alla clio-moduler

## Gotchas
Installera i editable mode (`pip install -e .`) så att ändringar reflekteras direkt i alla moduler. Lägg aldrig hemliga konfigurationer eller hårdkodade värden här.
