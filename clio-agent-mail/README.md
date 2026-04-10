# clio-agent-mail

AI-drivet e-postagent för Arvas/AIAB. Pollar IMAP, klassificerar inkommande e-post, genererar förslag på svar med Claude och kan logga ärenden i Notion.

## Körning

```powershell
python main.py             # Kontinuerlig polling
python main.py --once      # Kör ett varv och avsluta
python main.py --dry-run   # Kör utan att skicka svar
python main.py --debug     # Utförlig loggning
```

## Beroenden

```powershell
pip install -r requirements.txt
python check_deps.py
```

## Konfiguration

Läser från `clio.config` [emailfetch]-sektionen och `.env` för API-nycklar.
Se `MANUAL.md` för fullständig användarhandbok.
