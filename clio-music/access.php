<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * access.php — den enda platsen där regeln "vem får se vilket spår" bor.
 *
 * Anropas av: index.php (bygger spårlistan), stream.php (släpper igenom mediafiler),
 * admin/index.php (grupp-etikett i statistiken).
 *
 * Säkerhetsantaganden:
 * - Behörighet avgörs alltid på HUVUDSPÅRET. Kanalfiler (CH_SUFFIXES) och .lrc-filer
 *   ärver huvudspårets grupp, eftersom index.php bara exponerar dem via huvudspåret.
 *   Om index.php och stream.php skulle räkna olika uppstår en lucka — därför delar de
 *   scan_music() och main_channel_file() härifrån.
 * - Spår utan grupp syns för alla inloggade men aldrig för gäster.
 */

// Alla kanalsuffix. _msc är master; övriga är valfria (etiketter i channels.php).
// Ordningen är också reservordningen för huvudfilen när _msc saknas (main_channel_file).
const CH_SUFFIXES = ['_msc', '_vce', '_env', '_bin', '_ch2', '_ch3', '_ch4'];

// Stöder mp3 och m4a. Icke-girig bas: "a_b_msc.mp3" → bas "a_b".
const AUDIO_EXTENSIONS      = ['mp3', 'm4a'];
const AUDIO_EXT_PATTERN     = '(?:mp3|m4a)';
const CHANNEL_SUFFIX_PATTERN = '(_msc|_vce|_env|_bin|_ch2|_ch3|_ch4)';   // samma som CH_SUFFIXES
const CHANNEL_FILE_PATTERN  = '/^(.+?)' . CHANNEL_SUFFIX_PATTERN . '\.(?:mp3|m4a)$/i';

/**
 * Läser en prefixtabell "prefix;värde" (rader som börjar med # hoppas över).
 * Delas av track_groups.csv (behörighet) och track_types.csv (spårtyp, track_types.php).
 */
function load_prefix_csv(string $path): array {
    $map = [];
    if (!file_exists($path)) return $map;
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $parts = explode(';', $line, 2);
        if (count($parts) === 2) $map[trim($parts[0])] = trim($parts[1]);
    }
    return $map;
}

/** Värdet för första prefixet i tabellen som filnamnet börjar med, annars ''. */
function prefix_lookup(string $filename, array $map): string {
    foreach ($map as $prefix => $value) {
        if (str_starts_with($filename, $prefix)) return $value;
    }
    return '';
}

function load_track_groups(): array {
    return load_prefix_csv(__DIR__ . '/data/track_groups.csv');
}

function track_group(string $filename, array $map): string {
    return prefix_lookup($filename, $map);
}

function user_can_see(string $track_group, array $user): bool {
    if (!empty($user['admin'])) return true;
    if (in_array('Alla', $user['groups'] ?? [])) return true;
    if (is_guest($user)) return in_array($track_group, $user['groups']);
    if ($track_group === '') return true;
    return in_array($track_group, $user['groups'] ?? []);
}

/**
 * Skannar musikkatalogen och delar upp filerna i flerkanalsspår och fristående spår.
 * Returnerar ['channels' => [bas => [suffix => filnamn]], 'standalone' => [filnamn, ...]]
 * (endast filnamn, inga sökvägar), sorterat.
 */
function scan_music(string $music_dir): array {
    $all = [];
    foreach (AUDIO_EXTENSIONS as $ext) {
        $all = array_merge($all, glob($music_dir . DIRECTORY_SEPARATOR . '*.' . $ext) ?: []);
    }
    $files = $all;
    sort($files);
    $channels   = [];
    $standalone = [];
    foreach ($files as $path) {
        $filename = basename($path);
        if (preg_match(CHANNEL_FILE_PATTERN, $filename, $match)) {
            $channels[$match[1]][strtolower($match[2])] = $filename;
        } else {
            $standalone[] = $filename;
        }
    }
    return ['channels' => $channels, 'standalone' => $standalone];
}

/** Huvudfilen i ett flerkanalsspår: den vars grupp styr hela spåret. */
function main_channel_file(array $channel_files): ?string {
    foreach (CH_SUFFIXES as $suffix) {
        if (isset($channel_files[$suffix])) return $channel_files[$suffix];
    }
    return null;
}

/**
 * Vilka huvudspår exponerar denna mediafil i index.php?
 * - Kanalfil → huvudfilen i dess grupp.
 * - Fristående mp3 → sig själv.
 * - .lrc → de spår vars bas är lrc-namnet (normalt ett; två om både "x.mp3" och "x_msc.mp3" finns).
 * Tom array = filen exponeras inte av något spår och ska nekas.
 */
function owning_tracks(string $filename, array $scan): array {
    if (preg_match('/\.lrc$/i', $filename)) {
        $base   = preg_replace('/\.lrc$/i', '', $filename);
        $owners = [];
        if (isset($scan['channels'][$base])) $owners[] = main_channel_file($scan['channels'][$base]);
        foreach (AUDIO_EXTENSIONS as $ext) {
            if (in_array($base . '.' . $ext, $scan['standalone'], true)) $owners[] = $base . '.' . $ext;
        }
        return array_values(array_filter($owners));
    }
    if (preg_match(CHANNEL_FILE_PATTERN, $filename, $match)) {
        $channel_files = $scan['channels'][$match[1]] ?? [];
        return in_array($filename, $channel_files, true) ? array_filter([main_channel_file($channel_files)]) : [];
    }
    return in_array($filename, $scan['standalone'], true) ? [$filename] : [];
}

/** Får användaren hämta mediafilen? Sant om minst ett ägande spår är synligt (samma som UI:t visar). */
function user_can_access_media(string $filename, array $user, string $music_dir): bool {
    $group_map = load_track_groups();
    foreach (owning_tracks($filename, scan_music($music_dir)) as $main_file) {
        if (user_can_see(track_group($main_file, $group_map), $user)) return true;
    }
    return false;
}

/** Spårets URL i exakt det format index.php skriver i TRACKS (profiler, spellistor och plays.jsonl nycklas på det). */
function track_file_url(string $music_url, string $filename): string {
    return $music_url . '/' . rawurlencode($filename);
}

/**
 * Spåren (en post per huvudspår) som användaren får se, i den ordning index.php visar dem:
 * först flerkanalsspår, sedan fristående. Varje post: ['main_file' => filnamn,
 * 'base' => kanalspårets bas eller null, 'channel_files' => [suffix => filnamn] eller null].
 * Delas av index.php (bygger TRACKS) och API:erna (validerar spår), så att regeln aldrig dupliceras.
 */
function list_visible_tracks(array $user, string $music_dir): array {
    $group_map = load_track_groups();
    $scan      = scan_music($music_dir);
    $visible   = [];
    foreach ($scan['channels'] as $base => $channel_files) {
        $main_file = main_channel_file($channel_files);
        if ($main_file === null || !user_can_see(track_group($main_file, $group_map), $user)) continue;
        $visible[] = ['main_file' => $main_file, 'base' => (string)$base, 'channel_files' => $channel_files];
    }
    foreach ($scan['standalone'] as $filename) {
        if (!user_can_see(track_group($filename, $group_map), $user)) continue;
        $visible[] = ['main_file' => $filename, 'base' => null, 'channel_files' => null];
    }
    return $visible;
}

/** Mängden av `file`-URL:er (nycklar i arrayen) som användaren får se. Okänt eller osynligt spår = inte med. */
function visible_track_urls(array $user, string $music_dir, string $music_url): array {
    $urls = [];
    foreach (list_visible_tracks($user, $music_dir) as $track) {
        $urls[track_file_url($music_url, $track['main_file'])] = true;
    }
    return $urls;
}
