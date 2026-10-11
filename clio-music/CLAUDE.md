# CLAUDE.md — clio_music

Kontext för LLM-assistenter som arbetar med detta projekt.

## Vad projektet är

PHP-baserad musikspelare för meditationsljud (Miranon Media / Roger Gottardsson). Inloggningsskyddad, inga ramverk, inga npm-beroenden. Körs på EliteDesk GPU bakom Cloudflare på https://audio.arvas.international.

## Regler och konventioner

- **Inga ramverk.** Vanilla JS + Web Audio API på klientsidan. PHP utan Composer.
- **Inga hårdkodade URL:er.** Använd `$music_url` från config.php.
- **APP_VERSION** i config.php ska bumpa vid varje deploy — används för Cloudflare cache-bust på player.js.
- **data/-mappen är känslig.** users.csv, plays.jsonl, profiles/ och playlists/ är git-ignorerade och innehåller riktiga användardata.
- **Bcrypt** för lösenord, aldrig klartext. Hash genereras via SSH (se help_admin.php); `admin/hash_tool.php` är borttaget (S4).
- **Inga XSS-risker.** Allt som skrivs ut via PHP ska passera `htmlspecialchars()`. JS-sidan har `escHtml()`.
- **Inga SQL-injektioner** — projektet har ingen databas, men validera alltid filnamn med `basename()` vid filoperationer.

## Arkitektur

### Autentisering (auth.php)
- Session-baserad, bcrypt-lösenord
- `current_user()` returnerar `{username, display, admin, groups}` för inloggade
- `current_user_or_guest()` returnerar inloggad användare eller gäst-objekt `{username: '__guest__', groups: ['Gäst']}`
- Grupper styr vilka spår användaren ser (`user_can_see()` i index.php)
- Gruppen `Alla` ger tillgång till allt
- **API-endpoints som ska vara tillgängliga för gäster** ska använda `current_user_or_guest()`, inte `require_login()`

### Skyddad medialeverans (access.php + stream.php, v1.5.0)
- **All behörighetslogik för spår bor i `access.php`** (`load_track_groups`, `track_group`, `user_can_see`, `scan_music`, `main_channel_file`, `owning_tracks`, `user_can_access_media`). Duplicera den aldrig.
- Kanalfiler (`_bin/_vce/_env`) och `.lrc` ärver gruppen från huvudspåret (`_msc ?? _vce ?? _env ?? _bin`).
- nginx skickar `^~ /music/` och `^~ /lyrics/` till `stream.php` via FastCGI. **URL:erna är oförändrade** (`music/<fil>`), eftersom profiler, spellistor, kö och `plays.jsonl` nycklas på URL:en.
- `stream.php` validerar filnamnet (ett segment, rätt ändelse), kontrollerar behörigheten och svarar med `X-Accel-Redirect: /_protected/{music|lyrics}/<fil>`. nginx levererar filen (Range/seek) från `internal`-locations som bara aliasar `music/` resp. `lyrics/`.
- Svar: 400 ogiltigt namn, 404 saknas, 403 nekad (även för befintliga filer), `Cache-Control: private, no-store`.
- Test: `tests/security_smoke.sh` körs på servern (`bash /var/www/clio_music/tests/security_smoke.sh`). Inloggade tester använder en tillfällig sessionsfil för `__smoketest__`, så `users.csv` rörs inte.
- nginx-konfigen ligger i `/etc/nginx/sites-available/clio_music` (inte i repot). `/tests/` är spärrad i nginx.

### Säkerhetsbas: session, login, CSRF, audit (v1.5.1)
- **`auth.php`** startar sessionen via `start_session()`: HttpOnly, SameSite=Lax, Secure bakom HTTPS (Cloudflare), `use_strict_mode`. Absolut timeout 12 h; inaktivitetsgräns = php.ini `session.gc_maxlifetime` (1440 s, styrs av Debians cron-städning). `login_user()` byter sessions-id, `logout_user()` tömmer och förstör. Okända användarnamn verifieras mot `DUMMY_PASSWORD_HASH` (jämn svarstid).
- **`client_ip.php`**: `client_ip()` och `request_is_https()`. Proxy-headers (CF-Connecting-IP, X-Forwarded-Proto) litas bara på när REMOTE_ADDR är loopback (cloudflared-tunneln).
- **`login_throttle.php`**: räknare per användarnamn (5 fria) och IP (20 fria) i `data/login_attempts/`, exponentiell spärr 30 s → 15 min, flock-skyddad. nginx har dessutom `limit_req` på POST /login.php (10/min, burst 5).
- **`csrf.php`**: `csrf_token()`, `csrf_field()`, `csrf_verify()`, `csrf_require()`, `logout_button($action)`. Formulär: `<?= csrf_field() ?>` + `csrf_require()` först i POST-hanteringen.
- **`audit.php`**: `audit_log($event, $context)` → `data/audit.jsonl`. Nycklar som matchar pass/hash/token/secret filtreras bort.
- **`api/_bootstrap.php`** — kontrakt för alla JSON-API:er:
  ```php
  require_once __DIR__ . '/_bootstrap.php';
  ['user' => $user, 'body' => $body] = api_bootstrap(['method' => 'POST', 'allow_guest' => false, 'max_bytes' => 16384]);
  // validera $body själv …
  api_respond(['ok' => true]);   // eller api_error(400, 'invalid track');
  ```
  Garanterar metod (405), inloggning (401), för POST: CSRF via `X-CSRF-Token` (403), `application/json` (415), storlek (413), giltig JSON-array (400). Sessionen är stängd efteråt (skrivskyddad).
- `player.js` skickar `API_HEADERS` (inkl. `X-CSRF-Token: CM_CSRF`) i alla POST-anrop.
- **Servern saknar `mbstring`** — använd inte `mb_*`-funktioner i ny kod.

### Admin: grupper (v1.5.2, S4)
- **`admin/groups_store.php`** (data) och **`admin/groups.php`** (vy + formulärhantering) är åtskilda. Lagret har inga bieffekter och testas med `php tests/groups_store_test.php` mot fixture-filer (rör aldrig riktiga `users.csv`).
- Gruppnamn valideras mot `GROUP_NAME_PATTERN` i `config.php` (vitlista, 1–40 tecken; `D`-flaggan stoppar avslutande radbrytning). Filnamn måste finnas i `music/` och vara CSV-säkra. Formulärets användare, grupper och filer valideras mot kända mängder; okända nycklar avvisar hela begäran (400, inget skrivs). Dolda fält (`groups_list[]`) finns inte längre.
- Spårgrupp avgörs av `track_group()` i `access.php` (samma regel som `stream.php`). Nya filnamnsrader läggs först i `track_groups.csv` så att de vinner över prefixregler; prefixregler och kommentarer bevaras.
- Skrivning: flock på `<fil>.lock`, tempfil i samma katalog + `rename`, rättigheter bevaras. Rader som inte ändras skrivs tillbaka byte för byte; bara grupp-kolumnen i `users.csv` ändras. Sparning som lämnar ingen aktiv admin avvisas.
- Alla formulär har `csrf_field()`; POST kräver `csrf_require()` efter adminkontrollen (icke-admin → 403). Sparningar och avvisningar loggas som `admin_groups_saved` / `admin_groups_rejected` (utan hashar).
- `admin/hash_tool.php` är borttaget. Generera hash via SSH: `php -r 'echo password_hash(trim(fgets(STDIN)), PASSWORD_BCRYPT, ["cost" => 12]), "\n";'`.

### Spårmodell
Spår i `music/` skannas med glob. Filer med suffix `_msc/_bin/_vce/_env` grupperas till ett flerkanalsspår. Övriga filer renderas som standalone. Metadata läses med intern ID3v1/v2-läsare (inga externa libs).

### Klientside-state
- `TRACKS[]` — injiceras från PHP som JSON i index.php, läses av player.js
- `current` — index i TRACKS för aktuellt spår
- `queue[]` — `{idx, id}` — kön, sparas server-side via `_settings`-nyckeln i profiles
- `playlists{}` — namngivna spellistor, laddas från `api/load_playlists.php`

### Serverside-persistens
- `data/profiles/{username}.json` — objekt med filens URL som nyckel → ljudinställningar. `_settings`-nyckeln lagrar globala inställningar (playMode, hastighet, kö).
- `data/playlists/{username}.json` — objekt med spellistenamn som nyckel → array av fil-URL:er.
- Båda skrivs med `LOCK_EX` för att undvika race conditions.

### Tab-system (player.js)
Tre flikar: `lib` (bibliotek), `queue` (kö), `pl` (spellistor). Byt med `switchTab(tab)`.

### Album-sektioner
Spår grupperas per albumtagg i PHP (`$album_groups`). JS hanterar toggle via `.collapsed`-klassen. Kollapsade album sparas i `localStorage` under nyckeln `clio_collapsed_albums`.

## Filrättigheter på servern
```
data/profiles/   → clioadmin:www-data, chmod 775
data/playlists/  → clioadmin:www-data, chmod 775
```

## Deploy-server
- Host: `clioadmin@100.107.127.104` (EliteDesk GPU, Tailscale-IP)
- Webbrot: `/var/www/clio_music/`
- PHP 8.3-FPM, nginx port 8091, Cloudflare framför
- Musikfiler i `/var/www/clio_music/music/`

### Spelningslogg (api/log_play.php + admin/index.php)
- Loggar till `data/plays.jsonl` efter 5 s uppspelning (kräver `audios.msc` playing-event)
- Gäster loggas under `__guest__`
- `loggedTrack` nollställs vid varje `load()` — omval av samma spår räknas som ny lyssnig
- Admin-dashboarden filtrerar per lyssnargrupp (GET `?group=X`)

### Bakgrundsuppspelning (player.js)
- **Web Audio API initieras lazy** — startas först när användaren rör balance/bas/diskant-reglagen
- Före lazy-init används `audios[ch].volume` (native HTML), som iOS/Android kan spela i bakgrunden
- Efter lazy-init hanteras volymen av gain-noder; `ctx.onstatechange` försöker auto-resumera vid upplåsning
- **Media Session API** registrerat: låsskärmskontroller, spårtitel/artist, seek-position
- **Wake Lock API** håller skärmen tänd under uppspelning (släpps vid paus)

### Lyrics (player.js + index.php)
- LRC-filer i `lyrics/`-mappen, namngivna `{spårnamn_utan_suffix}.lrc`
- Visas i `#lyrics-panel`; aktuell rad highlightas och auto-scrollas via `updateLyricsLine(currentTime)`
- **Klick på rad** anropar `seekAll(line.time)` — hoppar direkt till den tidpunkten
- **Sökfält** (`#lyrics-search`) filtrerar rader i realtid; auto-scroll pausas under sökning
- Sökning och scroll-state nollställs vid `loadLyrics()` (nytt spår)

## Öppna punkter (från NCC)
- Validering av payload-storlek i save_profile.php (DoS-skydd)
- `_msc`-suffix syns i spårnamnet i admin-dashboarden (track_label() strippar ej kanal-suffix)
- Eventuellt: omslagsbilder per album
- Eventuellt: genrer/taggar-filtrering
