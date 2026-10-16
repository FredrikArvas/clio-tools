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
 * - Cachning (v1.8.0): gästspår (grupp GUEST_GROUP) är publika och får cachas av Cloudflare
 *   (public, max-age=604800). Övriga filer cachas bara i webbläsaren (private, max-age=604800,
 *   Vary: Cookie) och delas aldrig av CDN:en. Fel och nekade svar: private, no-store.
 *   Medveten avvägning: flyttas ett gästspår till en annan grupp kan Cloudflare leverera det
 *   upp till en vecka till — purga då filen i Cloudflare.
 */

require_once __DIR__ . '/auth.php';
require_once __DIR__ . '/config.php';
require_once __DIR__ . '/access.php';

const MEDIA_TYPES = [
    'music'  => [
        'extensions'   => ['mp3', 'm4a'],
        'content_types' => ['mp3' => 'audio/mpeg', 'm4a' => 'audio/mp4'],
    ],
    'lyrics' => [
        'extensions'    => ['lrc'],
        'content_types' => ['lrc' => 'text/plain; charset=utf-8'],
    ],
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
    $extensions = MEDIA_TYPES[$directory]['extensions'];
    $ext_pattern = implode('|', array_map('preg_quote', $extensions, array_fill(0, count($extensions), '/')));
    $is_plain_name = $filename === basename($filename)
        && !str_contains($filename, "\0")
        && !str_starts_with($filename, '.');
    if (!$is_plain_name || !preg_match('/\.(' . $ext_pattern . ')$/i', $filename)) stream_fail(400);
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

$ext         = strtolower(pathinfo($filename, PATHINFO_EXTENSION));
$content_type = MEDIA_TYPES[$directory]['content_types'][$ext] ?? 'application/octet-stream';

// Gäst-tillgängliga filer (grupp = GUEST_GROUP) är publika: Cloudflare och webbläsare får
// cacha dem i en vecka. Övriga filer cachas bara lokalt i webbläsaren (private) — CDN:en
// delar dem aldrig. Vary: Cookie behövs inte för publika filer eftersom alla får samma svar.
$track_group = ($directory === 'music')
    ? track_group($filename, load_track_groups())
    : '';
$is_public = ($track_group === GUEST_GROUP);
if ($is_public) {
    header('Cache-Control: public, max-age=604800');
} else {
    header('Cache-Control: private, max-age=604800');
    header('Vary: Cookie');
}

header('Content-Type: ' . $content_type);
header('X-Accel-Redirect: /_protected/' . $directory . '/' . rawurlencode($filename));
