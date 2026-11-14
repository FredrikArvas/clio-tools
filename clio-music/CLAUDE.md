# CLAUDE.md — clio_music

Kontext för LLM-assistenter som arbetar med detta projekt. Säkerhetsmodellen i korthet finns i SECURITY.md. Detaljerad arkitektur, drift och öppna punkter finns i **ARCHITECTURE.md** — läs relevant avsnitt innan du ändrar i ett område (se kartan nedan).

## Vad projektet är

PHP-baserad musikspelare för meditationsljud (Miranon Media / Roger Gottardsson). Inloggningsskyddad, inga ramverk, inga npm-beroenden. Körs på EliteDesk GPU bakom Cloudflare på https://audio.examensbyran.se. Version: `APP_VERSION` i `config.php`.

## Regler och konventioner

- **Inga ramverk.** Vanilla JS + Web Audio API på klientsidan. PHP utan Composer.
- **Inga hårdkodade URL:er.** Använd `$music_url` från config.php.
- **APP_VERSION** i config.php ska bumpas vid varje deploy. Den används för cache-bust (`?v=APP_VERSION`) på style.css, consent.js och player.js.
- **data/-mappen är känslig.** users.csv, plays.jsonl, audit.jsonl, profiles/ och playlists/ är git-ignorerade och innehåller riktiga användardata.
- **Bcrypt** för lösenord, aldrig klartext. Hash genereras via SSH (se SECURITY.md). `admin/hash_tool.php` är borttaget (S4).
- **Inga XSS-risker.** Allt som skrivs ut via PHP ska passera `htmlspecialchars()`. JS-sidan har `escHtml()`.
- **Inga SQL-injektioner.** Projektet har ingen databas, men validera alltid filnamn med `basename()` vid filoperationer.
- **Inga inline-skript och inga `on*`-attribut** i PHP-vyerna (CSP är enforcing). Data till JS skrivs i `<script type="application/json">`-block.
- **Servern saknar `mbstring`.** Använd inte `mb_*`-funktioner i ny kod.
- **Inga tysta undantag.** Fel loggas eller returneras explicit.

## Fällor (detaljer i ARCHITECTURE.md)

- All behörighetslogik för spår bor i `access.php`. Duplicera den aldrig; `index.php`, `stream.php` och API:erna delar samma regel.
- Spår-URL:erna (`music/<fil>`) är nycklar i profiler, spellistor, kö och `plays.jsonl`. Ändra dem inte.
- Nya JSON-API:er går via `api_bootstrap()` i `api/_bootstrap.php` (metod, inloggning, CSRF, storlek, JSON).
- Formulär: `csrf_field()` och `csrf_require()`. Gäst-API:er använder `current_user_or_guest()`, inte `require_login()`.
- nginx: en location med egen `add_header` ärver inga säkerhetsrubriker — lägg in include-raderna där också.
- `UPLOAD_GROUP` (`uploaded`) syns bara för admin och kan aldrig tilldelas användare.
- Teman: inga hårdkodade färger, text på accent = `var(--on-accent)`. Kör kontrasttestet efter temaändringar.
- Ändrar du `.value` på ett reglage i JS: anropa `paintRange(el)`.

## Karta över ARCHITECTURE.md

| Arbetar du med … | Läs avsnittet |
|---|---|
| Inloggning, sessioner, spärr, klient-IP | Autentisering och sessioner · Inloggningsspärr · CSRF och audit |
| Ljudfiler, behörighet, cache | Skyddad medialeverans · Kanaler och etiketter · Spårmodell |
| nginx, rubriker, CSP, PHP-FPM | nginx och säkerhetsrubriker |
| API:er, validering, gränser | API-kontrakt och validering |
| Admin | Admin: grupper · Admin: uppladdning · Spelningslogg |
| player.js, profiler, spellistor | Klientside · Serverside-persistens |
| Utseende | Teman |
| Server, deploy, loggar | Filrättigheter · Loggrotation · Deploy |
| Vad som återstår | Öppna punkter |

## Tester

Körs från webroten på servern; ingen av dem skriver till riktiga data.

```
php tests/api_validation_test.php
php tests/groups_store_test.php
php tests/upload_validation_test.php
php tests/channels_test.php
php tests/theme_contrast_test.php
bash /var/www/clio_music/tests/security_smoke.sh
```

## Drift i korthet

Host `clioadmin@100.107.127.104`, webbrot `/var/www/clio_music/`, PHP 8.3-FPM, nginx på 127.0.0.1:8091 bakom cloudflared. Deploy via `~/staging/clio_music_<sprint>/deploy.sh` (backup, `php -l`, `nginx -t`, smoke-test); rollback med `rollback.sh`. Hela flödet i ARCHITECTURE.md → Deploy.
