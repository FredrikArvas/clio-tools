# clio_music — Meditationsmusikspelare

Inloggningsskyddad webbspelare för meditationsljud, byggd för Miranon Media / Roger Gottardsson. Stödjer upp till fyra parallella ljudkanaler per spår (musik, binauralt, röst, miljö) med individuell volymkontroll och EQ.

**Live:** https://audio.arvas.international (version: `APP_VERSION` i `config.php`)

## Funktioner

- 4-kanals Web Audio API-mixer (musik, binauralt, röst, miljö)
- Kollapsibara album-sektioner med ▶ Spela alla
- Kö med drag-and-drop-omsortering, sparas server-side
- Spellistor: namngivna, permanenta listor sparade per användare
- Serverside ljudprofiler (volym, EQ, balans, hastighet) per spår och användare
- Uppspelningslägen: repetera låt, repetera lista, slumpa
- Hastighetsreglage 0.5×–2.0×
- Användargrupper styr vilka låtar varje användare ser
- Spelningslogg (`data/plays.jsonl`) och admin-dashboard med statistik per låt och användare
- Skyddad medialeverans: ljudfiler och lyrics går via behörighetskontroll (se SECURITY.md)

## Teknisk stack

- PHP 8.3-FPM + nginx (lyssnar bara på 127.0.0.1:8091, bakom cloudflared och Cloudflare)
- Vanilla JS + Web Audio API, inga ramverk, inga npm-beroenden
- Servern saknar `mbstring`; använd inte `mb_*`

## Filstruktur

```
Sidor
  index.php            Spellista + 4-kanals spelare (TRACKS injiceras som JSON-block)
  login.php            Inloggning (login_throttle, CSRF)
  logout.php           Utloggning (POST + CSRF)
  help.php             Användarmanual
  help_admin.php       Adminmanual (kräver admin-flagga)
  stream.php           Medialeverans: behörighet, sedan X-Accel-Redirect till nginx
  consent.js           Cookie-/GA-samtycke och banner

Kärnlogik (PHP)
  auth.php             Sessioner (start_session), bcrypt-login, current_user(), grupper
  access.php           Spårgrupper och åtkomst (enda källan: track_group, user_can_see, list_visible_tracks)
  csrf.php             CSRF-token, csrf_field(), csrf_require(), logout_button()
  audit.php            audit_log() till data/audit.jsonl (hemligheter filtreras bort)
  client_ip.php        client_ip(), request_is_https(); proxy-headers litas bara på från loopback
  login_throttle.php   Inloggningsspärr per användarnamn och IP
  rate_limit.php       rate_limit_hit(): fast fönster för API-anrop
  json_store.php       json_file_update() / json_file_read(): flock-skyddad JSON-lagring
  config.php           Konstanter (GROUP_NAME_PATTERN, MAX_*, LOG_PLAY_*), APP_VERSION
  player.js            Web Audio API-mixer och klient-API (apiPost, API_HEADERS)
  style.css            Blått tema, CSS-variabler

api/                   JSON-API (alla använder api/_bootstrap.php)
  _bootstrap.php       api_bootstrap(): metod, inloggning, CSRF, JSON, storlek
  _validation.php      Vitlistad validering av profiler, spellistor och kö
  log_play.php         POST → data/plays.jsonl
  save_profile.php     POST {track, settings} → data/profiles/{user}.json
  load_profiles.php    GET  → alla inställningar för inloggad användare
  save_playlist.php    POST {name, tracks} / {name, delete:true}
  load_playlists.php   GET  → spellistor för inloggad användare

admin/
  index.php            Dashboard: spelningar per låt/användare
  groups.php           Vy och formulär: användare↔grupper, låtar↔grupper
  groups_store.php     Dataskiktet för grupper (inga bieffekter, testas med fixtures)

data/                  Körtidsdata, ägs av servern (se CLAUDE.md, "Filrättigheter")
  track_groups.csv     Låt-grupptillhörighet (versionshanterad)
  users.csv            Användare (git-ignorerad, aldrig i repot)
  plays.jsonl          Spelningslogg, append-only (git-ignorerad)
  audit.jsonl          Säkerhetsaudit (git-ignorerad)
  profiles/            Ljudprofiler per användare (git-ignorerad)
  playlists/           Spellistor per användare (git-ignorerad)
  login_attempts/      Inloggningsräknare (git-ignorerad)
  rate_limits/         API-räknare (git-ignorerad)

deploy/                Källa för nginx och logrotate (installeras i /etc, inte i webroten)
  nginx_clio_music.conf          → /etc/nginx/sites-available/clio_music
  clio_music_security_headers.conf → /etc/nginx/snippets/
  clio_music_csp.conf            → /etc/nginx/snippets/ (CSP i enforcing-läge)
  logrotate_clio_music           → /etc/logrotate.d/clio_music

tests/                 Körs på servern från webroten (/tests/ nekas av nginx)
  security_smoke.sh    Säkerhetsrök mot 127.0.0.1:8091 (kräver sudo)
  api_validation_test.php   Enhetstest för api/_validation.php
  groups_store_test.php     Test av admin/groups_store.php mot fixture-filer

lyrics/                LRC-filer, namngivna {spårnamn}.lrc
music/                 Ljudfiler (git-ignorerad, laddas upp separat)
```

## 4-kanalsnamngivning

Spår med flera kanaler exporteras med identisk bas och suffix:

```
001-Djup-Avslappning_msc.mp3   ← musik (master)
001-Djup-Avslappning_bin.mp3   ← binauralt
001-Djup-Avslappning_vce.mp3   ← röst
001-Djup-Avslappning_env.mp3   ← miljö
```

Spelaren känner igen gruppen automatiskt. Metadata läses från `_msc`-filen.

## Deploy

Ändringar förbereds först i en staging-katalog på servern och rullas sedan ut av ett skript. Skripten ligger i `~/staging/clio_music_<sprint>/` och versioneras inte i repot.

```bash
# 1. Kopiera filerna till staging (från arbetskopian)
scp <ändrade filer> clioadmin@100.107.127.104:~/staging/clio_music_<sprint>/

# 2. På servern: deploy-skriptet tar backup, kopierar till /var/www/clio_music/,
#    validerar nginx om den ändrats och kör tests/security_smoke.sh
ssh clioadmin@100.107.127.104 'bash ~/staging/clio_music_<sprint>/deploy.sh'

# Rollback: rollback.sh i samma katalog (återställer från ~/backups/)
```

**Musik:** `scp music/*.mp3 clioadmin@100.107.127.104:/var/www/clio_music/music/`

**Grupptillhörighet:** `data/track_groups.csv` skrivs av admin-gränssnittet. Kopiera inte över den från repot med scp; den ägs av `www-data` (640) och kan inte skrivas av `clioadmin`.

Efter deploy: kontrollera att uppspelning, sparning av profil och admin-sparning av grupper fungerar.
