<?php
/**
 * api/_validation.php — validering av innehållet i API-anropen (profil, spellista, spelningslogg).
 *
 * Anropas av: api/save_profile.php, api/save_playlist.php, api/log_play.php och
 * tests/api_validation_test.php. Filen har inga bieffekter (ingen utskrift, ingen session), så
 * den testas med php CLI.
 *
 * Säkerhetsantaganden:
 * - "Känt spår" betyder ett spår som just den användaren får se (visible_track_urls i access.php):
 *   osynliga och påhittade spår avvisas lika. Det hindrar att profiler och loggar fylls med
 *   godtyckliga strängar och att spårnamn läcks via spelloggen.
 * - Inställningar valideras mot en vitlista av nycklar med typ och intervall (samma intervall som
 *   reglagen i index.php). Okända nycklar kastas tyst, så att äldre klienter och äldre sparade
 *   profiler fortsätter fungera; värden utanför intervallet avvisas.
 * - Listor (kö, spellistor) filtreras mot kända spår i stället för att avvisas helt, eftersom ett
 *   spår kan ha tagits bort eller bytt grupp sedan listan sparades.
 *
 * Konvention: valideringsfunktionerna returnerar [värde, felmeddelande]; tomt felmeddelande = ok.
 */

require_once dirname(__DIR__) . '/config.php';
require_once dirname(__DIR__) . '/access.php';

const GLOBAL_SETTINGS_KEY = '_settings';   // profilnyckel för uppspelningsläge, hastighet och kö
const PLAY_MODES          = ['none', 'repeat-one', 'repeat-all', 'shuffle'];
// Intervall per spårinställning; speglar min/max på reglagen i index.php.
const TRACK_SETTING_RANGES = [
    'msc' => [0.0, 1.0], 'bin' => [0.0, 1.0], 'vce' => [0.0, 1.0], 'env' => [0.0, 1.0],
    'balance' => [-1.0, 1.0], 'bass' => [-12.0, 12.0], 'treble' => [-12.0, 12.0],
];
const PLAYBACK_RATE_RANGE = [0.5, 2.0];

/** Är värdet ett ändligt JSON-tal (inte sträng, bool eller null) inom intervallet? */
function is_number_in_range(mixed $value, float $min, float $max): bool {
    return (is_int($value) || is_float($value)) && is_finite((float)$value) && $value >= $min && $value <= $max;
}

/** Behåller bara strängar som är kända spår-URL:er (set från visible_track_urls), i ursprunglig ordning. */
function filter_known_tracks(array $urls, array $known_urls): array {
    $kept = [];
    foreach ($urls as $url) {
        if (is_string($url) && isset($known_urls[$url])) $kept[] = $url;
    }
    return $kept;
}

/** Ett spår som måste vara känt (log_play, save_profile). Returnerar [url, fel]. */
function validate_known_track(mixed $track, array $known_urls): array {
    if (!is_string($track) || $track === '' || strlen($track) > MAX_TRACK_URL_LENGTH) return ['', 'invalid track'];
    if (!isset($known_urls[$track])) return ['', 'unknown track'];
    return [$track, ''];
}

// ── Profil ────────────────────────────────────────────────────────────────────

/**
 * Validerar ett save_profile-anrop. $track är antingen '_settings' eller ett känt spår.
 * Returnerar [rensade inställningar, fel].
 */
function validate_profile_settings(mixed $track, mixed $settings, array $known_urls): array {
    if (!is_array($settings)) return [[], 'invalid settings'];
    if ($track === GLOBAL_SETTINGS_KEY) return clean_global_settings($settings, $known_urls);
    [, $error] = validate_known_track($track, $known_urls);
    return $error !== '' ? [[], $error] : clean_track_settings($settings);
}

/** Spårinställningar: volymer, balans, bas/diskant och 'liked'. Okända nycklar kastas. */
function clean_track_settings(array $settings): array {
    $clean = [];
    foreach (TRACK_SETTING_RANGES as $key => [$min, $max]) {
        if (!array_key_exists($key, $settings)) continue;
        if (!is_number_in_range($settings[$key], $min, $max)) return [[], 'invalid setting: ' . $key];
        $clean[$key] = $settings[$key];
    }
    if (array_key_exists('liked', $settings)) {
        if (!is_bool($settings['liked'])) return [[], 'invalid setting: liked'];
        $clean['liked'] = $settings['liked'];
    }
    return [$clean, ''];
}

/** Globala inställningar: uppspelningsläge, hastighet, kö och köposition. Kön filtreras mot kända spår. */
function clean_global_settings(array $settings, array $known_urls): array {
    $clean = [];
    if (array_key_exists('playMode', $settings)) {
        if (!in_array($settings['playMode'], PLAY_MODES, true)) return [[], 'invalid setting: playMode'];
        $clean['playMode'] = $settings['playMode'];
    }
    if (array_key_exists('playbackRate', $settings)) {
        if (!is_number_in_range($settings['playbackRate'], PLAYBACK_RATE_RANGE[0], PLAYBACK_RATE_RANGE[1])) {
            return [[], 'invalid setting: playbackRate'];
        }
        $clean['playbackRate'] = $settings['playbackRate'];
    }
    if (array_key_exists('queue', $settings)) {
        if (!is_array($settings['queue']) || count($settings['queue']) > MAX_QUEUE_LENGTH) return [[], 'invalid setting: queue'];
        $clean['queue'] = filter_known_tracks($settings['queue'], $known_urls);
    }
    if (array_key_exists('queueCursor', $settings)) {
        if (!is_int($settings['queueCursor']) || $settings['queueCursor'] < -1 || $settings['queueCursor'] > MAX_QUEUE_LENGTH) {
            return [[], 'invalid setting: queueCursor'];
        }
        $clean['queueCursor'] = $settings['queueCursor'];
    }
    return [$clean, ''];
}

// ── Spellistor ────────────────────────────────────────────────────────────────

/** Spellistans namn: text utan kontrolltecken, 1..MAX_PLAYLIST_NAME_LENGTH byte, giltig UTF-8. Returnerar [namn, fel]. */
function validate_playlist_name(mixed $name): array {
    if (!is_string($name) || preg_match('//u', $name) !== 1) return ['', 'invalid_name'];
    $clean = trim(preg_replace('/[\x00-\x1F\x7F]/', '', $name));
    if ($clean === '' || strlen($clean) > MAX_PLAYLIST_NAME_LENGTH) return ['', 'invalid_name'];
    return [$clean, ''];
}

/** Spellistans spår: array, högst MAX_TRACKS_PER_PLAYLIST poster; okända spår filtreras bort. Returnerar [lista, fel]. */
function validate_playlist_tracks(mixed $tracks, array $known_urls): array {
    if (!is_array($tracks)) return [[], 'invalid'];
    if (count($tracks) > MAX_TRACKS_PER_PLAYLIST) return [[], 'too many tracks'];
    return [filter_known_tracks($tracks, $known_urls), ''];
}
