# clio-fetch

Webb-hämtare: laddar ned URL:er, sparar HTML/text och kan skicka innehållet till Claude för analys och sammanfattning.

## Körning

```powershell
python clio_fetch.py <url>
python clio_fetch.py <url> --analyse    # Skicka till Claude
python clio_fetch.py <url> --clean      # Flytta gamla filer till papperskorgen
```

## Beroenden

```powershell
pip install -r requirements.txt
python check_deps.py
```

## Konfiguration

Kräver `ANTHROPIC_API_KEY` i `.env` för Claude-analys.
