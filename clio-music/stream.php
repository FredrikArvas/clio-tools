<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * stream.php — behörighetskontrollerad leverans av ljud- och lyricsfiler.
 *
 * Anropas av: nginx, för ALLA förfrågningar på /music/* och /lyrics/* (location ^~ i
 * sajtkonfigen skickar dem hit via FastCGI). Klienten anropar aldrig stream.php direkt;
 * URL:erna är oförändrade (music/<fil>, lyrics/<fil>). Det är medvetet: profiler, spellistor,
 * kön och spelloggen använder URL:en som nyckel och fortsätter därför att fungera.
 *
 * Varför X-Accel-Redirect: PHP avgör bara VEM som får hämta filen. nginx levererar sedan
 * filen själv från en `internal` location (/_protected/music/, /_protected/lyrics/) och sköter
 * Range/seek, vilket iOS Safari kräver. Ingen fil läses av PHP.
 *
 * Säkerhetsantaganden:
 * - Filnamnet tas från den RÅA request-URI:n och måste vara ett enda sökvägssegment efter
 *   avkodning (basename() === namnet). Därmed avvisas "..", "/" och kodade "%2f" med 400.
 * - Behörighet avgörs av user_can_access_media() i access.php (samma regel som index.php).
 * - Nekad åtkomst ger 403 även för filer som finns. Vi skiljer inte 403/404 för att dölja
 *   existens: den som gissar ett filnamn vet redan namnet, och 404 för okända filer gör
 *   felsökning enklare. Avvägningen är medveten.
 * - Svaren får aldrig cachas av delade cachar (Cloudflare): Cache-Control private, no-store.
 */

require_once __DIR__ . '/auth.php';
require_once __DIR__ . '/config.php';
require_once __DIR__ . '/access.php';

const MEDIA_TYPES = [
    'music'  => ['extension' => 'mp3', 'content_type' => 'audio/mpeg'],
    'lyrics' => ['extension' => 'lrc', 'content_type' => 'text/plain; charset=utf-8'],
];

function stream_fail(int $status): never {
    http_response_code($status);
    header('Cache-Control: private, no-store');
    exit;
}

/** Tolkar request-URI:n till [katalognamn, filnamn] eller avbryter med 400. */
function parse_media_request(string $request_uri): array {
    $path = strtok($request_uri, '?');
    if (!preg_match('#^/(music|lyrics)/([^/]+)$#', $path, $match)) stream_fail(400);
    [$directory, $filename] = [$match[1], rawurldecode($match[2])];
    $extension = MEDIA_TYPES[$directory]['extension'];
    $is_plain_name = $filename === basename($filename)
        && !str_contains($filename, "\0")
        && !str_starts_with($filename, '.');
    if (!$is_plain_name || !preg_match('/\.' . $extension . '$/i', $filename)) stream_fail(400);
    return [$directory, $filename];
}

if (!in_array($_SERVER['REQUEST_METHOD'], ['GET', 'HEAD'], true)) stream_fail(405);

[$directory, $filename] = parse_media_request($_SERVER['REQUEST_URI'] ?? '');

$user = current_user_or_guest();
// Släpp sessionslåset direkt: spelaren hämtar upp till fyra kanaler parallellt, och PHP:s
// fil-lås på sessionen skulle annars köa dem efter varandra.
session_write_close();

$real_directory = realpath(__DIR__ . '/' . $directory);
$real_file      = realpath(__DIR__ . '/' . $directory . '/' . $filename);
if ($real_directory === false || $real_file === false || dirname($real_file) !== $real_directory || !is_file($real_file)) {
    stream_fail(404);
}

if (!user_can_access_media($filename, $user, $music_dir)) stream_fail(403);

header('Content-Type: ' . MEDIA_TYPES[$directory]['content_type']);
header('Cache-Control: private, no-store');
header('Vary: Cookie');
header('X-Accel-Redirect: /_protected/' . $directory . '/' . rawurlencode($filename));
