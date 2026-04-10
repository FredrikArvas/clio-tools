# clio-core

Delat bibliotek för clio-tools ekosystemet. Innehåller gemensamma utilities, banner och lokaliseringsdata som alla delprogram importerar.

## Installation

```powershell
# Lokal utveckling (rekommenderat)
pip install -e ./clio-core

# Via GitHub
pip install "clio-core @ git+https://github.com/KONTO/clio-tools.git#subdirectory=clio-core"
```

## Innehåll

| Modul | Syfte |
|---|---|
| `clio_core.utils` | Delade hjälpfunktioner (sökvägar, strängar, m.m.) |
| `clio_core.banner` | Utskrift av CLI-banner |
| `clio_core.locales/` | Lokaliseringssträngar (sv.json, en.json) |

## Beroenden

Enbart Python stdlib — inga externa paket.

## Verifiera

```powershell
python check_deps.py
```
