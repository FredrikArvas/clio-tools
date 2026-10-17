<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * admin/upload_validation.php — validering av uppladdade ljudfiler (namn, storlek, innehåll)
 * och varningar om kanalregler.
 *
 * Anropas av: admin/upload.php och tests/upload_validation_test.php. Filen har inga bieffekter
 * (ingen utskrift, ingen session, inga skrivningar), så den testas med php CLI.
 *
 * Säkerhetsantaganden:
 * - Filnamnet blir både filnamn i music/ och nyckel i track_groups.csv. Det måste därför vara
 *   ett enda sökvägssegment, CSV-säkert (inga ; CR LF NUL, inte inledande #) och utan
 *   inledande/avslutande blanksteg: load_prefix_csv() trimmar nycklarna, och en nyckel som inte
 *   matchar det riktiga filnamnet skulle göra spåret synligt för alla inloggade.
 * - Ändelsen skrivs alltid med gemener. scan_music() globbar '*.mp3'/'*.m4a', vilket är
 *   skiftlägeskänsligt på Linux: en fil som slutar på .MP3 skulle annars aldrig synas.
 * - Innehållet avgörs av filens första byte (ID3/MPEG-ramsynk resp. 'ftyp'), aldrig av
 *   klientens $_FILES[...]['type']. finfo används dessutom när tillägget finns.
 * - Servern saknar mbstring: bara preg_* med /u, inga mb_*-funktioner.
 *
 * Konvention: valideringsfunktionerna returnerar [värde, felkod]; tom felkod = ok.
 * Felkoderna översätts till HTTP-status och svensk text via upload_error().
 */

require_once dirname(__DIR__) . '/config.php';
require_once dirname(__DIR__) . '/access.php';
require_once dirname(__DIR__) . '/channels.php';

// Felkod => [HTTP-status, meddelande på svenska].
const UPLOAD_ERRORS = [
    'not_logged_in'      => [401, 'Du är inte inloggad. Ladda om sidan och logga in igen.'],
    'forbidden'          => [403, 'Bara admin får ladda upp filer.'],
    'csrf'               => [403, 'Sidan hade gått ut. Ladda om sidan och försök igen.'],
    'method'             => [405, 'Endast POST stöds.'],
    'rate_limited'       => [429, 'För många uppladdningar. Vänta en stund och försök igen.'],
    'no_file'            => [400, 'Ingen fil skickades.'],
    'multiple_files'     => [400, 'Skicka en fil per anrop.'],
    'partial'            => [400, 'Filen kom bara fram delvis. Försök igen.'],
    'invalid_name'       => [400, 'Filnamnet är inte tillåtet (snedstreck, semikolon, kontrolltecken, inledande punkt, # eller blanksteg).'],
    'name_too_long'      => [400, 'Filnamnet är för långt.'],
    'invalid_extension'  => [415, 'Bara .mp3 och .m4a kan laddas upp.'],
    'empty_file'         => [400, 'Filen är tom.'],
    'too_large'          => [413, 'Filen är större än ' . (UPLOAD_MAX_BYTES / 1048576) . ' MB.'],
    'content_mismatch'   => [415, 'Filens innehåll stämmer inte med ändelsen.'],
    'exists'             => [409, 'En fil med samma namn finns redan. Byt namn eller ta bort den gamla via SSH.'],
    'server_error'       => [500, 'Filen kunde inte sparas på servern. Inget har ändrats.'],
];

// MIME-typer från finfo som godtas per ändelse. application/octet-stream godtas eftersom finfo
// inte alltid känner igen korta eller ovanliga filer; de magiska byten är den avgörande kontrollen.
const UPLOAD_FINFO_TYPES = [
    'mp3' => ['audio/mpeg', 'audio/mp3', 'audio/x-mp3', 'audio/x-mpeg', 'audio/mpeg3', 'application/octet-stream'],
    'm4a' => ['audio/mp4', 'audio/x-m4a', 'audio/m4a', 'video/mp4', 'audio/aac', 'application/octet-stream'],
];

const UPLOAD_MAGIC_BYTES = 16;   // så många byte läses från filens början

/** [HTTP-status, meddelande] för en felkod. Okänd kod behandlas som serverfel. */
function upload_error(string $code): array {
    return UPLOAD_ERRORS[$code] ?? UPLOAD_ERRORS['server_error'];
}

/**
 * Validerar och normaliserar filnamnet. Returnerar [filnamn med gemen ändelse, felkod].
 * $music_url behövs för längdgränsen: spårets URL (track_file_url) får inte bli längre än
 * MAX_TRACK_URL_LENGTH, annars avvisar API:erna spåret i profiler, kö och spellistor.
 */
function validate_upload_filename(string $name, string $music_url): array {
    if ($name === '' || preg_match('//u', $name) !== 1) return ['', 'invalid_name'];
    $is_plain = basename($name) === $name
        && $name[0] !== '.'
        && $name[0] !== '#'
        && $name === trim($name)
        && preg_match('#[/\\\\;]#', $name) !== 1
        && preg_match('/[\p{Cc}\p{Cf}]/u', $name) !== 1;   // kontroll- och formattecken (t.ex. RTL-override)
    if (!$is_plain) return ['', 'invalid_name'];
    if (preg_match('/^(.+)\.(' . implode('|', AUDIO_EXTENSIONS) . ')$/iD', $name, $match) !== 1) {
        return ['', 'invalid_extension'];
    }
    $normalized = $match[1] . '.' . strtolower($match[2]);
    if (strlen(track_file_url($music_url, $normalized)) > MAX_TRACK_URL_LENGTH) return ['', 'name_too_long'];
    return [$normalized, ''];
}

/** 1..UPLOAD_MAX_BYTES byte. Returnerar [antal byte, felkod]. */
function validate_upload_size(int $bytes): array {
    if ($bytes <= 0) return [0, 'empty_file'];
    if ($bytes > UPLOAD_MAX_BYTES) return [0, 'too_large'];
    return [$bytes, ''];
}

/**
 * Stämmer filens innehåll med ändelsen? Returnerar [true, ''] eller [false, felkod].
 * MP3: ID3-tagg eller en giltig MPEG-ramsynk. M4A: 'ftyp' på offset 4.
 */
function validate_upload_content(string $tmp_path, string $ext): array {
    $ext  = strtolower($ext);
    $head = is_file($tmp_path) ? file_get_contents($tmp_path, false, null, 0, UPLOAD_MAGIC_BYTES) : false;
    if ($head === false || $head === '') return [false, 'content_mismatch'];
    $is_match = match ($ext) {
        'mp3'   => is_mp3_header($head),
        'm4a'   => strlen($head) >= 8 && substr($head, 4, 4) === 'ftyp',
        default => false,
    };
    if (!$is_match) return [false, 'content_mismatch'];
    $finfo_type = detect_finfo_type($tmp_path);
    if ($finfo_type !== null && !in_array($finfo_type, UPLOAD_FINFO_TYPES[$ext], true)) {
        return [false, 'content_mismatch'];
    }
    return [true, ''];
}

/** ID3v2-tagg, eller MPEG-ramsynk (11 bitar) med giltig version, lager, bithastighet och samplingsfrekvens. */
function is_mp3_header(string $head): bool {
    if (strlen($head) >= 4 && str_starts_with($head, 'ID3') && ord($head[3]) < 0xFF) return true;
    if (strlen($head) < 4) return false;
    [$b0, $b1, $b2] = [ord($head[0]), ord($head[1]), ord($head[2])];
    $is_sync          = $b0 === 0xFF && ($b1 & 0xE0) === 0xE0;
    $is_version_valid = (($b1 >> 3) & 0x03) !== 0x01;
    $is_layer_valid   = (($b1 >> 1) & 0x03) !== 0x00;
    $is_bitrate_valid = (($b2 >> 4) & 0x0F) !== 0x0F;
    $is_rate_valid    = (($b2 >> 2) & 0x03) !== 0x03;
    return $is_sync && $is_version_valid && $is_layer_valid && $is_bitrate_valid && $is_rate_valid;
}

/** MIME-typ enligt finfo, eller null om tillägget saknas (loggas; de magiska byten avgör då ensamma). */
function detect_finfo_type(string $path): ?string {
    if (!class_exists('finfo')) {
        error_log('clio_music: fileinfo saknas — uppladdning kontrolleras bara med magiska byte');
        return null;
    }
    $type = (new finfo(FILEINFO_MIME_TYPE))->file($path);
    return is_string($type) ? $type : 'application/octet-stream';
}

// ── Varningar (avvisar inte) ──────────────────────────────────────────────────

/**
 * Grupperar filnamn som scan_music() gör: [bas => [suffix => filnamn]] för kanalfiler.
 * Används på listan över filer i music/ plus den nya filen.
 */
function group_channel_files(array $files): array {
    $channels = [];
    foreach ($files as $file) {
        if (preg_match(CHANNEL_FILE_PATTERN, $file, $match)) {
            $channels[$match[1]][strtolower($match[2])][] = $file;
        }
    }
    return $channels;
}

/**
 * Varningar om kanalregler för en ny fil, givet filerna som redan finns i music/:
 * kanalfil utan _msc-master, fler kanaler än spelaren har platser, och samma kanal i både
 * .mp3 och .m4a (bara en av dem används). Returnerar en lista med svenska meddelanden.
 */
function check_channel_rules(string $name, array $existing_files): array {
    if (preg_match(CHANNEL_FILE_PATTERN, $name, $match) !== 1) return [];
    [$base, $suffix] = [$match[1], strtolower($match[2])];
    $track    = group_channel_files(array_merge($existing_files, [$name]))[$base] ?? [];
    $warnings = [];
    if ($suffix !== '_msc' && !isset($track['_msc'])) {
        $warnings[] = "Kanalfil utan _msc-master: \"$name\" spelas som huvudspår tills \"{$base}_msc\" laddas upp.";
    }
    if (count($track) > MAX_CHANNEL_SLOTS) {
        $warnings[] = 'Spåret "' . $base . '" har nu ' . count($track) . ' kanaler. Spelaren har '
            . MAX_CHANNEL_SLOTS . ' platser; resten spelas inte.';
    }
    if (count($track[$suffix] ?? []) > 1) {
        $warnings[] = "Kanalen $suffix finns nu i flera format för \"$base\". Bara en av filerna används.";
    }
    return $warnings;
}

/**
 * Behörighet för kanalfiler avgörs av huvudspåret (access.php: main_channel_file). Raden
 * "fil;UPLOAD_GROUP" döljer därför bara en ny kanalfil om den blir huvudfil. Varnar när
 * - den nya filen läggs till ett befintligt spår och ärver dess grupp (hörs direkt), eller
 * - den nya filen tar över som huvudfil och därmed döljer ett befintligt spår.
 * $group_map är load_track_groups(). Returnerar en lista med svenska meddelanden.
 */
function check_group_inheritance(string $name, array $existing_files, array $group_map): array {
    if (preg_match(CHANNEL_FILE_PATTERN, $name, $match) !== 1) return [];
    $before = scanned_channel_files(group_channel_files($existing_files)[$match[1]] ?? []);
    if ($before === []) return [];
    $main_before = main_channel_file($before);
    $main_after  = main_channel_file(scanned_channel_files(group_channel_files(array_merge($existing_files, [$name]))[$match[1]]));
    $group_label = fn(string $file) => track_group($file, $group_map) === '' ? 'alla inloggade' : track_group($file, $group_map);
    if ($main_after === $name) {
        return ["\"$name\" blir ny huvudfil för spåret. Hela spåret (tidigare styrt av \"$main_before\", grupp: "
            . $group_label($main_before) . ') syns nu bara för admin tills det flyttas i Grupper → Låtar.'];
    }
    return ["\"$name\" läggs till ett befintligt spår och ärver gruppen från \"$main_after\" ("
        . $group_label($main_after) . '). Kanalen hörs direkt för dem som ser spåret.'];
}

/**
 * [suffix => [filnamn, ...]] → [suffix => filnamn] som scan_music() ger: den går igenom filerna
 * sorterade och skriver över, så den sista i sorteringsordning vinner.
 */
function scanned_channel_files(array $track): array {
    $scanned = [];
    foreach ($track as $suffix => $files) {
        sort($files);
        $scanned[$suffix] = end($files);
    }
    return $scanned;
}
