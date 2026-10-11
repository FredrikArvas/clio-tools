# Säkerhet — clio_music

Kort beskrivning av säkerhetsmodellen efter saneringen S1–S6 (version 1.6.0). Detaljer per funktion finns i CLAUDE.md.

## Säkerhetsmodell

- **Medialeverans.** Ljudfiler och lyrics går alltid via `stream.php`, som kontrollerar behörigheten (`access.php`). Först därefter levererar nginx filen via `X-Accel-Redirect` från `internal`-locations. Filerna kan inte nås direkt. Ogiltigt namn ger 400, saknad fil 404, nekad åtkomst 403.
- **nginx.** Lyssnar bara på `127.0.0.1:8091`. Publik trafik kommer via cloudflared och Cloudflare. `/data/` och `/tests/` nekas. Endast explicit listade PHP-filer körs. Säkerhetsrubriker sätts på servernivå, och CSP är enforcing (`script-src 'self'` plus Googles taggbibliotek).
- **Sessioner.** HttpOnly, SameSite=Lax, Secure bakom HTTPS, strict mode. Session-id byts vid inloggning. Absolut timeout 12 h, inaktivitetsgräns enligt `session.gc_maxlifetime` (1440 s). Utloggning är POST med CSRF.
- **CSRF.** Formulär har `csrf_field()` och `csrf_require()`. JSON-API:erna kräver `X-CSRF-Token` på POST.
- **Inloggningsspärr.** `login_throttle.php` räknar per användarnamn (5 fria försök) och per IP (20 fria). Spärren växer exponentiellt från 30 s till 15 min. nginx begränsar dessutom POST /login.php till 10/min med burst 5.
- **API-begränsningar.** `api_bootstrap()` kontrollerar metod, inloggning, CSRF, Content-Type, storlek och JSON-form. Innehållet valideras mot en vitlista (`api/_validation.php`). Gränser för storlek och antal är konstanter i `config.php`. `log_play` begränsas till 10/min per gäst-IP och 60/min per användare. nginx begränsar `/api/` till 120/min med burst 20.
- **Lösenord.** bcrypt. Okända användarnamn verifieras mot en dummy-hash för jämn svarstid.
- **Auditlogg.** `data/audit.jsonl` innehåller inloggningar, utloggningar, avvisad CSRF, utgångna sessioner och admin-sparningar. Nycklar som ser ut som hemligheter filtreras bort.

## Lägga till användare

1. Skapa bcrypt-hash på servern. Kommandot står även i `help_admin.php`. Lösenordet skrivs när det efterfrågas, så det hamnar inte i kommandohistoriken:
   ```bash
   php -r 'echo password_hash(trim(fgets(STDIN)), PASSWORD_BCRYPT, ["cost" => 12]), "\n";'
   ```
2. Lägg till en rad i `data/users.csv`:
   ```
   användarnamn;[hash];Visningsnamn;1;0;Grupp1|Grupp2
   ```
   Kolumnerna: användarnamn, hash, visningsnamn, aktiv (1/0), admin (1/0), grupper (pipe-separerade).
   Filen ägs av `www-data` och har rättigheterna 640, så `clioadmin` redigerar den som webbserverns användare: `sudo -u www-data nano /var/www/clio_music/data/users.csv` (behåller ägare och rättigheter).

## Grupper

- Grupper sätts i admin-gränssnittet under **Grupper** (`admin/groups.php`). Fliken *Användare* kryssar i grupper per användare. Fliken *Låtar* väljer grupp per låt.
- Gruppnamn får vara 1–40 tecken: bokstäver, siffror, mellanslag, `_` och `-`.
- Varje sparning kräver CSRF, valideras mot kända användare, grupper och filer och loggas som `admin_groups_saved` eller `admin_groups_rejected`. Sparning som skulle lämna ingen aktiv admin avvisas.
- Spår utan grupp syns för inloggade användare, men aldrig för gäster.

## Tester

- Säkerhetsrök på servern: `bash /var/www/clio_music/tests/security_smoke.sh`. Testet körs mot `127.0.0.1:8091` och kräver `sudo`. Inloggade tester använder en tillfällig sessionsfil för `__smoketest__`, så riktiga användare påverkas inte.
- Enhetstester: `php /var/www/clio_music/tests/api_validation_test.php` och `php /var/www/clio_music/tests/groups_store_test.php`. Det senare testet använder fixture-filer.

## Vid misstänkt intrång

1. **Granska `data/audit.jsonl`.** Titta på `login_failed`, `login_blocked`, `csrf_rejected` och `admin_groups_*`. Äldre rader finns i roterade filer `audit.jsonl.N.gz` i samma katalog.
2. **Granska nginx-loggarna** `/var/log/nginx/access.log` och `/var/log/nginx/error.log`.
3. **Stäng ute kontot.** Byt lösenord enligt ovan och ersätt hashen i `users.csv`. Sätt aktiv till 0 om kontot ska stängas av.
4. **Rensa sessioner** vid behov: `sudo rm /var/lib/php/sessions/sess_*`. Det loggar ut alla inloggade.
5. **Återställ vid behov.** Backuper ligger i `~/backups/clio_music.bak_<datum>_<sprint>`. Rollback-skripten ligger i `~/staging/clio_music_<sprint>/rollback.sh`. S6-rollback återställer ägare, rättigheter, `config.php` och smoke-testet, men inte innehållet i `data/`.
6. **Rapportera till Fredrik** innan något ändras vidare.
