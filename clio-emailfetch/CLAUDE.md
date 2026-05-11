# clio-emailfetch — CLAUDE.md

## Syfte
IMAP-backup: laddar ned alla e-postmeddelanden och sparar som .eml-filer. Stöder inkrementell backup (hoppar över redan nedladdade meddelanden).

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python setup_credentials.py        # Konfigurera IMAP-lösenord (engång)
python imap_backup.py              # Fullständig backup
python imap_backup.py --dry-run    # Simulera utan att spara
```

## Nyckelkod
- `imap_backup.py` — IMAP-klient, inkrementell backup
- `setup_credentials.py` — Lösenordskonfiguration

## Beroenden
Externa: imapclient, keyring
Interna: clio-core

## Relaterade moduler
clio-core, clio-agent-mail, clio-agent-gmail

## Gotchas
Lösenord lagras i OS Credential Manager via keyring. Standard IMAP: imap.one.com:993 (SSL). Mappstruktur: `<backup_dir>/<konto>/<imap-mapp>/YYYY-MM-DD_Ämne.eml`.
