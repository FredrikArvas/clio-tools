# clio-agent-mail — CLAUDE.md

## Syfte
SMTP-klient för utgående mail från Clio. Stöder flera avsändarkonton (clio, ssf, gsf, gtk, gtff, fredrik, ulrika m.fl.) och bilagor.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python main.py             # Kontinuerlig polling
python main.py --once      # Kör ett varv och avsluta
python main.py --dry-run   # Kör utan att skicka svar
```

## Nyckelkod
- `smtp_client.py` — SMTP-sändare, IPv4-patch för mail.arvas.international
- `main.py` — Entry point, poller och klassificerare
- `clio.config` — Kontokonfiguration
- `MANUAL.md` — Fullständig användarhandbok

## Beroenden
Externa: imapclient, anthropic
Interna: clio-core

## Relaterade moduler
clio-core, clio-agent-gmail, clio-emailfetch

## Gotchas
IPv4-patch i smtp_client.py är kritisk — Python väljer annars IPv6 för mail.arvas.international vilket blockas. Lösenord via .env: IMAP_PASSWORD_[KONTO]. Se CLAUDE.md i root för lista på konton.
