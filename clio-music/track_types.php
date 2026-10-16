<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * track_types.php — spårtyp styr hur de fyra kanalerna presenteras i spelaren.
 *
 * Typen sätts i data/track_types.csv med samma prefixmatchning som track_groups.csv
 * ("prefix;typ"). Spår utan rad får DEFAULT_TRACK_TYPE.
 *
 * Typen påverkar bara presentationen: etikett, ikon och standardvolym per kanal samt
 * EQ-rubriken. Filsuffixen (_msc/_bin/_vce/_env), ljudkedjan, profilnycklarna och
 * behörigheten (access.php) är desamma för alla typer.
 */

require_once __DIR__ . '/access.php';

const DEFAULT_TRACK_TYPE = 'meditation';

// Per kanal: label (inställningspanelen), icon (före etiketten), list_icon (spårlistan),
// default (standardvolym 0–1 innan användaren sparat en egen profil).
const TRACK_TYPES = [
    'meditation' => [
        'eq_title' => 'Equalizer — musikkanal',
        'channels' => [
            'msc' => ['label' => 'Musik',     'icon' => '🎵', 'list_icon' => '♪', 'default' => 0.8],
            'bin' => ['label' => 'Binauralt', 'icon' => '🔈', 'list_icon' => '≋', 'default' => 0.5],
            'vce' => ['label' => 'Röst',      'icon' => '🎙', 'list_icon' => '◎', 'default' => 0.9],
            'env' => ['label' => 'Miljö',     'icon' => '🌿', 'list_icon' => '〜', 'default' => 0.4],
        ],
    ],
    'kör' => [
        'eq_title' => 'Equalizer — stämma 1',
        'channels' => [
            'msc' => ['label' => 'Stämma 1', 'icon' => '①', 'list_icon' => '①', 'default' => 0.8],
            'bin' => ['label' => 'Stämma 2', 'icon' => '②', 'list_icon' => '②', 'default' => 0.8],
            'vce' => ['label' => 'Stämma 3', 'icon' => '③', 'list_icon' => '③', 'default' => 0.8],
            'env' => ['label' => 'Stämma 4', 'icon' => '④', 'list_icon' => '④', 'default' => 0.8],
        ],
    ],
];

function load_track_types(): array {
    return load_prefix_csv(__DIR__ . '/data/track_types.csv');
}

/** Spårets typ. Okänd typ i tabellen loggas och ger DEFAULT_TRACK_TYPE. */
function track_type(string $filename, array $map): string {
    $type = prefix_lookup($filename, $map);
    if ($type === '') return DEFAULT_TRACK_TYPE;
    if (!isset(TRACK_TYPES[$type])) {
        error_log("clio_music: okänd spårtyp '$type' för $filename i track_types.csv");
        return DEFAULT_TRACK_TYPE;
    }
    return $type;
}
