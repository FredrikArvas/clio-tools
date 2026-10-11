<?php
/**
 * access.php — den enda platsen där regeln "vem får se vilket spår" bor.
 *
 * Anropas av: index.php (bygger spårlistan), stream.php (släpper igenom mediafiler),
 * admin/index.php (grupp-etikett i statistiken).
 *
 * Säkerhetsantaganden:
 * - Behörighet avgörs alltid på HUVUDSPÅRET. Kanalfiler (_bin/_vce/_env/_msc) och .lrc-filer
 *   ärver huvudspårets grupp, eftersom index.php bara exponerar dem via huvudspåret.
 *   Om index.php och stream.php skulle räkna olika uppstår en lucka — därför delar de
 *   scan_music() och main_channel_file() härifrån.
 * - Spår utan grupp syns för alla inloggade men aldrig för gäster.
 */

const CH_SUFFIXES = ['_msc', '_bin', '_vce', '_env'];

// Samma regex som tidigare låg i index.php. Icke-girig bas: "a_b_msc.mp3" → bas "a_b".
const CHANNEL_FILE_PATTERN = '/^(.+?)(_msc|_bin|_vce|_env)\.mp3$/i';

function load_track_groups(): array {
    $path = __DIR__ . '/data/track_groups.csv';
    $map  = [];
    if (!file_exists($path)) return $map;
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $parts = explode(';', $line, 2);
        if (count($parts) === 2) $map[trim($parts[0])] = trim($parts[1]);
    }
    return $map;
}

function track_group(string $filename, array $map): string {
    foreach ($map as $prefix => $group) {
        if (str_starts_with($filename, $prefix)) return $group;
    }
    return '';
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
    $files = is_dir($music_dir) ? (glob($music_dir . DIRECTORY_SEPARATOR . '*.mp3') ?: []) : [];
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
    return $channel_files['_msc'] ?? $channel_files['_vce'] ?? $channel_files['_env'] ?? $channel_files['_bin'] ?? null;
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
        if (in_array($base . '.mp3', $scan['standalone'], true)) $owners[] = $base . '.mp3';
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
