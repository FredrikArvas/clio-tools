# clio-agent-mail — Manual

**Version:** Sprint 2 (2026-04-09)
**Målgrupp:** Admins och tekniker

---

## Innehåll

1. [Vad är clio-agent-mail?](#1-vad-är-clio-agent-mail)
2. [Snabbstart](#2-snabbstart)
3. [Konfiguration](#3-konfiguration)
4. [Mailflöden](#4-mailflöden)
5. [Kommandosystem](#5-kommandosystem)
6. [Admin-guide](#6-admin-guide)
7. [TUI — maillogg](#7-tui--maillogg)
8. [Felsökning](#8-felsökning)
9. [Arkitektur](#9-arkitektur)

---

## 1. Vad är clio-agent-mail?

clio-agent-mail är en AI-driven mailhanterare som hanterar inkorgarna på:

| Konto | Adress | Syfte |
|-------|--------|-------|
| `clio` | clio@arvas.international | Fredriks assistent, full access |
| `krut` | krut@arvas.international | Ulrikas assistent |
| `gtff` | gtff@arvas.international | Föreningsminne GTFF |
| `gtk` | gtk@arvas.international | Föreningsminne GTK |
| `gsf` | gsf@arvas.international | Föreningsminne GSF |
| `vimla` | vimla@arvas.international | Parrelationscoach |

`info@arvas.international` är ett alias och pollas ej separat.

Systemet hämtar olästa mail via IMAP, klassificerar dem, genererar svar med
Claude API och skickar autonomt eller ber en admin om godkännande.

---

## 2. Snabbstart

```powershell
cd "C:\Users\Fredrik Arvas\Documents\git\clio-tools\clio-agent-mail"

# Starta i bakgrunden (normalläge)
python main.py

# Kör ett enda pass (testning)
python main.py --once

# Simulera utan att skicka mail eller skriva till DB
python main.py --dry-run

# Aktivera detaljerad loggning (HTTP-trafik m.m.)
python main.py --debug
```

### Snabbkommando (clio från valfri katalog)

Lägg till i PowerShell-profilen (`notepad $PROFILE`):

```powershell
function clio { python "C:\Users\Fredrik Arvas\Documents\git\clio-tools\clio.py" @args }
```

Därefter kan du skriva `clio` från valfri katalog i PowerShell.

Agenten startar polling-loopen och loggar till stdout.

---

## 3. Konfiguration

### clio.config

| Nyckel | Beskrivning | Exempel |
|--------|-------------|---------|
| `imap_host` | IMAP-server | `mail.arvas.international` |
| `imap_port` | IMAP SSL-port | `993` |
| `accounts` | Kommaseparerade konton att polla | `clio,krut,gtff,gtk,gsf,vimla` |
| `imap_user_clio` | Användare clio-konto | `clio@arvas.international` |
| `imap_user_info` | Användare info-konto (alias, pollas ej) | `info@arvas.international` |
| `imap_user_krut` | Användare krut-konto | `krut@arvas.international` |
| `imap_user_gtff` | Användare gtff-konto | `gtff@arvas.international` |
| `imap_user_gtk` | Användare gtk-konto | `gtk@arvas.international` |
| `imap_user_gsf` | Användare gsf-konto | `gsf@arvas.international` |
| `imap_user_vimla` | Användare vimla-konto | `vimla@arvas.international` |
| `permissions_notion_page_id` | Notion-sida med behörighetsmatris | `33x67...` |
| `smtp_host` | SMTP-server | `mail.arvas.international` |
| `smtp_port` | SMTP SSL-port | `465` |
| `notify_address` | Fredrik's arvas-adress | `fredrik@arvas.se` |
| `notify_address_capgemini` | Fredrik's cap-adress | `fredrik.arvas@capgemini.com` |
| `admin_addresses` | Kommaseparerade admin-adresser | `fredrik@arvas.se, ulrika@arvas.se` |
| `default_language` | Systemspråk för .com/.net/.org | `sv` |
| `imap_timeout_seconds` | Timeout för IMAP-anslutning | `30` |
| `poll_interval_seconds` | Pollintervall dagtid | `300` |
| `poll_interval_night_seconds` | Pollintervall nattetid | `900` |
| `poll_night_start_hour` | Nattens start (timme) | `22` |
| `poll_night_end_hour` | Nattens slut (timme) | `6` |
| `whitelist_notion_page_id` | Notion-sida med vitlistan | `33a67...` |
| `faq_notion_page_id` | Notion-sida med FAQ | `33a67...` |
| `knowledge_notion_db_ids` | Notion-databaser för kunskapsbas | `db_id:Projektmasterlista` |
| `whitelist_keyword` | Nyckelord för vitlistning | `VITLISTA` |
| `blacklist_keyword` | Nyckelord för svartlistning | `SVARTLISTA` |
| `keep_keyword` | Nyckelord för behåll | `BEHÅLL` |
| `approval_keyword_yes` | Godkänn utkast | `JA` |
| `approval_keyword_no` | Avvisa utkast | `NEJ` |

### .env

```
ANTHROPIC_API_KEY=sk-ant-...
NOTION_API_KEY=secret_...
IMAP_PASSWORD_CLIO=...
IMAP_PASSWORD_INFO=...
IMAP_PASSWORD_KRUT=...
IMAP_PASSWORD_GTFF=...
IMAP_PASSWORD_GTK=...
IMAP_PASSWORD_GSF=...
IMAP_PASSWORD_VIMLA=...
```

Lösenord och API-nycklar ska **aldrig** finnas i `clio.config`.

---

## 4. Mailflöden

### Klassificering

```
Inkommande mail
    │
    ├─ Intern tag ([CLIO-FLAGGAD], [CLIO-KOPIA], [CLIO-INFO]) → Ignoreras
    │
    ├─ Ämne = "help" (alla avsändare) → HELP-svar direkt
    │
    ├─ Avsändare = admin → SELF_QUERY
    │   ├─ Ämne = känt kommando → Kommandosystem
    │   └─ Övrigt → AI-svar med kunskapsbas
    │
    ├─ Konto = info@ → FAQ_CHECK
    │   ├─ Hög konfidens → Automatiskt FAQ-svar
    │   └─ Låg konfidens → Holding-svar + notis till admin
    │
    └─ Konto = clio@
        ├─ Vitlistad avsändare
        │   ├─ [CLIO-DRAFT] i ämne → SEND_FOR_APPROVAL
        │   └─ Övrigt → AUTO_SEND
        │
        └─ Ej vitlistad → STANDARD_REPLY
            ├─ Holding-svar till avsändaren
            ├─ Flaggnotis till admin
            └─ STATUS_WAITING i DB
```

### WAITING-flöde

1. Okänd avsändare → holding-svar + `[CLIO-FLAGGAD]`-notis till admin
2. Admin svarar med `VITLISTA` → Notion + automatiskt AI-svar på väntande mail
3. Admin svarar med `SVARTLISTA` → Blockeras permanent
4. Admin svarar med `BEHÅLL` → Standardsvar skickas, markeras FLAGGED

Alternativt: använd TUI-mailloggen för att hantera WAITING-mail direkt.

### Godkännandeflöde (SEND_FOR_APPROVAL)

1. Clio skickar utkast + `[CLIO-DRAFT]`-mail till admin
2. Admin svarar `JA` → Mailet skickas till den ursprungliga avsändaren
3. Admin svarar `NEJ` → Utkastet avvisas, markeras REJECTED
4. Admin kan redigera utkastet i svaret — Clio använder den redigerade texten

### CC-logik

Clio CC:ar admin på utgående svar i tre fall (prioritetsordning):
1. Admin fanns redan i original CC/To → samma adress används
2. Avsändaren är från `@capgemini.com` → Capgemini-adressen
3. `[CLIO-CC]` i ämnesraden → arvas-adressen

---

## 5. Kommandosystem

Admin mailar till `clio@arvas.international`:
- **Ämnesrad** = kommando (case-insensitivt, `/`-prefix valfritt)
- **Brödtext** = argument

### Kommandon

| Kommando | Synonymer | Argument | Beskrivning |
|----------|-----------|----------|-------------|
| `list` | `lista`, `liste`, `projekt` | — | Alla projekt + #kodord |
| `waiting` | `väntande`, `väntar` | — | WAITING-mail i DB |
| `status` | — | — | Systemöversikt |
| `whitelist` | `vitlista` | — | Visa vitlistan |
| `whitelist` | `vitlista` | `email@...` i brödtext | Lägg till adress |
| `blacklist` | `svartlista` | `email@...` i brödtext | Svartlista adress |
| `help` | `hjälp`, `aide`, `hilfe` | — | Kortfattad hjälp (alla användare) |
| `adminhelp` | `systemhelp` | — | Admin-kommandon |
| `manual` | `manuell` | — | Fullständig manual (detta dokument) |
| `onboarding` | `welcome`, `välkommen` | `email@...` + ev. namn | Välkomstmail till ny kontakt |
| `prompt` | `instruera`, `instruct` | `email@...` + text med `#kodord` | Skicka instruktion till tredje part |
| `language` | `språk`, `langue` | Språkkod (`sv`, `en`, `fr`, `de`) | Byt din språkpreferens |

### #kodord i prompt

`prompt`-kommandot identifierar projektkontext via `#kodord`:

```
Till: clio@arvas.international
Ämne: prompt

carl@example.com
Skriv en statusrapport om #ssf och redovisa perspektiven från #iaf.
```

- Första `#kodord` = primärt NCC (huvudkontext)
- Ytterligare `#kodord` = sekundär kontext
- Inget `#kodord` → Clio svarar med resonemang och ber om förtydligande

Se `list`-kommandot för alla tillgängliga kodord.

### Språkdetektering

- Nationella TLD:er (`.se` → sv, `.fr` → fr, `.de` → de, m.fl.) → automatiskt
- Icke-nationella (`.com`, `.net`, `.org`) → `default_language` i `clio.config`
- Kontaktens preferens sparas i `partners`-tabellen och kan ändras med `language`

---

## 6. Admin-guide

### Lägga till admin

I `clio.config`:
```ini
admin_addresses = fredrik@arvas.se, ulrika@arvas.se
```

Starta om agenten.

### Vitlistning

Vitlistan läses från en Notion-sida (en adress per rad, `#` = kommentar).
Uppdateras automatiskt när admin svarar `VITLISTA` på en flaggnotis,
eller via `whitelist`-kommandot.

### Svartlistning

Svartlistan lagras lokalt i `state.db`. Svartlistade avsändare ignoreras
helt — inget svar skickas.

### Manuell DB-inspektion

```powershell
cd "C:\Users\Fredrik Arvas\Documents\git\clio-tools\clio-agent-mail"

# Öppna SQLite
sqlite3 state.db

-- WAITING-mail
SELECT sender, subject, date_received FROM mail WHERE status='WAITING';

-- Partners
SELECT email, name, language, role, onboarded_at FROM partners;

-- Svartlista
SELECT email, added_at FROM blacklist;
```

---

## 7. TUI — maillogg

Nås via `clio.py` → meny 5.

**Filter (standard: WAITING):**
- 1 — WAITING (väntande vitlistningsbeslut)
- 2 — Alla
- 3 — SENT
- 4 — FLAGGED

**Åtgärder på WAITING-mail:**
- `V` — Vitlista avsändaren (Notion + auto-svar på väntande mail)
- `S` — Svartlista avsändaren (SQLite + markera FLAGGED)
- `B` — Behåll olistad (skicka standardsvar, markera FLAGGED)

---

## 8. Felsökning

### Agenten hänger utan aktivitet

IMAP-anslutningen kan tappas tyst. Timeout är 30 sekunder (konfigurerbart
med `imap_timeout_seconds`). Kontrollera att timeout inte är för lång.

### Mail processas inte

1. Kolla att `message_id` inte redan finns i `state.db` (`is_seen`)
2. Kontrollera att ämnesraden inte innehåller intern tag
3. Kör `python main.py --debug` för fullständig HTTP-loggning

### Vitlistan hämtas inte

1. Kontrollera att Notion-integrationen har läsrättigheter på vitlistesidan
2. Testa: `python -c "import notion_data; print(notion_data.get_whitelist('PAGE_ID'))"`

### Fel lösenord / autentisering

Lösenord läses från `.env`-filen (aldrig från `clio.config`).
Kontrollera att `IMAP_PASSWORD_CLIO` är satt korrekt.

### Loggning

```powershell
# Normalläge (INFO — rekommenderat)
python main.py

# Debug (HTTP-trafik, API-anrop m.m.)
python main.py --debug
```

---

## 9. Arkitektur

```
main.py          Huvudloop, poll_once (N konton), run_cycle, entrypoint
handlers.py      Mail-routing, alla _handle_*, flagged/waiting-flöden
helpers.py       Rena hjälpfunktioner (extract_email, cc-logik m.m.)
classifier.py    Regelmotor: AUTO_SEND / APPROVAL / STANDARD / FAQ / SELF_QUERY
commands.py      Kommandosystem: 11 kommandon, synonymtabell, #kodord-resolving
imap_client.py   IMAP-hämtning, bilagshantering, mänskliga mappnamn
smtp_client.py   Utskick (SSL 465), HTML-format, APPEND till Skickat
reply.py         Claude-prompt med bilagor, few-shot, SELF_QUERY, holding-svar
approval.py      JA/NEJ-flöde, redigerbara utkast, learned_replies
faq.py           FAQ-matchning, holding-svar för info@
notion_data.py   Vitlista, FAQ, Context Cards, behörighetsmatris, #kodord-index
state.py         SQLite: mail, approvals, flaggade, partners, svartlista
attachments.py   Textextraktion: PDF, Word, Excel, PPT, bild, CSV, TXT, MD
insights.py      Mailmönsteranalys → Notion
clio.py          TUI-gränssnitt (maillogg, start/stopp m.m.)
```

### Databas (state.db)

| Tabell | Innehåll |
|--------|----------|
| `mail` | Alla inkommande mail med status och action |
| `approvals` | Utkast som väntar på JA/NEJ |
| `learned_replies` | Fredrik-godkända svar (few-shot) |
| `flagged_notifications` | VITLISTA/SVARTLISTA/BEHÅLL-ärenden |
| `blacklist` | Permanentblockerade adresser |
| `partners` | Kontakter med språkpreferens (forward-compatible med clio-partnerdb) |

### Statusar

| Status | Beskrivning |
|--------|-------------|
| `NEW` | Nytt mail, ej hanterat ännu |
| `PENDING` | Väntar på admin-godkännande (JA/NEJ) |
| `WAITING` | Okänd avsändare, väntar på vitlistningsbeslut |
| `SENT` | Svar skickat |
| `FLAGGED` | Hanterat utan AI-svar (BEHÅLL, svartlistat m.m.) |
| `REJECTED` | Admin svarade NEJ på godkännandeförfrågan |
