<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * tests/channels_test.php — test av channels.php (suffix → etikett, platstilldelning) och av
 * att access.php känner igen alla kanalsuffix.
 *
 * Körs lokalt eller på servern:  php tests/channels_test.php
 * Skriver bara i en tillfällig katalog som raderas vid avslut. Avslutskod 0 = alla gröna.
 */

require_once dirname(__DIR__) . '/channels.php';

$pass = 0;
$fail = 0;

function check(string $description, bool $condition): void {
    global $pass, $fail;
    if ($condition) { $pass++; echo "  OK    $description\n"; return; }
    $fail++;
    echo "  FEL   $description\n";
}

$labels = fn(array $slots, bool $choir) => array_map(fn($s) => channel_info($s[0], $choir)['label'], $slots);
$suffixes = fn(array $slots) => array_column($slots, 0);

// ── Tabellen ──────────────────────────────────────────────────────────────────
check('varje suffix i CH_SUFFIXES har en etikett', array_diff(CH_SUFFIXES, array_keys(CHANNELS)) === []);
check('varje valfri plats är ett känt suffix', array_diff(CHANNEL_SLOT_ORDER, CH_SUFFIXES) === []);
foreach (CHANNELS + ['msc som stämma' => CHANNEL_MSC_AS_VOICE] as $suffix => $c) {
    $ok = is_string($c['label']) && is_string($c['icon']) && is_string($c['list_icon'])
        && is_float($c['default']) && $c['default'] >= 0.0 && $c['default'] <= 1.0;
    check("$suffix: label, ikoner och default 0–1", $ok);
}

// ── Platstilldelning ──────────────────────────────────────────────────────────
$meditation = ['_msc' => 'a_msc.mp3', '_bin' => 'a_bin.mp3', '_vce' => 'a_vce.mp3', '_env' => 'a_env.mp3'];
$slots = channel_slots($meditation, 'a_msc.mp3');
check('meditation: _msc först, sedan bin/vce/env', $suffixes($slots) === ['_msc', '_bin', '_vce', '_env']);
check('meditation: etiketter Musik/Binauralt/Röst/Miljö', $labels($slots, false) === ['Musik', 'Binauralt', 'Röst', 'Miljö']);
check('meditation är inte körspår', !is_choir_track($meditation));

$choir = ['_msc' => 'k_msc.mp3', '_ch2' => 'k_ch2.mp3', '_ch3' => 'k_ch3.mp3', '_ch4' => 'k_ch4.mp3'];
$slots = channel_slots($choir, 'k_msc.mp3');
check('kör: msc, ch2, ch3, ch4', $suffixes($slots) === ['_msc', '_ch2', '_ch3', '_ch4']);
check('kör: _msc heter Stämma 1', $labels($slots, is_choir_track($choir)) === ['Stämma 1', 'Stämma 2', 'Stämma 3', 'Stämma 4']);

$mixed = ['_msc' => 'm_msc.mp3', '_ch2' => 'm_ch2.mp3', '_vce' => 'm_vce.mp3'];
$slots = channel_slots($mixed, 'm_msc.mp3');
check('blandat: msc, ch2, vce', $suffixes($slots) === ['_msc', '_ch2', '_vce']);
check('blandat: Stämma 1, Stämma 2, Röst', $labels($slots, is_choir_track($mixed)) === ['Stämma 1', 'Stämma 2', 'Röst']);

ini_set('error_log', PHP_OS_FAMILY === 'Windows' ? 'NUL' : '/dev/null');
$too_many = ['_msc' => 'x_msc.mp3', '_ch2' => 'x_ch2.mp3', '_ch3' => 'x_ch3.mp3', '_ch4' => 'x_ch4.mp3', '_vce' => 'x_vce.mp3'];
$slots = channel_slots($too_many, 'x_msc.mp3');
check('fler än fyra kanaler: bara fyra platser (vce spelas inte)', count($slots) === MAX_CHANNEL_SLOTS && !in_array('_vce', $suffixes($slots), true));

$no_msc = ['_vce' => 'r_vce.mp3', '_env' => 'r_env.mp3'];
$slots = channel_slots($no_msc, main_channel_file($no_msc));
check('utan _msc: huvudfilen (_vce) blir master och dubbleras inte', $suffixes($slots) === ['_vce', '_env']);
check('fristående spår: en plats, Musik', channel_slots(null, 'solo.mp3') === [['_msc', 'solo.mp3']]);
check('fristående spår är inte körspår', !is_choir_track(null));

// ── Rubrik i spelarlistan: album, annars behörighetsgrupp ─────────────────────
check('albumtaggen vinner över gruppen', track_section('FrUlleBo', 'FrUlleBo-låtar') === 'FrUlleBo');
check('utan album: gruppnamnet', track_section('', 'FrUlleBo-låtar') === 'FrUlleBo-låtar');
check('utan album: understreck blir mellanslag', track_section('', 'Ulrikas_35_årslåt') === 'Ulrikas 35 årslåt');
check('utan album och grupp: ingen rubrik', track_section('', '') === '');
check('utan album, uppladdat: egen rubrik', track_section('', UPLOAD_GROUP) === UPLOAD_SECTION_LABEL);
check('uppladdat med album: albumet', track_section('Demo', UPLOAD_GROUP) === 'Demo');

// ── access.php: suffixen grupperas och ärver huvudspårets behörighet ───────────
$dir = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'channels_test_' . bin2hex(random_bytes(4));
mkdir($dir);
foreach (['k_msc.mp3', 'k_ch2.mp3', 'k_CH3.m4a', 'solo.mp3', 'x_ch5.mp3'] as $name) touch($dir . DIRECTORY_SEPARATOR . $name);
$scan = scan_music($dir);
foreach (scandir($dir) as $entry) if ($entry !== '.' && $entry !== '..') unlink($dir . DIRECTORY_SEPARATOR . $entry);
rmdir($dir);

$k_group = $scan['channels']['k'] ?? [];
ksort($k_group);
check('scan: _ch2 och _CH3 grupperas med _msc', $k_group === ['_ch2' => 'k_ch2.mp3', '_ch3' => 'k_CH3.m4a', '_msc' => 'k_msc.mp3']);
check('scan: okänt suffix _ch5 är ett fristående spår', in_array('x_ch5.mp3', $scan['standalone'], true));
check('owning_tracks: _ch2-fil ägs av huvudfilen', owning_tracks('k_ch2.mp3', $scan) === ['k_msc.mp3']);
check('owning_tracks: okänd kanalfil ägs inte', owning_tracks('k_ch4.mp3', $scan) === []);

echo "\n$pass OK, $fail FEL\n";
exit($fail === 0 ? 0 : 1);
