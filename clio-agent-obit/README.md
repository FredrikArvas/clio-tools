# clio-agent-obit

Automatisk bevakning av svenska dödsannonser mot en personlig bevakningslista. Körs 1×/dag. Notifierar via e-post vid träff.

## Körning

```powershell
python run.py              # Normal körning
python run.py --dry-run    # Simulera utan att skicka e-post
python run.py --once       # Kör ett varv
```

## Beroenden

```powershell
pip install -r requirements.txt
python check_deps.py
```

## Konfiguration

- `sources.yaml` — lista med aktiva källadaptrar (familjesidan, fonus m.fl.)
- `config.yaml` — SMTP-inställningar och notifieringsadress
- `.env` — lösenord och hemligheter (kopiera `.env.example`)
- `watchlists/*.csv` — bevakningslista per bevakare

## Matchningslogik

Konfidenspoäng baserat på efternamn (+40), förnamn (+30), födelseår (+20), hemort (+10). Tröskelvärde för notis: ≥ 60p.
