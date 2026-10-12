<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * api/log_play.php — loggar en spelning (efter 5 s uppspelning) till data/plays.jsonl.
 *
 * Anropas av: player.js (logPlay). Gäster får logga, men med hastighetsgräns per IP.
 * Kropp: {"track": "<spår-URL>"}. Loggraden innehåller bara user, track och ts.
 * Svar: 200 {"ok":true}; 400 okänt/ogiltigt spår; 403 CSRF; 413 för stor kropp;
 *       429 för många spelningar per minut (med Retry-After); 500 lagringsfel.
 *
 * Säkerhetsantaganden:
 * - Hastighetsgränsen räknas före valideringen, så även felaktiga anrop räknas mot gränsen.
 * - Sessionen är stängd efter api_bootstrap, så gäster räknas per klient-IP (client_ip.php),
 *   inloggade per användarnamn.
 * - Spåret måste vara ett som användaren själv får se (api/_validation.php).
 */
require_once __DIR__ . '/_bootstrap.php';
require_once __DIR__ . '/_validation.php';
require_once dirname(__DIR__) . '/rate_limit.php';

['user' => $user, 'body' => $body] = api_bootstrap([
    'method'      => 'POST',
    'allow_guest' => true,
    'max_bytes'   => MAX_LOG_PLAY_BYTES,
]);

$retry_after = is_guest($user)
    ? rate_limit_hit('log_play_guest', client_ip(), LOG_PLAY_GUEST_MAX_PER_MINUTE, 60)
    : rate_limit_hit('log_play_user', $user['username'], LOG_PLAY_USER_MAX_PER_MINUTE, 60);
if ($retry_after > 0) {
    header('Retry-After: ' . $retry_after);
    api_error(429, 'too many requests');
}

[$track, $error] = validate_known_track($body['track'] ?? null, visible_track_urls($user, $music_dir, $music_url));
if ($error !== '') api_error(400, $error);

$entry = json_encode(['user' => $user['username'], 'track' => $track, 'ts' => time()], JSON_UNESCAPED_UNICODE) . "\n";
if (file_put_contents(dirname(__DIR__) . '/data/plays.jsonl', $entry, FILE_APPEND | LOCK_EX) === false) {
    error_log('clio_music: kunde inte skriva data/plays.jsonl');
    api_error(500, 'storage error');
}
api_respond(['ok' => true]);
