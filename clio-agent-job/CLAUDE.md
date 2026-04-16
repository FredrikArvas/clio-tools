# clio-agent-job

RSS-driven förändringssignalspaning för jobbsökande. Kör dagligen via cron på EliteDesk GPU.

## Beroenden till andra moduler

### → clio-agent-mail (hårt beroende)

`notifier.py` delar SMTP-infrastruktur med clio-agent-mail:

- Importerar `smtp_client.send_email()` från `../clio-agent-mail/`
- Anropar `load_config()` från `clio-agent-mail/main.py` för att hämta SMTP-config
- Lösenordet (`IMAP_PASSWORD_CLIO`) läses från `clio-agent-mail/.env` — lagras **inte** i clio-agent-job

**Konsekvens:** clio-agent-mail måste vara installerat och ha en fungerande `clio.config` + `.env`
för att clio-agent-job ska kunna skicka mail.

## Körkommando (server)

```bash
~/git/clio-tools/.venv/bin/python ~/git/clio-tools/clio-agent-job/run.py \
  --profile ~/git/clio-tools/clio-agent-job/profiles/richard.yaml
```

## Cron (elitedeskgpu)

```
0 7 * * *  richard.yaml
5 7 * * *  ulrika.yaml
```

Logg: `~/logs/clio-agent-job.log`
