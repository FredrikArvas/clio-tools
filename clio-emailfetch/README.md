# clio-emailfetch

IMAP-backup: laddar ned alla e-postmeddelanden och sparar som `.eml`-filer. Stöder inkrementell backup (hoppar över redan nedladdade meddelanden).

## Körning

```powershell
python imap_backup.py               # Fullständig backup
python imap_backup.py --dry-run     # Simulera utan att spara
python setup_credentials.py        # Konfigurera IMAP-lösenord
```

**Mappstruktur:** `<backup_dir>/<konto>/<imap-mapp>/YYYY-MM-DD_Ämne.eml`

## Beroenden

```powershell
pip install -r requirements.txt
python check_deps.py
```

## Konfiguration

Läser från `clio.config` [emailfetch]-sektionen. Lösenord lagras i OS Credential Manager via `keyring`.

Standard IMAP-server: `imap.one.com:993` (SSL).
