<?php
$music_dir   = __DIR__ . '/music';
$music_url   = 'music';
$site_title  = 'Clio Music';
define('APP_VERSION', '1.5.3');
$lyrics_url = 'lyrics';
define('GUEST_GROUP',  'Gäst');

// Tillåtna gruppnamn (admin/groups_store.php). Vitlista, inte svartlista: bara bokstaver, siffror,
// mellanslag, understreck och bindestreck. Därmed kan varken CSV-avgränsare (; |), radbrytningar
// eller citattecken nå data/users.csv eller data/track_groups.csv.
// D-flaggan behövs: utan den släpper "$" igenom ett avslutande radbrytningstecken.
const GROUP_NAME_PATTERN = '/^[\p{L}\p{N} _\-]{1,40}$/uD';

// ── Gränser för JSON-API:erna (api/) ──────────────────────────────────────────
// Alla gränser avvisar med tydligt felmeddelande (413 för för stor kropp, annars 400).
const MAX_REQUEST_BYTES        = 65536;   // kropp till save_profile/save_playlist
const MAX_LOG_PLAY_BYTES       = 1024;    // kropp till log_play (bara en spår-URL)
const MAX_PROFILE_TRACKS       = 1000;    // poster per användarprofil (spår + _settings)
const MAX_QUEUE_LENGTH         = 500;     // poster i den sparade kön
const MAX_PLAYLISTS_PER_USER   = 100;
const MAX_TRACKS_PER_PLAYLIST  = 500;
const MAX_PLAYLIST_NAME_LENGTH = 100;     // byte
const MAX_TRACK_URL_LENGTH     = 300;     // tecken i en spår-URL (music/<fil>)
// Spelningslogg: högst så många loggade spelningar per minut (fast fönster).
const LOG_PLAY_GUEST_MAX_PER_MINUTE = 10;   // per IP; gäster har ingen egen identitet
const LOG_PLAY_USER_MAX_PER_MINUTE  = 60;   // per inloggad användare
