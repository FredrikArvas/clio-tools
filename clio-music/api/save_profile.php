<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * api/save_profile.php — sparar inställningar för ett spår (eller globala inställningar) i användarens profil.
 *
 * Anropas av: player.js (saveSettings, saveGlobalSettings, toggleLike).
 * Kropp: {"track": "<spår-URL>" | "_settings", "settings": {...}}.
 * Svar: 200 {"ok":true}; 400 ogiltigt/okänt spår eller ogiltig inställning; 401 ej inloggad;
 *       403 CSRF; 413 för stor kropp; 500 lagringsfel.
 *
 * Säkerhetsantaganden: se api/_validation.php (vitlista, känt spår för just denna användare).
 * Användarnamnet kommer från sessionen, aldrig från kroppen, och styr filnamnet.
 */
require_once __DIR__ . '/_bootstrap.php';
require_once __DIR__ . '/_validation.php';
require_once dirname(__DIR__) . '/json_store.php';

['user' => $user, 'body' => $body] = api_bootstrap([
    'method'      => 'POST',
    'allow_guest' => false,
    'max_bytes'   => MAX_REQUEST_BYTES,
]);

$known_urls = visible_track_urls($user, $music_dir, $music_url);
$track      = $body['track'] ?? null;
[$settings, $error] = validate_profile_settings($track, $body['settings'] ?? null, $known_urls);
if ($error !== '') api_error(400, $error);

$directory = dirname(__DIR__) . '/data/profiles';
if (!is_dir($directory) && !mkdir($directory, 0750, true) && !is_dir($directory)) {
    error_log('clio_music: kan inte skapa ' . $directory);
    api_error(500, 'storage error');
}
$is_limit_hit = false;
$is_saved = json_file_update(
    $directory . '/' . basename($user['username']) . '.json',
    function (array $profiles) use ($track, $settings, &$is_limit_hit): ?array {
        if (!isset($profiles[$track]) && count($profiles) >= MAX_PROFILE_TRACKS) {
            $is_limit_hit = true;
            return null;
        }
        $profiles[$track] = $settings;
        return $profiles;
    },
    'abort',
    JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT
);
if ($is_limit_hit) api_error(400, 'too many profile entries');
if (!$is_saved) api_error(500, 'storage error');
api_respond(['ok' => true]);
