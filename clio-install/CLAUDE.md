# clio-install — CLAUDE.md

## Syfte
Installationsscript och maskinöverflyttningsverktyg för clio-tools. Installerar systemprogram, pip-beroenden, clio-core och miljövariabler. Stöder krypterad .env-överföring mellan maskiner.

## Status
Aktiv

## Snabbstart
```powershell
python install.py                      # Interaktiv installation
python install.py --venv --yes --check # Automatisk med verifikation
python install.py --dry-run             # Se vad som skulle göras
python uninstall.py                    # Avinstallera (läser install_log.json)

# Maskinöverflyttning
python env_transfer.py --export        # Exportera krypterat från gammal maskin
python env_transfer.py --import clio-env-transfer.zip  # Importera på ny maskin
```

## Nyckelkod
- `install.py` — Idempotent installation
- `uninstall.py` — Avinstallation styrd av install_log.json
- `env_transfer.py` — Krypterad .env/clio.config-överföring

## Beroenden
Externa: winreg (Windows)
Interna: clio-core (installeras härifrån)

## Relaterade moduler
Installerar clio-core som ett steg

## Gotchas
Idempotent — säker att köra flera gånger. PATH-ändringar via Registry kräver ny terminal. install_log.json (gitignorerad) styr avinstallationen.
