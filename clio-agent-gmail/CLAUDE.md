# clio-agent-gmail — CLAUDE.md

## Syfte
Hämtar bilagor från Gmail via IMAP och lagrar dem lokalt enligt konfigurerade jobb. Varje jobb kan filtrera efter avsändare och målmappar.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python main.py              # Kör alla jobb
python main.py --job bauhaus  # Kör specifikt jobb
python main.py --list       # Lista konfigurerade jobb
python main.py --add-job    # Lägg till nytt jobb interaktivt
```

## Nyckelkod
- `main.py` — CLI entry point, jobb-dispatcher
- `fetch.py` — IMAP-klient för hämtning av bilagor
- `clio.config` — Jobbkonfiguration

## Beroenden
Externa: imap-tools, python-dotenv
Interna: clio-core

## Relaterade moduler
clio-core, clio-agent-mail, clio-emailfetch

## Gotchas
Jobb konfigureras i clio.config [gmail]-sektion. Lösenord via .env: IMAP_PASSWORD_[KONTO].
