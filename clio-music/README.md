# clio_music — Meditationsmusikspelare

Inloggningsskyddad webbspelare för meditationsljud, byggd för Miranon Media / Roger Gottardsson. Stödjer upp till fyra parallella ljudkanaler per spår (musik, binauralt, röst, miljö) med individuell volymkontroll och EQ.

**Live:** https://audio.arvas.international

## Funktioner

- 4-kanals Web Audio API-mixer (musik, binauralt, röst, miljö)
- Kollapsibara album-sektioner med ▶ Spela alla
- Kö med drag-and-drop-omsortering, sparas server-side
- Spellistor — namngivna, permanenta listor sparade per användare
- Serverside ljudprofiler (volym, EQ, balans, hastighet) per spår och användare
- Uppspelningslägen: repetera låt, repetera lista, slumpa
- Hastighetsreglage 0.5×–2.0×
- Användargrupper styr vilka låtar varje användare ser
- Spelningslogg (plays.jsonl)
- Admin-dashboard med statistik per låt och användare

## Teknisk stack

- PHP 8.3-FPM + nginx
- Vanilla JS + Web Audio API
- Inga ramverk, inga npm-beroenden
- Cloudflare framför (cache-bust via `?v=APP_VERSION`)

## Filstruktur

```
index.php           Spellista + 4-kanals spelare
auth.php            Session, bcrypt-login, grupper
config.php          $music_dir, $music_url, $site_title, APP_VERSION
player.js           Web Audio API mixer
style.css           Blått tema, CSS-variabler
help.php            Användarmanual
help_admin.php      Adminmanual (kräver admin-flagga)

api/
  log_play.php      POST → data/plays.jsonl
  save_profile.php  POST {track, settings} → data/profiles/{user}.json
  load_profiles.php GET  → alla inställningar för inloggad användare
  save_playlist.php POST {name, tracks} / {name, delete:true}
  load_playlists.php GET → spellistor för inloggad användare

admin/
  index.php         Dashboard: spelningar per låt/användare
  groups.php        Hantera användare↔grupper och låtar↔grupper

data/
  users.csv         Användare (git-ignorerad)
  plays.jsonl       Spelningslogg, append-only (git-ignorerad)
  track_groups.csv  Låt-grupptillhörighet
  profiles/         Ljudprofiler per användare (git-ignorerad)
  playlists/        Spellistor per användare (git-ignorerad)
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

```bash
# PHP/JS/CSS
scp -r auth.php config.php index.php login.php logout.php help.php help_admin.php \
    player.js style.css api admin \
    clioadmin@100.107.127.104:/var/www/clio_music/

# Grupptillhörighet
scp data/track_groups.csv clioadmin@100.107.127.104:/var/www/clio_music/data/

# Musik
scp music/*.mp3 clioadmin@100.107.127.104:/var/www/clio_music/music/
```

Mappen `data/playlists/` skapas automatiskt vid första sparning. Kontrollera att `data/profiles/` och `data/playlists/` ägs av `clioadmin:www-data` med `chmod 775`.
