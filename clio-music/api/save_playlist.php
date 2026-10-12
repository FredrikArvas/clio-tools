<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * api/save_playlist.php — skapar, ersätter eller tar bort en spellista i användarens fil.
 *
 * Anropas av: player.js (savePlPlaylist, deletePlaylist).
 * Kropp: {"name": "...", "tracks": ["<spår-URL>", ...]} eller {"name": "...", "delete": true}.
 * Svar: 200 {"ok":true}; 400 ogiltigt namn/format eller för många spellistor/spår; 401 ej inloggad;
 *       403 CSRF; 413 för stor kropp; 500 lagringsfel.
 *
 * Säkerhetsantaganden: se api/_validation.php. Okända spår filtreras bort ur listan.
 * Användarnamnet kommer från sessionen och styr filnamnet.
 */
require_once __DIR__ . '/_bootstrap.php';
require_once __DIR__ . '/_validation.php';
require_once dirname(__DIR__) . '/json_store.php';

['user' => $user, 'body' => $body] = api_bootstrap([
    'method'      => 'POST',
    'allow_guest' => false,
    'max_bytes'   => MAX_REQUEST_BYTES,
]);

[$name, $error] = validate_playlist_name($body['name'] ?? null);
if ($error !== '') api_error(400, $error);

$is_delete = !empty($body['delete']);
$tracks    = [];
if (!$is_delete) {
    $known_urls = visible_track_urls($user, $music_dir, $music_url);
    [$tracks, $error] = validate_playlist_tracks($body['tracks'] ?? null, $known_urls);
    if ($error !== '') api_error(400, $error);
}

$directory = dirname(__DIR__) . '/data/playlists';
if (!is_dir($directory) && !mkdir($directory, 0775, true) && !is_dir($directory)) {
    error_log('clio_music: kan inte skapa ' . $directory);
    api_error(500, 'storage error');
}
$is_limit_hit = false;
$is_saved = json_file_update(
    $directory . '/' . basename($user['username']) . '.json',
    function (array $playlists) use ($name, $tracks, $is_delete, &$is_limit_hit): array {
        if ($is_delete) {
            unset($playlists[$name]);
        } elseif (!isset($playlists[$name]) && count($playlists) >= MAX_PLAYLISTS_PER_USER) {
            $is_limit_hit = true;
        } else {
            $playlists[$name] = $tracks;
        }
        return $playlists;
    },
    'abort',
    JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT
);
if ($is_limit_hit) api_error(400, 'too many playlists');
if (!$is_saved) api_error(500, 'storage error');
api_respond(['ok' => true]);
