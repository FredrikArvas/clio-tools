# Plan: Användaradmin + mail (clio-music)

Beslutad: 2026-10-12. Sprint: egen (efter v1.7.4).

## Bakgrund

Admin ska kunna skapa, redigera, aktivera/inaktivera och sätta lösenord direkt i
webbgränssnittet — utan SSH. Utökas med inbjudningsmail och lösenordsåterställning
via mail (examensbyran.se-konto, läggs till i clio-agent-mail när SMTP-uppgifter finns).

## Låsta beslut

| # | Fråga | Svar |
|---|---|---|
| 1 | Mailmekanism | **A: mailkö** — PHP skriver JSON-filer till `data/mail_queue/`, systemd-timer skickar via clio-agent-mail |
| 2 | Mailavsändare | examensbyran.se — SMTP-uppgifter saknas, konfigureras senare |
| 3 | Användarnamnsformat | `[a-zA-Z0-9_]{3,30}`, sparas/jämförs alltid som gemener |
| 4 | Lösenordsminimumlängd | 12 tecken (`MIN_PASSWORD_LENGTH`) |

## users.csv — utökat format

```
username;hash;display;active;admin;groups;must_change;email
```

| Kolumn | Index | Nytt? | Notering |
|---|---|---|---|
| username | 0 | — | |
| hash | 1 | — | bcrypt |
| display | 2 | — | |
| active | 3 | — | 0/1 |
| admin | 4 | — | 0/1 |
| groups | 5 | — | pipe-separerat |
| must_change | 6 | **JA** | 0/1; saknad kolumn = 0 |
| email | 7 | **JA** | valfri; saknad kolumn = '' |

Befintlig kod (groups_store.php, auth.php) läser/skriver bara kol 0–5 och hanterar
kortare rader med `?? ''` — bakåtkompatibelt utan migrering.

## Filer att skapa

| Fil | Beskrivning |
|---|---|
| `admin/file_utils.php` | Flytta `with_file_lock()` + `write_file_atomically()` hit (delas av groups_store och users_store) |
| `admin/users_store.php` | Datalager: läsning, validering, skrivning av users.csv |
| `admin/users.php` | Vy + formulärhantering (bara admin) |
| `mail_queue.php` | `queue_mail(to, subject, body, from_account)` → skriver `data/mail_queue/{uuid}.json` |
| `reset.php` | Begär/genomför lösenordsåterställning via token |
| `change_password.php` | Tvingad lösenordsbyte vid first-login (must_change=1) |
| `admin/send_queued_mail.py` | Python-skript som tömmer mailkön via clio-agent-mail |
| `deploy/clio_music_mail.service` | systemd service |
| `deploy/clio_music_mail.timer` | Kör var 60:e sekund |
| `tests/users_store_test.php` | CLI-test mot fixture-filer |

## Filer att ändra

| Fil | Vad |
|---|---|
| `config.php` | `MIN_PASSWORD_LENGTH`, `USERNAME_PATTERN`, `MAIL_FROM_ACCOUNT`, `RESET_TOKEN_TTL` + katalog-konstanter |
| `auth.php` | `save_user_hash()` tas bort (flyttas till users_store.php); `load_users()` + `verify_login()` läser kol 6–7; `must_change` läggs till i session-objektet |
| `admin/groups_store.php` | `with_file_lock()` + `write_file_atomically()` ersätts med `require_once 'file_utils.php'` |
| `login.php` | Efter lyckad inloggning: om `must_change` → redirect till `change_password.php` |
| `admin/index.php` | Länk till `users.php` i admin-headern |
| `help_admin.php` | Ersätt SSH-manualen för användarskapande med länk till `/admin/users.php` |

## admin/users_store.php — funktioner

```php
// Läsning
read_all_users_for_admin(path): array          // inkl. inaktiva, alla kolumner
// Validering
validate_username(name, existing): [lower, err]  // pattern + unicitet
validate_password(pw): [ok, err]                 // MIN_PASSWORD_LENGTH
validate_display_name(name): [trimmed, err]      // 1–60 tecken, csv-säkert
validate_email(email): [trimmed, err]            // tomt ok, annars basic format
// Skrivning
save_new_user(path, data): '' | error            // atomisk append av ny rad
save_user_fields(path, username, changes): '' | error  // display/active/admin/must_change/email
save_user_hash(path, username, hash): bool       // flyttas från auth.php
```

## admin/users.php — UI

Tre GET-lägen via `?action=` (default = lista):

- **lista** — tabell: username, visningsnamn, grupper (antal), aktiv, admin, knappar
- **?action=create** — formulär: username, visningsnamn, lösenord ×2, aktiv, admin, email, "Skicka inbjudningsmail" (förkryssad om email ifyllt), "Tvinga lösenordsbyte"
- **?action=edit&u=X** — redigera: visningsnamn, aktiv, admin, email, must_change
- **?action=password&u=X** — nytt lösenord ×2

POST-actions: `create`, `edit`, `set_password`, `toggle_active`.

Alla POST: `csrf_require()` som första rad.

Audit-events: `admin_user_created`, `admin_user_edited`, `admin_password_changed`,
`admin_user_rejected`.

## Inbjudningsflöde

```
Admin → skapar användare med email + "Skicka inbjudningsmail" ikryssad
  → PHP genererar engångslösenord (16 tecken, random_bytes → base64)
  → hashar och sparar, must_change=1
  → queue_mail(email, "Välkommen", "Inloggning: URL, användarnamn, lösenord")
  → systemd-timer skickar inom ~60 s
```

## Lösenordsåterställningsflöde (reset.php)

```
GET /reset.php           → formulär: ange användarnamn
POST → token genereras   → data/reset_tokens/{32-byte-hex}.json {username, expires: now+TTL}
                         → queue_mail(email, "Återställ lösenord", URL+token)

GET /reset.php?token=X   → validera token (finns, ej utgången) → formulär nytt lösenord ×2
POST med token           → hash sparas, must_change=0, token raderas → redirect login.php
```

Token-filer rensas vid varje besök (skannar reset_tokens/ och tar bort utgångna).

## Lösenordsbytesflöde (change_password.php)

Visas när `current_user()['must_change'] === 1`.
`require_login()` kallar ny `require_password_change_redirect()` på alla sidor utom
`change_password.php` och `logout.php`.

Formulär: nytt lösenord ×2 (gammalt lösenord behövs ej — användaren precis autentiserat).
POST: `save_user_hash()` + `save_user_fields(must_change=0)` → redirect index.php.

## Öppna punkter

- SMTP-uppgifter för examensbyran.se saknas — MAIL_FROM_ACCOUNT är tom sträng tills vidare;
  `queue_mail()` loggar en varning och gör inget när kontot saknas.
- Grupptilldelning för nya användare görs fortfarande i groups.php (oförändrat).
- Ingen SMTP-notifiering till admin när lösenordsåterställning begärs.
