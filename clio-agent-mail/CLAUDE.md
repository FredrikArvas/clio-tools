# clio-agent-mail — CLAUDE.md
# Instruktioner för AI-assistenter. Läs detta innan du arbetar i modulen.

## Vad modulen gör

Autonomt e-postagentsystem som körs som en daemon på EliteDeskGPU.
Pollar IMAP, klassificerar inkommande mail, genererar svarsförslag med Claude API,
och hanterar ett moderationsflöde via mail innan svar skickas till avsändaren.

---

## Konton och deras syfte

| Konto                         | Syfte                                        | Skicka från? |
|-------------------------------|----------------------------------------------|--------------|
| `clio@arvas.international`    | Clios primära brevlåda                       | Ja           |
| `info@arvas.international`    | Arvas officiella kontaktadress (inkorg)      | **Nej**      |
| `ssf@arvas.international`     | SSF/Capgemini-relaterad kommunikation        | Ja           |
| `gsf@arvas.international`     | GSF (Guldboda Scoutkår/föreningskommunik.)   | Ja           |
| `gtk@arvas.international`     | GTK-projekt                                  | Ja           |
| `gtff@arvas.international`    | GTFF-projekt                                 | Ja           |
| `krut@arvas.international`    | Krut-projekt                                 | Ja           |
| `vimla@arvas.international`   | Vimla-projekt                                | Ja           |
| `fredrik@arvas.international` | Fredriks personliga konto                    | Ja           |
| `ulrika@arvas.international`  | Ulrikas konto                                | Ja           |

**info@ är Arvas officiella inkommande adress — agenten läser den men skickar aldrig därifrån.**
Svar på mail som kommit in till info@ skickas alltid från ett lämpligt funktionskonto (t.ex. clio@).

---

## Moderationsflöde (gäller alla konton)

Agenten skickar **aldrig svar direkt** till en extern avsändare utan Fredriks godkännande.

```
Inkorg → klassificering → svarsförslag genereras →
  förslag mailas till fredrik@arvas.se →
    Fredrik svarar: JA (skicka) / NEJ (kassera) / redigerad text (skicka den) →
      agent skickar till ursprunglig avsändare
```

- Moderationsadressen: `notify_address = fredrik@arvas.se` (i clio.config)
- Godkännandeord: `JA` (skicka), `NEJ` (kassera)
- Fredrik kan redigera förslaget direkt i svarsmailtexten — agenten skickar den redigerade versionen
- Flödet är **server-side och laptopoberoende** — allt sker på EliteDeskGPU

---

## Klassificeringsflöde

1. IMAP-poll hämtar nya meddelanden per konto
2. `intent_classifier.py` klassificerar: FAQ / svar-behövs / kommando / övrigt
3. FAQ-match → svar genereras från Notion-FAQ utan moderering (konfigurerat per konto)
4. Allt annat → svarsförslag → moderationsflöde ovan

---

## Viktiga mönster och gotchas

- **Avsändarkonto**: välj alltid `from_account_key` utifrån vilken inkorg mailet kom in till,
  aldrig info@ som avsändare (se tabellen ovan)
- **clio.config + .env**: hemligheter (lösenord, API-nycklar) ALDRIG i kod — läses från `.env`
  via `IMAP_PASSWORD_[KONTO]`-variablerna
- **account_scopes.json**: styr vilka kodord (NCC-projekt) varje brevlåda får hantera.
  Tom lista = alla kodord tillåtna
- **state.db**: SQLite-databas för mail-state (läst, besvarad, pending godkännande).
  Rör inte direkt — använd `state.py`-API
- **Modellkonstanter**: använd `MODEL_SONNET` / `MODEL_HAIKU` från config, aldrig hårdkodade strängar
- **Bilagor**: hanteras via `attachments.py`, sparas i `attachments/`-katalogen

---

## Körkommandon

```bash
python main.py              # Kontinuerlig polling (daemon-läge)
python main.py --once       # Kör ett varv och avsluta
python main.py --dry-run    # Utan sändning eller DB-skrivning
python main.py --debug      # DEBUG-loggning inkl. HTTP-trafik
```

Systemd-tjänst: `systemctl status clio-mail.service`

---

## Sökvägar

- **Repo (server)**: `~/19.0/clio-tools/clio-agent-mail/`
- **Konfig**: `clio.config` + `../.env`
- **Databas**: `state.db`
- **Loggar**: `journalctl -u clio-mail.service -f`

NCC-kodord: `#mail`
