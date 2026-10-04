# clio_music — CLAUDE.md

PHP-baserad musikspelare för meditationskurser (Miranon Media / Roger Gottardsson).
Deployad på EliteDeskGPU, tillgänglig via https://audio.arvas.international

## Stack
- PHP 8.3-FPM + nginx (port 8091 på servern)
- Vanilla JS + Web Audio API
- Inga ramverk, inga npm-beroenden

## Filstruktur
```
index.php          Spellista + 4-kanals spelare
auth.php           Session, bcrypt-login, grupper
config.php         $music_dir, $music_url, $site_title
login.php          Inloggningsformulär
logout.php         session_destroy
player.js          Web Audio API mixer (4 kanaler)
style.css          Mörkt tema, CSS-variabler
help.php           Hjälpsida (admindel dold för vanliga användare)

api/
  log_play.php     POST-endpoint för spelningslogg → data/plays.jsonl

admin/
  index.php        Dashboard: spelningar per låt/användare
  groups.php       Hantera användare↔grupper och låtar↔grupper
  hash_tool.php    Generera bcrypt-hash (ta bort efter användning)

data/
  users.csv        Användare (git-ignorerad)
  plays.jsonl      Spelningslogg, append-only (git-ignorerad)
  track_groups.csv Låt-grupptillhörighet (prefixmatchning)
  .htaccess        Deny from all

music/             MP3-filer (git-ignorerade)
```

## 4-kanals ljudmodell
Varje meditation kan ha upp till fyra filer med samma basnamn:

| Suffix | Kanal     | Web Audio-kedja                  |
|--------|-----------|----------------------------------|
| `_msc` | Musik     | Gain → Pan → Bas → Diskant → ut  |
| `_bin` | Binauralt | Gain → ut (stereo bevaras)       |
| `_vce` | Röst      | Gain → ut                        |
| `_env` | Miljö     | Gain → ut                        |

Exempel: `001_djup-avslappning_msc.mp3`, `001_djup-avslappning_bin.mp3`

Filer utan suffix visas som fristående musikspår (bakåtkompatibelt).
`_bin`/`_vce`/`_env`-filer filtreras bort från spellistan.

## Användarhantering
`data/users.csv` — semicolonseparerat, **inte** komma (namn kan innehålla komma).
Format: `användarnamn;bcrypt_hash;Visningsnamn;aktiv;admin;Grupp1|Grupp2`

Generera hash: öppna `admin/hash_tool.php` i webbläsaren (ta bort efteråt).

## Grupper
- Grupper definieras implicit ur users.csv + track_groups.csv
- Användare i gruppen **Alla** ser alltid alla låtar
- Admin-flagga (kolumn 5) ger åtkomst till admin/ och all musik
- GUI: `admin/groups.php` — kryssrutor för användare, radioknappar för låtar

## Deploy
```bash
# Uppdatera PHP/JS/CSS-filer
scp -r auth.php config.php index.php login.php logout.php help.php \
    player.js style.css api admin \
    clioadmin@100.107.127.104:/var/www/clio_music/

# Uppdatera datafiler
scp data/track_groups.csv clioadmin@100.107.127.104:/var/www/clio_music/data/

# Ladda upp musik
scp music/*.mp3 clioadmin@100.107.127.104:/var/www/clio_music/music/
```

## Spelningslogg
`data/plays.jsonl` — en JSON-rad per spelning:
```json
{"user":"roger","track":"music/001_meditation_msc.mp3","ts":1728000000}
```
Spelning räknas efter 5 sekunders sammanhängande uppspelning.
