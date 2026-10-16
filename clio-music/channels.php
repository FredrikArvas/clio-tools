<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * channels.php — filsuffixet styr kanalens etikett, ikon och standardvolym i spelaren.
 *
 * Ett spår har högst MAX_CHANNEL_SLOTS kanaler. Plats 0 är master (driver förlopp och EQ):
 * _msc, eller huvudfilen enligt main_channel_file() om _msc saknas. Övriga platser fylls med
 * de valfria kanalerna i CHANNEL_SLOT_ORDER och kan blandas fritt, t.ex. _ch2 + _vce + _env.
 * _msc heter "Stämma 1" när spåret har någon _chN-fil, annars "Musik".
 *
 * Behörigheten bor kvar i access.php; här finns bara presentation och platstilldelning.
 */

require_once __DIR__ . '/access.php';

const MAX_CHANNEL_SLOTS = 4;

// Valfria kanaler i den ordning de får platserna 1–3.
const CHANNEL_SLOT_ORDER = ['_ch2', '_ch3', '_ch4', '_bin', '_vce', '_env'];

// Per suffix: label, icon (inställningspanelen), list_icon (spårlistan), default (volym 0–1).
const CHANNELS = [
    '_msc' => ['label' => 'Musik',     'icon' => '🎵', 'list_icon' => '♪', 'default' => 0.8],
    '_bin' => ['label' => 'Binauralt', 'icon' => '🔈', 'list_icon' => '≋', 'default' => 0.5],
    '_vce' => ['label' => 'Röst',      'icon' => '🎙', 'list_icon' => '◎', 'default' => 0.9],
    '_env' => ['label' => 'Miljö',     'icon' => '🌿', 'list_icon' => '〜', 'default' => 0.4],
    '_ch2' => ['label' => 'Stämma 2',  'icon' => '②',  'list_icon' => '②', 'default' => 0.8],
    '_ch3' => ['label' => 'Stämma 3',  'icon' => '③',  'list_icon' => '③', 'default' => 0.8],
    '_ch4' => ['label' => 'Stämma 4',  'icon' => '④',  'list_icon' => '④', 'default' => 0.8],
];
const CHANNEL_MSC_AS_VOICE = ['label' => 'Stämma 1', 'icon' => '①', 'list_icon' => '①', 'default' => 0.8];

/** Presentation för en kanal; $is_choir gör _msc till "Stämma 1". */
function channel_info(string $suffix, bool $is_choir): array {
    if ($suffix === '_msc' && $is_choir) return CHANNEL_MSC_AS_VOICE;
    return CHANNELS[$suffix];
}

/**
 * Platser för ett spår: lista med [suffix, filnamn], plats 0 = master, högst MAX_CHANNEL_SLOTS.
 * $channel_files = [suffix => filnamn] från scan_music(), null för fristående spår.
 * Kanaler som inte får plats loggas och spelas inte.
 */
function channel_slots(?array $channel_files, string $main_file): array {
    if ($channel_files === null) return [['_msc', $main_file]];
    $master_suffix = array_search($main_file, $channel_files, true);
    $slots = [[$master_suffix, $main_file]];
    foreach (CHANNEL_SLOT_ORDER as $suffix) {
        if (!isset($channel_files[$suffix]) || $suffix === $master_suffix) continue;
        if (count($slots) >= MAX_CHANNEL_SLOTS) {
            error_log("clio_music: $main_file har fler än " . MAX_CHANNEL_SLOTS . " kanaler; {$channel_files[$suffix]} spelas inte");
            continue;
        }
        $slots[] = [$suffix, $channel_files[$suffix]];
    }
    return $slots;
}

/** Är spåret ett körspår (minst en _chN-fil)? */
function is_choir_track(?array $channel_files): bool {
    return $channel_files !== null && (isset($channel_files['_ch2']) || isset($channel_files['_ch3']) || isset($channel_files['_ch4']));
}
