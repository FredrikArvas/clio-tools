# CLAUDE.md — clio_music

Kontext för LLM-assistenter som arbetar med detta projekt.

## Vad projektet är

PHP-baserad musikspelare för meditationsljud (Miranon Media / Roger Gottardsson). Inloggningsskyddad, inga ramverk, inga npm-beroenden. Körs på EliteDesk GPU bakom Cloudflare på https://audio.arvas.international.

## Regler och konventioner

- **Inga ramverk.** Vanilla JS + Web Audio API på klientsidan. PHP utan Composer.
- **Inga hårdkodade URL:er.** Använd `$music_url` från config.php.
- **APP_VERSION** i config.php ska bumpa vid varje deploy — används för Cloudflare cache-bust på player.js.
- **data/-mappen är känslig.** users.csv, plays.jsonl, profiles/ och playlists/ är git-ignorerade och innehåller riktiga användardata.
- **Bcrypt** för lösenord, aldrig klartext. admin/hash_tool.php finns för att generera hash — ta bort efter användning.
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
