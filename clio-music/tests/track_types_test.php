<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * tests/track_types_test.php — test av track_types.php (spårtyp via prefixtabell).
 *
 * Körs lokalt eller på servern:  php tests/track_types_test.php
 * Rör aldrig data/track_types.csv: tabellen skrivs i en tillfällig fil. Avslutskod 0 = alla gröna.
 */

require_once dirname(__DIR__) . '/track_types.php';

$pass = 0;
$fail = 0;

function check(string $description, bool $condition): void {
    global $pass, $fail;
    if ($condition) { $pass++; echo "  OK    $description\n"; return; }
    $fail++;
    echo "  FEL   $description\n";
}

// ── Typdefinitionerna ─────────────────────────────────────────────────────────
check('standardtypen finns', isset(TRACK_TYPES[DEFAULT_TRACK_TYPE]));
check('typerna meditation och kör finns', isset(TRACK_TYPES['meditation'], TRACK_TYPES['kör']));
foreach (TRACK_TYPES as $name => $def) {
    check("$name: har eq_title", is_string($def['eq_title'] ?? null) && $def['eq_title'] !== '');
    check("$name: exakt kanalerna msc/bin/vce/env", array_keys($def['channels']) === ['msc', 'bin', 'vce', 'env']);
    foreach ($def['channels'] as $ch => $c) {
        $ok = is_string($c['label'] ?? null) && is_string($c['icon'] ?? null) && is_string($c['list_icon'] ?? null)
            && is_float($c['default'] ?? null) && $c['default'] >= 0.0 && $c['default'] <= 1.0;
        check("$name/$ch: label, ikoner och default 0–1", $ok);
    }
}
check('kör: stämma 1–4 i kanalordning', array_column(TRACK_TYPES['kör']['channels'], 'label') === ['Stämma 1', 'Stämma 2', 'Stämma 3', 'Stämma 4']);

// ── Prefixtabellen ────────────────────────────────────────────────────────────
$csv = tempnam(sys_get_temp_dir(), 'track_types_test_');
file_put_contents($csv, "# kommentar\n101_kor_;kör\n102_;meditation\n103_;okänd_typ\n\nfelrad_utan_semikolon\n");
$map = load_prefix_csv($csv);
unlink($csv);

check('kommentarer och felrader hoppas över', $map === ['101_kor_' => 'kör', '102_' => 'meditation', '103_' => 'okänd_typ']);
check('prefixträff ger kör', track_type('101_kor_Gloria_msc.mp3', $map) === 'kör');
check('uttrycklig meditation', track_type('102_vila.mp3', $map) === 'meditation');
check('spår utan rad ger standardtypen', track_type('999_annat.mp3', $map) === DEFAULT_TRACK_TYPE);
check('tom tabell ger standardtypen', track_type('101_kor_Gloria_msc.mp3', []) === DEFAULT_TRACK_TYPE);

ini_set('error_log', PHP_OS_FAMILY === 'Windows' ? 'NUL' : '/dev/null');
check('okänd typ ger standardtypen (loggas)', track_type('103_x.mp3', $map) === DEFAULT_TRACK_TYPE);
check('saknad fil ger tom tabell', load_prefix_csv(sys_get_temp_dir() . '/finns_inte_' . bin2hex(random_bytes(4)) . '.csv') === []);

echo "\n$pass OK, $fail FEL\n";
exit($fail === 0 ? 0 : 1);
