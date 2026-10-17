# CLAUDE.md — clio_music

Kontext för LLM-assistenter som arbetar med detta projekt. Säkerhetsmodellen i korthet finns i SECURITY.md.

## Vad projektet är

PHP-baserad musikspelare för meditationsljud (Miranon Media / Roger Gottardsson). Inloggningsskyddad, inga ramverk, inga npm-beroenden. Körs på EliteDesk GPU bakom Cloudflare på https://audio.examensbyran.se. Version: `APP_VERSION` i `config.php` (1.6.0 efter säkerhetssaneringen S1–S6).

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

## Arkitektur

### Autentisering och sessioner (auth.php, S2)
- Session-baserad, bcrypt-lösenord. `current_user()` returnerar `{username, display, admin, groups}` för inloggade. `current_user_or_guest()` returnerar inloggad användare eller gäst-objekt `{username: '__guest__', groups: ['Gäst']}` (GUEST_GROUP i config.php).
- `start_session()`: HttpOnly, SameSite=Lax, Secure bakom HTTPS (`request_is_https()`), `use_strict_mode`. Absolut timeout `SESSION_ABSOLUTE_TIMEOUT` = 12 h. Inaktivitetsgräns `SESSION_IDLE_TIMEOUT` = `session.gc_maxlifetime` (1440 s, styrs av Debians cron-städning).
- `login_user()` byter sessions-id. `logout_user()` tömmer och förstör sessionen.
- Okända användarnamn verifieras mot `DUMMY_PASSWORD_HASH` (jämn svarstid).
- `require_login()` redirectar till /login.php, även från admin/. API-endpoints som ska vara tillgängliga för gäster använder `current_user_or_guest()`, inte `require_login()`.
- Grupper styr vilka spår användaren ser. Gruppen `Alla` ger tillgång till allt utom `UPLOAD_GROUP` (se nedan).
- **`UPLOAD_GROUP`** (`uploaded`, config.php, v1.11.0): nyuppladdade spår. `user_can_see()` släpper bara igenom admin, och regeln ligger *före* `Alla`-kontrollen, så varken `Alla`, vanliga användare eller gäster ser dem. Gruppen kan väljas för spår i Låtar-fliken men aldrig tilldelas användare (`user_assignable_groups()`, validering i `groups_store.php`).

### Inloggningsspärr och klient-IP (S2)
- **`login_throttle.php`**: räknare per användarnamn (5 fria försök) och per IP (20 fria). Exponentiell spärr 30 s → 15 min. Lagras i `data/login_attempts/`, flock-skyddat. Kontrolleras före lösenordet.
- **`client_ip.php`**: `client_ip()` och `request_is_https()`. Proxy-headers (CF-Connecting-IP, X-Forwarded-Proto) litas bara på när REMOTE_ADDR är loopback (cloudflared-tunneln).
- nginx har dessutom `limit_req` på POST /login.php (10/min, burst 5).

### CSRF och audit (S2)
- **`csrf.php`**: `csrf_token()`, `csrf_field()`, `csrf_verify()`, `csrf_require()`, `logout_button($action)`. Formulär: `<?= csrf_field() ?>` och `csrf_require()` först i POST-hanteringen. Logout är POST med CSRF.
- `player.js` skickar `API_HEADERS` (inkl. `X-CSRF-Token: CM_CSRF`) i alla POST-anrop.
- **`audit.php`**: `audit_log($event, $context)` → `data/audit.jsonl`. Nycklar som matchar pass/hash/token/secret filtreras bort. Events: `login_ok`, `login_failed`, `login_blocked`, `logout`, `session_expired`, `csrf_rejected`, `password_rehashed`, `password_rehash_needed` (skrivfel), `admin_groups_saved`, `admin_groups_rejected`, `admin_upload_ok`, `admin_upload_rejected` (v1.11.0).

### Skyddad medialeverans (access.php + stream.php, S1)
- **All behörighetslogik för spår bor i `access.php`** (`load_track_groups`, `track_group`, `user_can_see`, `scan_music`, `main_channel_file`, `owning_tracks`, `user_can_access_media`, `track_file_url`, `list_visible_tracks`, `visible_track_urls`). Duplicera den aldrig.
- Kanalfiler och `.lrc` ärver gruppen från huvudspåret (`main_channel_file()`: första suffixet i `CH_SUFFIXES`, normalt `_msc`).
- nginx skickar `^~ /music/` och `^~ /lyrics/` till `stream.php` via FastCGI. **URL:erna är oförändrade** (`music/<fil>`), eftersom profiler, spellistor, kö och `plays.jsonl` nycklas på URL:en.
- `stream.php` validerar filnamnet (ett segment, rätt ändelse), kontrollerar behörigheten och svarar med `X-Accel-Redirect: /_protected/{music|lyrics}/<fil>`. nginx levererar filen (Range/seek) från `internal`-locations som bara aliasar `music/` resp. `lyrics/`.
- Svar: 400 ogiltigt namn, 404 saknas, 403 nekad (även för befintliga filer). Fel och nekade svar: `Cache-Control: private, no-store`.
- Cachning (v1.8.0, beslut Fredrik 2026-10-16): gästspår `public, max-age=604800` (Cloudflare får cacha), övriga `private, max-age=604800` + `Vary: Cookie`. Flyttas ett gästspår till annan grupp: purga filen i Cloudflare.

### Kanaler och etiketter (v1.10.0)
- Suffixet styr etiketten. `CH_SUFFIXES` i access.php (behörighet, gruppering): `_msc _vce _env _bin _ch2 _ch3 _ch4`. Presentation och platser i `channels.php` (`CHANNELS`, `channel_slots()`, `is_choir_track()`).
- Fyra platser (`MAX_CHANNEL_SLOTS`): `msc` = master (förlopp, loggning, EQ), `s1–s3` = valfria kanaler i `CHANNEL_SLOT_ORDER`. Fler kanaler loggas och spelas inte. `_msc` heter "Stämma 1" om spåret har någon `_chN`-fil, annars "Musik".
- Profilnycklar = suffix utan understreck (`msc`, `bin`, `ch2` …), inte platsen. `TRACKS[i].channels` = `[{key, url, label, icon, list_icon, default}]` i platsordning.
- Ersätter v1.9.0:s `track_types.php`/`data/track_types.csv` (borttagna). Test: `php tests/channels_test.php`.

### nginx och säkerhetsrubriker (S5)
- Konfigen finns i repot: `deploy/nginx_clio_music.conf` (= `/etc/nginx/sites-available/clio_music`), snippets `deploy/clio_music_security_headers.conf` och `deploy/clio_music_csp.conf` (= `/etc/nginx/snippets/`). Ändra i repot, validera i staging, deploya, ladda om.
- nginx lyssnar **bara på 127.0.0.1:8091**. All publik trafik kommer via cloudflared. Ingen direktväg förbi Cloudflare.
- `location /data/ { deny all; }` skyddar data/. data/.htaccess är borttagen ur repot: den är Apache-syntax och verkningslös under nginx. `location /tests/ { deny all; }` skyddar tests/.
- Rubriker (`always`, server-nivå): nosniff, Referrer-Policy, Permissions-Policy, X-Frame-Options DENY, CSP. **nginx-arv:** en location med egen `add_header` ärver inga rubriker från servernivån. Lägg då in de två include-raderna där också.
- **CSP är enforcing** sedan 2026-10-11: `script-src 'self' https://www.googletagmanager.com`. Stilar får `'unsafe-inline'` (medvetet undantag). `deploy_enforce.sh` byter bara rubriknamnet från Report-Only till enforcing.
- `server_tokens off`, `fastcgi_hide_header X-Powered-By`, `client_max_body_size` 256k (server) och 64k (`/api/`). `location = /admin/upload.php` (v1.11.0): 96M, `client_body_timeout`/`fastcgi_read_timeout` 300s, ingen egen `add_header` (ärver rubrikerna). `admin/upload_validation.php` nekas som `groups_store.php`.
- **PHP-FPM för uppladdning:** egen pool `clio_music_upload` (`deploy/php-fpm_clio_music_upload.conf` = `/etc/php/8.3/fpm/pool.d/clio_music_upload.conf`, socket `php8.3-fpm-clio_music_upload.sock`, `pm = ondemand`). Bara `location = /admin/upload.php` använder den. `upload_max_filesize = 96M`, `post_max_size = 97M`, `max_input_time`/`max_execution_time = 300`. Poolen `www` (delad med andra sajter) behåller php.ini:s 2M/8M/30 s. Samma användare och php.ini, så sessionerna delas. `fileinfo` finns på servern. Kroppen buffras på disk två gånger (nginx `client_body_temp_path` + PHP:s tempkatalog).
- **Rättigheter för uppladdning:** `music/` → `clioadmin:www-data` 775. `music/.incoming/` skapas av PHP med 770. `limit_req` zon `clio_music_api` (120/min, burst 20) på `/api/`.
- Åtkomstloggar: `/var/log/nginx/access.log` och `error.log`.

### API-kontrakt och validering (S3)
- **`api/_bootstrap.php`**, kontrakt för alla JSON-API:er:
  ```php
  require_once __DIR__ . '/_bootstrap.php';
  ['user' => $user, 'body' => $body] = api_bootstrap(['method' => 'POST', 'allow_guest' => false, 'max_bytes' => 16384]);
  // validera $body själv …
  api_respond(['ok' => true]);   // eller api_error(400, 'invalid track');
  ```
  Garanterar metod (405), inloggning (401), för POST: CSRF via `X-CSRF-Token` (403), `application/json` (415), storlek (413), giltig JSON-array (400). Sessionen är stängd efteråt (skrivskyddad).
- Gäster får 401 på save_*, tomt svar på load_*. `load_*` returnerar sparade filer som de är. En trasig fil loggas och ger tomt svar.
- **Delad spårregel:** `index.php` och API:erna använder samma lista från `access.php` (`list_visible_tracks()`, `visible_track_urls()`). API:erna validerar mot de spår *just den användaren* får se.
- **`api/_validation.php`** (ren funktionsfil, testas med `php tests/api_validation_test.php`): vitlista per profilnyckel (`msc/bin/vce/env` 0–1, `balance` −1..1, `bass/treble` −12..12, `liked` bool; `_settings`: `playMode`, `playbackRate` 0.5–2, `queue`, `queueCursor`). Okända nycklar kastas, värden utanför intervall ger 400. Kö och spellistor filtreras mot kända spår (avvisas inte).
- Gränser är konstanter i config.php: `MAX_REQUEST_BYTES`, `MAX_LOG_PLAY_BYTES`, `MAX_PROFILE_TRACKS`, `MAX_QUEUE_LENGTH`, `MAX_PLAYLISTS_PER_USER`, `MAX_TRACKS_PER_PLAYLIST`, `MAX_PLAYLIST_NAME_LENGTH`, `MAX_TRACK_URL_LENGTH`.
- **`rate_limit.php`**: `rate_limit_hit($bucket, $key, $max, $window)` → 0 eller Retry-After-sekunder (`RATE_LIMIT_DIR` = `data/rate_limits/`). `log_play` räknar gäster per IP (`LOG_PLAY_GUEST_MAX_PER_MINUTE` = 10) och inloggade per användare (`LOG_PLAY_USER_MAX_PER_MINUTE` = 60) *före* validering, och svarar 429.
- **`json_store.php`**: `json_file_update()` (flock-skyddat läs-ändra-skriv; `abort` skriver inte över trasig JSON) och `json_file_read()`. Används av login_throttle, rate_limit, save_profile och save_playlist.
- `player.js`: `apiPost()` ersätter fetch-anropen. 400/403/413/429 ger bara `console.warn`. 401 (gäst) är tyst.

### Admin: grupper (S4)
- **`admin/groups_store.php`** (data) och **`admin/groups.php`** (vy och formulärhantering) är åtskilda. Lagret har inga bieffekter och testas med `php tests/groups_store_test.php` mot fixture-filer. Testet rör aldrig riktiga `users.csv` eller `track_groups.csv`.
- Gruppnamn valideras mot `GROUP_NAME_PATTERN` i config.php (vitlista, 1–40 tecken, `D`-flaggan). Filnamn måste finnas i `music/` och vara CSV-säkra. Formulärets användare, grupper och filer valideras mot kända mängder. Okända nycklar avvisar hela begäran (400, inget skrivs).
- Spårgrupp avgörs av `track_group()` i `access.php` (samma regel som `stream.php`). Nya filnamnsrader läggs först i `track_groups.csv` så att de vinner över prefixregler. Prefixregler och kommentarer bevaras.
- Skrivning: flock på `<fil>.lock`, tempfil i samma katalog och `rename`, rättigheter bevaras. Rader som inte ändras skrivs tillbaka byte för byte. I `users.csv` ändras bara grupp-kolumnen. Sparning som lämnar ingen aktiv admin avvisas.
- Alla formulär har `csrf_field()`. POST kräver `csrf_require()` efter adminkontrollen (icke-admin → 403). Sparningar och avvisningar loggas som `admin_groups_saved` och `admin_groups_rejected` (utan hashar).

### Admin: uppladdning (v1.11.0)
- **`admin/upload.php`**: POST multipart, fältet `file`, en fil per anrop. Svar JSON `{ok, filename, bytes, warnings}` eller `{ok: false, error, message}`. Ordning: inloggning (401), admin (403), POST (405), CSRF via `X-CSRF-Token` (403), `rate_limit_hit('upload', användare, UPLOAD_MAX_PER_HOUR, 3600)` (429 + Retry-After), `$_FILES`-fel (400/413), validering (400/413/415), finns redan (409).
- **Grupprad före fil:** `fil;uploaded` skrivs med `save_track_groups()` och kontrolleras med `track_group()` innan filen flyttas (spår utan rad syns för alla inloggade). Filen går `move_uploaded_file()` → `music/.incoming/<slump>.part` (664) → `rename()` till `music/<fil>`. Fel efter gruppraden återställer spårets tidigare grupp. Steget från existenskontroll till rename körs under `with_file_lock(music/.incoming/upload)`.
- **`admin/upload_validation.php`** (ren funktionsfil, nekas av nginx, testas med `php tests/upload_validation_test.php`): `validate_upload_filename()` (ett segment, giltig UTF-8, inga kontroll-/formattecken, inga `/ \ ;`, inte inledande `.`/`#`/blanksteg, URL:en ≤ `MAX_TRACK_URL_LENGTH`), `validate_upload_size()` (1..`UPLOAD_MAX_BYTES` = 95 MB), `validate_upload_content()` (ID3/MPEG-ramsynk resp. `ftyp`; finfo när tillägget finns), `check_channel_rules()` och `check_group_inheritance()` (varningar, avvisar inte). Felkoder → status och svensk text i `UPLOAD_ERRORS`.
- **Ändelsen sparas med gemener** (`x.MP3` → `x.mp3`): `scan_music()` globbar `*.mp3`/`*.m4a`, skiftlägeskänsligt på Linux.
- Kanalfiler ärver huvudspårets grupp. En ny `_bin` till ett befintligt spår hörs alltså direkt för spårets grupp; en ny `_msc` tar över och döljer hela spåret. Båda fallen ger en varning i svaret.
- Ingen överskrivning och ingen borttagning i UI. Fel fil rättas via SSH (fil i `music/` + rad i `data/track_groups.csv`).
- UI: fliken **Ladda upp** i `admin/index.php` (`?view=upload`), JS i `admin/upload.js` (XHR per fil, progress, `textContent`). Konfig och CSRF-token i `<script type="application/json" id="upload-config">`.

### Spelningslogg (api/log_play.php + admin/index.php)
- Loggar till `data/plays.jsonl` efter 5 s uppspelning (kräver `audios.msc` playing-event).
- Gäster loggas under `__guest__`. `loggedTrack` nollställs vid varje `load()`, så omval av samma spår räknas som ny lyssning.
- Admin-dashboarden räknar **över all tid**: `read_play_log_lines()` i admin/index.php läser roterade filer (`plays.jsonl.N`, `plays.jsonl.N.gz`) plus aktuell `plays.jsonl`.
- Admin-dashboarden filtrerar per lyssnargrupp (GET `?group=X`).

### Serverside-persistens
- `data/profiles/{username}.json`: objekt med filens URL som nyckel → ljudinställningar. `_settings`-nyckeln lagrar globala inställningar (playMode, hastighet, kö).
- `data/playlists/{username}.json`: objekt med spellistenamn som nyckel → array av fil-URL:er.
- Båda skrivs via `json_file_update()` (flock) och är nyckade på URL.

### Klientside (player.js)
- `TRACKS[]` injiceras från PHP som JSON i `<script type="application/json" id="cm-data">` (tillsammans med CM_USER, CM_USER_TYPE, CM_CSRF) och läses med `JSON.parse`.
- `current`: index i TRACKS för aktuellt spår. `queue[]`: `{idx, id}`, sparas server-side via `_settings`. `playlists{}`: laddas från `api/load_playlists.php`.
- Tre flikar: `lib` (bibliotek), `queue` (kö), `pl` (spellistor). Byt med `switchTab(tab)`.
- Album grupperas per albumtagg i PHP (`$album_groups`). Saknar spåret albumtagg grupperas det under sin behörighetsgrupp (v1.11.1, `track_section()` i channels.php, `_` visas som mellanslag); spår i `UPLOAD_GROUP` under "Nyuppladdat (bara admin)", spår utan både album och grupp utan rubrik. Rubriken ligger i `TRACKS[i].section`; `album` är fortfarande bara taggen (artistraden, låsskärmen). Kollapsade album sparas i `localStorage` under `clio_collapsed_albums`.
- **Bakgrundsuppspelning:** Web Audio API initieras lazy, först när användaren rör balance/bas/diskant-reglagen. Före lazy-init används `audios[ch].volume` (native HTML), som iOS/Android kan spela i bakgrunden. Media Session API (låsskärm, titel, seek) och Wake Lock API (släpps vid paus) är registrerade.
- **Lyrics:** LRC-filer i `lyrics/`, namngivna `{spårnamn_utan_suffix}.lrc`. Visas i `#lyrics-panel`. Aktuell rad highlightas och auto-scrollas via `updateLyricsLine(currentTime)`. Klick på rad anropar `seekAll(line.time)`. Sökfältet `#lyrics-search` filtrerar i realtid och pausar auto-scroll. Sökning och scroll-state nollställs vid `loadLyrics()`.

### Teman (v1.7.0)
- Ett tema är bara värden på CSS-variabler i `style.css` (`:root, [data-theme="natt"]`, `[data-theme="morgon"]` m.fl.). Layouten ändras aldrig. Sex teman: natt (standard), morgon, skymning, skog, lavendel, kontrast.
- `theme.js` laddas **synkront i `<head>`** (före style.css) och sätter `data-theme` på `<html>` från `localStorage` (`clio_theme`), så inget blinkar. Samma fil bygger temaväljaren (`#btn-theme` + `#theme-panel`) och validerar valet mot en vitlista. Valet är per enhet, inte sparat på servern än.
- Ny tema = ett nytt `[data-theme]`-block med alla tio variabler plus `--on-accent`, och en post i `THEMES` i `theme.js`. **Kör `php tests/theme_contrast_test.php`**: den mäter WCAG-kontrasten för alla färgpar som används.
- Komponenter får inte hårdkoda färger. Text på fylld accent använder `var(--on-accent)`, aldrig `#fff`.
- Reglagens fyllda del styrs av `--fill`, som `paintRange()` i `player.js` sätter. Ändra du `.value` på ett reglage i kod, anropa `paintRange(el)`.
- Loggan: `$logo_url` i `config.php` (fil i `assets/`). Tom sträng = ingen logga. Loggan har vit bakgrund och visas därför som rund bricka.

### Spårmodell
Spår i `music/` skannas med glob (`scan_music`). Filer med suffix `_msc/_bin/_vce/_env` grupperas till ett flerkanalsspår. Övriga filer renderas som standalone. Metadata läses med intern ID3v1/v2-läsare (inga externa libs).

## Filrättigheter på servern (S6)

Verifierat med `ls -l` före och efter S6. Skript: `~/staging/clio_music_S6/apply.sh`, rollback: `rollback.sh`.

| Sökväg | Ägare:grupp | Rättighet | Anmärkning |
|---|---|---|---|
| `data/` | clioadmin:www-data | 775 | PHP skapar låsfiler och tempfiler här. Ska vara kvar. |
| `data/users.csv`, `data/track_groups.csv` | www-data:www-data | 640 | Läses och skrivs av PHP (admin). clioadmin kan inte läsa dem utan sudo. |
| `data/audit.jsonl`, `data/plays.jsonl` | www-data:www-data | 660 | |
| `data/profiles/`, `data/playlists/` | clioadmin:www-data | 775 | Filerna i dem: 664, ägare www-data. |
| `data/login_attempts/`, `data/rate_limits/` | www-data | 750 | Skapade av PHP. Lämnas orörda. |

- `data/plays.jsonl.bak_*` flyttades i S6 till `~/backups/clio_music/` (utanför webroten). Inga `.bak`-filer ska ligga i webroten.
- Admin-sparning av `users.csv` och `track_groups.csv` fungerar eftersom PHP körs som www-data. Manuell redigering görs med `sudoedit` (se SECURITY.md).

## Loggrotation (S6)

- `/etc/logrotate.d/clio_music` (källa: `deploy/logrotate_clio_music`): veckovis, `rotate 12`, `compress`, `delaycompress`, `copytruncate`, `missingok`, `notifempty`, `su www-data www-data`. Gäller `data/plays.jsonl` och `data/audit.jsonl`.
- Roterade filer hamnar i `data/` som `plays.jsonl.1`, `plays.jsonl.2.gz` osv. Mönstren `data/plays.jsonl*` och `data/audit.jsonl*` är git-ignorerade.
- `copytruncate` eftersom PHP håller filen öppen med O_APPEND. Rader som skrivs mellan kopia och trunkering kan gå förlorade.
- Admin-dashboarden räknar över rotation (beslut Fredrik 2026-10-11, v1.6.1): roterade filer läses med `gzfile()`/`file()`.
- Kontroll: `sudo logrotate -d /etc/logrotate.d/clio_music` (torrkörning).

## Deploy

Ändringar förbereds i `~/staging/clio_music_<sprint>/` på servern. Deploy-skriptet (`deploy.sh`) i samma katalog gör följande.
1. Avbryter om backupen redan finns. Annars tar den backup: `sudo cp -a /var/www/clio_music ~/backups/clio_music.bak_<datum>_<sprint>`.
2. Validerar PHP (`php -l`) och, om nginx ändrats, konfigen (`nginx -t` mot en testkonfig).
3. Kopierar webroten. Vid nginx-ändring kopieras snippets och konfig. Vid fel återställs konfigen och ingen reload görs.
4. Laddar om nginx med restart, eftersom listen-adressen kan ändras.
5. Kör `bash /var/www/clio_music/tests/security_smoke.sh`.

Rollback: `rollback.sh` i samma katalog återställer från backupen. Skripten versioneras inte i repot. Efter deploy kontrolleras uppspelning, sparning av profil och admin-sparning manuellt.

Övrigt:
- Host: `clioadmin@100.107.127.104` (EliteDesk GPU, Tailscale-IP)
- Webbrot: `/var/www/clio_music/`. Musikfiler i `/var/www/clio_music/music/`.
- PHP 8.3-FPM, nginx port 8091, Cloudflare framför.

## Tester

- **`tests/security_smoke.sh`**: skickar `Host: $SMOKE_HOST` (standard `audio.examensbyran.se`) i alla anrop, eftersom nginx annars svarar med den gamla domänens 301. Körs på servern (`bash /var/www/clio_music/tests/security_smoke.sh`) mot 127.0.0.1:8091, förbi Cloudflare. Inloggade tester använder en tillfällig sessionsfil för `__smoketest__` i `/var/lib/php/sessions`, så `users.csv` rörs inte. Testets rader i `audit.jsonl` och `plays.jsonl` rensas efteråt. Läser `track_groups.csv` via `sudo -u www-data` (640).
- **`php tests/api_validation_test.php`**, **`php tests/groups_store_test.php`**, **`php tests/upload_validation_test.php`** och **`php tests/channels_test.php`**: kan köras från webroten på servern. Ingen av dem skriver till riktiga data. upload_validation_test skapar sina små ljud-fixtures i en tempkatalog och testar även `user_can_see()` med `UPLOAD_GROUP`.
- `security_smoke.sh` har ett uppladdningsavsnitt (v1.11.0): 401/403/405/415/409, lyckad uppladdning av en liten mp3, att raden `uploaded` finns och att icke-admin och gäst får 403 på filen. Testfilen, gruppraden och hastighetsräknaren tas bort efteråt (även vid avbrott).
- Testprotokollet T1–T12 och fynden 1–13 finns i granskningsrapporten (`Säkerhetsgranskning_OWASP_2026-10-11.md`).

## Öppna punkter

- Favicon saknas (404).
- Admin-fliken Låtar låter grupp sättas på kanalfiler (`_vce/_bin/_env`) trots att huvudspåret styr åtkomsten.
- `track_label()` i admin/index.php strippar inte kanal-suffixet `_msc`. Spårnamnet syns därför med suffix i admin-dashboarden.
- ~~Automatisk omhashning av lösenord uteblir~~ — åtgärdat v1.7.4: `save_user_hash()` i auth.php byter hash-kolumnen atomiskt vid inloggning.
- Cloudflare-cache bör purgas för `frida_session_edited.*`.
- Uppladdning nästa sprint: chunkad uppladdning (> 95 MB), borttagning/ersättning i UI.
- Uppladdning: `x.mp3;uploaded` är som alla filnamnsrader i `track_groups.csv` också en prefixregel och läggs först. En befintlig fil vars namn börjar med det nya namnet (t.ex. `x.mp3.mp3`) hamnar därför också i `uploaded` (döljs, exponeras inte).
- Användaradmin (skapa/inaktivera användare, sätta lösenord) i admin-gränssnittet — egen sprint, beslutad 2026-10-11. Tills dess: `sudo -u www-data nano data/users.csv` (filen är 640).
- `help_admin.php` beskriver att `users.csv` redigeras via SSH/SFTP. Efter S6 kräver det sudo. Texten är inte ändrad (PHP-fil utanför S6).
- White-label/teman (se Fredriks plan).
- Eventuellt: omslagsbilder per album.
- Eventuellt: genrer/taggar-filtrering.
