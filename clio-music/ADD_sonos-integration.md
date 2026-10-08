# ADD — Sonos Cloud API-integration för clio-music

**Status:** Planerad, ej påbörjad  
**Datum:** 2026-10-08  
**Författare:** Fredrik Arvas / Clio  
**Valt alternativ:** Alt B — Sonos Cloud API (OAuth 2.0)

---

## Bakgrund

clio-music är en PHP-baserad meditationsspelare för Miranon Media, körd på
`https://audio.arvas.international`. Idag spelas ljud enbart i webbläsaren
via Web Audio API. Behovet är att kunna skicka uppspelning till Sonos-högtalare
i rummet utan att lämna spelaren.

---

## Valt alternativ

**Sonos Cloud API v1** — officiellt REST-API med OAuth 2.0.

### Varför inte Alt A (lokal UPnP)?
Fungerar bara om Sonos-högtalarna är på samma LAN som EliteDesk GPU.
Inte garanterat för alla användare.

### Varför inte Alt C (klistrad URL)?
Klumpig användarupplevelse. Kräver att användaren lämnar spelaren och manuellt
hanterar Sonos-appen.

---

## Flödesöversikt

```
Användaren klickar "Spela på Sonos"
    ↓
[1] OAuth: redirect till Sonos login (om ej autentiserad)
    ↓
[2] Sonos returnerar access_token → sparas i PHP-session
    ↓
[3] Player hämtar Sonos-hushåll och grupper via API
    ↓
[4] Användaren väljer grupp (högtalare)
    ↓
[5] Player genererar signerad stream-URL (HMAC, tidsbegränsad)
    ↓
[6] PHP anropar POST /v1/groups/{groupId}/playback/audioClip
    ↓
[7] Sonos streamer ljud direkt från Cloudflare-URL
```

---

## Nya komponenter

### `sonos_auth.php`
Hanterar OAuth 2.0-flödet mot `https://api.sonos.com/login/v3/oauth`.

- `GET /sonos_auth.php?action=login` — redirect till Sonos
- `GET /sonos_auth.php?action=callback` — tar emot code, byter mot token
- `GET /sonos_auth.php?action=logout` — rensar token ur session
- Lagrar `access_token`, `refresh_token`, `expires_at` i PHP-session
- Token refresh sker automatiskt om `expires_at` passerat

### `api/sonos_groups.php`
Returnerar användarens Sonos-hushåll och grupper som JSON.

```json
{
  "groups": [
    { "id": "...", "name": "Vardagsrum", "playerNames": ["PLAY:5"] }
  ]
}
```

### `api/sonos_play.php`
Tar emot `{ groupId, trackUrl, trackName }`, genererar signerad URL,
anropar Sonos Cloud API.

### `api/stream.php` — ny autentiserad ström-endpoint
Ersätter direkt filservering för Sonos. Sonos kan inte använda PHP-sessioner,
så vi behöver token-baserad auth.

**URL-format:** `https://audio.arvas.international/stream.php?t=HMAC_TOKEN&f=SPÅRFILNAMN`

- Token = `HMAC-SHA256(secret_key, filnamn + "|" + expiry_unix_timestamp)`
- Expiry: 4 timmar (täcker en hel lyssningssession)
- PHP validerar token och expiry, sedan `readfile()` med rätt `Content-Type`
- `secret_key` lagras i `.env` som `STREAM_HMAC_KEY`

---

## API-integration — Sonos Cloud API v1

### Registrering
1. Skapa konto på [Sonos Developer Portal](https://developer.sonos.com)
2. Skapa ny integration — välj "Playback" scope
3. Sätt Redirect URI: `https://audio.arvas.international/sonos_auth.php?action=callback`
4. Spara `SONOS_CLIENT_ID` och `SONOS_CLIENT_SECRET` i `.env`

### Relevanta endpoints

| Ändamål | Endpoint |
|---|---|
| Hämta hushåll | `GET /v1/households` |
| Hämta grupper | `GET /v1/households/{id}/groups` |
| Spela audio clip | `POST /v1/groups/{id}/playback/audioClip` |
| Pausa | `POST /v1/groups/{id}/playback/pause` |
| Volym | `POST /v1/groups/{id}/groupVolume/relative` |

### `audioClip`-payload
```json
{
  "name": "Spårnamn",
  "appId": "international.arvas.audio",
  "streamUrl": "https://audio.arvas.international/stream.php?t=...&f=...",
  "volume": 30,
  "clipType": "LONG_LIVED_AUDIO"
}
```

`LONG_LIVED_AUDIO` pausar nuvarande uppspelning och spelar klippet. Alternativet
`SHORT_LIVED_AUDIO` lämpar sig för korta notifikationer.

---

## Klientside-förändringar (player.js)

### Ny "Spela på Sonos"-knapp
Visas bredvid play-knappen. Grå om ej Sonos-autentiserad, aktiv annars.

```
[ ▶ Play ]  [ 🔊 Sonos ▾ ]
                ├─ Vardagsrum
                ├─ Sovrum
                └─ Koppla Sonos-konto...
```

- Dropdown hämtar grupper via `api/sonos_groups.php`
- Vald grupp sparas i `localStorage` som `clio_sonos_group`
- Vid spårval: POST till `api/sonos_play.php` → Sonos börjar spela

### Statusindikator
Liten ikon i spårkortet visar om spåret spelas på Sonos (pollas via
`GET /v1/groups/{id}/playback` var 5:e sek).

---

## Säkerhet

| Risk | Åtgärd |
|---|---|
| Signerad URL läcker | Kort expiry (4h), HMAC-validering |
| Token i PHP-session stjäls | `session.cookie_secure = On`, `session.cookie_httponly = On` |
| SONOS_CLIENT_SECRET exponeras | Lagras i `.env`, aldrig i frontend |
| Stream-endpoint missbrukas | Rate limit på nginx (10 req/s per IP) |
| Sonos API-nyckel roteras | Refresh-token-flöde hanterar detta automatiskt |

---

## Konfiguration (.env)
```
SONOS_CLIENT_ID=xxx
SONOS_CLIENT_SECRET=xxx
STREAM_HMAC_KEY=<64-tecken random hex>
```

---

## Filer att skapa/ändra

| Fil | Ändring |
|---|---|
| `sonos_auth.php` | Ny — OAuth-flöde |
| `api/sonos_groups.php` | Ny — hämta grupper |
| `api/sonos_play.php` | Ny — starta uppspelning |
| `api/stream.php` | Ny — token-autentiserad ström |
| `player.js` | Ny Sonos-dropdown + statuspolling |
| `style.css` | Sonos-knapp, dropdown-styling |
| `config.php` | Läs SONOS_* från .env |
| `.env.example` | Lägg till SONOS_* och STREAM_HMAC_KEY |
| `config.php` | Bumpa APP_VERSION vid deploy |

---

## Öppna frågor inför implementation

1. Ska Sonos-kopplingen vara per användare (session) eller global (admin konfigurerar ett konto)?
2. Ska `audioClip` ta över Sonos helt (`LONG_LIVED_AUDIO`) eller bara lägga till som overlay?
3. Behöver vi stödja köhantering på Sonos-sidan, eller räcker "spela detta nu"?
4. Ska volymkontroll exponeras i spelaren eller hanteras i Sonos-appen?

---

## Resurser

- [Sonos Cloud API docs](https://developer.sonos.com/reference/control-api/)
- [Sonos OAuth 2.0 guide](https://developer.sonos.com/build/direct-control/authorize/)
- [audioClip reference](https://developer.sonos.com/reference/control-api/audioclip/)
