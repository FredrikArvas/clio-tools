<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * tests/api_validation_test.php — enhetstest av api/_validation.php, rate_limit.php, json_store.php
 * och visible_track_urls() i access.php, mot fixture-filer i en tillfällig katalog.
 *
 * Körs lokalt eller på servern:  php tests/api_validation_test.php
 * Rör aldrig data/: spårkatalog, JSON-filer och räknare ligger i en tillfällig katalog. Avslutskod 0 = alla tester gröna.
 */

// access.php anropar is_guest() från auth.php, men auth.php startar en session vid inläsning.
function is_guest(array $user): bool {
    return !empty($user['is_guest']);
}

require_once dirname(__DIR__) . '/api/_validation.php';
require_once dirname(__DIR__) . '/json_store.php';

$pass = 0;
$fail = 0;

function check(string $description, bool $condition): void {
    global $pass, $fail;
    if ($condition) { $pass++; echo "  OK    $description\n"; return; }
    $fail++;
    echo "  FEL   $description\n";
}

function remove_dir(string $dir): void {
    foreach (scandir($dir) as $entry) {
        if ($entry === '.' || $entry === '..') continue;
        $path = $dir . DIRECTORY_SEPARATOR . $entry;
        is_dir($path) ? remove_dir($path) : unlink($path);
    }
    rmdir($dir);
}

$dir = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'api_validation_test_' . bin2hex(random_bytes(4));
mkdir($dir . DIRECTORY_SEPARATOR . 'music', 0775, true);
register_shutdown_function(fn() => remove_dir($dir));
foreach (['zz_a_msc.mp3', 'zz_a_vce.mp3', 'zz_b.mp3', 'zz Mellanslag å.mp3'] as $name) {
    touch($dir . '/music/' . $name);
}

echo "== Känt spår: visible_track_urls\n";
$admin = ['username' => 'a', 'admin' => 1, 'groups' => []];
$guest = ['username' => '__guest__', 'admin' => false, 'groups' => ['Gäst'], 'is_guest' => true];
$known = visible_track_urls($admin, $dir . '/music', 'music');
check('huvudfilen i flerkanalsspåret är känd (_msc)', isset($known['music/zz_a_msc.mp3']));
check('kanalfil som inte är huvudfil är inte ett eget spår', !isset($known['music/zz_a_vce.mp3']));
check('fristående spår är känt', isset($known['music/zz_b.mp3']));
check('URL:en är rawurlencodad som i index.php', isset($known['music/zz%20Mellanslag%20%C3%A5.mp3']));
check('okänd fil är inte känd', !isset($known['music/finns_inte.mp3']));
check('gäst ser inget av spåren utan grupp', visible_track_urls($guest, $dir . '/music', 'music') === []);
check('saknad musikkatalog ger tom mängd', visible_track_urls($admin, $dir . '/finns_inte', 'music') === []);
check('track_file_url matchar index.php-formatet', track_file_url('music', 'a b.mp3') === 'music/a%20b.mp3');

echo "== validate_known_track (log_play)\n";
[$track, $error] = validate_known_track('music/zz_b.mp3', $known);
check('känt spår ok', $error === '' && $track === 'music/zz_b.mp3');
foreach ([['okänt spår', 'music/hittepa.mp3'], ['tomt', ''], ['array', ['x']], ['null', null], ['tal', 5],
          ['för långt', 'music/' . str_repeat('x', 400)]] as [$label, $value]) {
    [, $error] = validate_known_track($value, $known);
    check("avvisas: $label", $error !== '');
}

echo "== Spårinställningar\n";
$valid = ['msc' => 0.8, 'bin' => 0, 'vce' => 1, 'env' => 0.4, 'ch2' => 0.8, 'ch3' => 0, 'ch4' => 1,'balance' => -1, 'bass' => -12, 'treble' => 3.5, 'liked' => true];
[$clean, $error] = validate_profile_settings('music/zz_b.mp3', $valid, $known);
check('giltiga inställningar godtas oförändrade', $error === '' && $clean === $valid);
[$clean, $error] = validate_profile_settings('music/zz_b.mp3', $valid + ['evil' => 'x', '__proto__' => 1, 'extra' => [1]], $known);
check('okända nycklar kastas, resten sparas', $error === '' && $clean === $valid);
$bad_settings = [
    'volym 9' => ['msc' => 9], 'negativ volym' => ['env' => -0.1], 'balans 2' => ['balance' => 2],
    'bas 13' => ['bass' => 13], 'diskant -13' => ['treble' => -13], 'sträng som tal' => ['msc' => '0.5'],
    'null' => ['msc' => null], 'liked som sträng' => ['liked' => 'true'], 'array' => ['bass' => [1]],
];
foreach ($bad_settings as $label => $settings) {
    [, $error] = validate_profile_settings('music/zz_b.mp3', $settings, $known);
    check("avvisas: $label", $error !== '');
}
[, $error] = validate_profile_settings('music/hittepa.mp3', $valid, $known);
check('okänt spår avvisas', $error !== '');
[, $error] = validate_profile_settings('music/zz_b.mp3', 'inte array', $known);
check('settings som inte är array avvisas', $error !== '');
[$clean, $error] = validate_profile_settings('music/zz_b.mp3', [], $known);
check('tomma inställningar godtas', $error === '' && $clean === []);

echo "== Globala inställningar (_settings)\n";
$global = ['playMode' => 'shuffle', 'playbackRate' => 1.25, 'queue' => ['music/zz_b.mp3', 'music/hittepa.mp3', 7], 'queueCursor' => 0, 'gammal' => 1];
[$clean, $error] = validate_profile_settings('_settings', $global, $known);
check('giltiga globala inställningar godtas', $error === '');
check('kön filtreras mot kända spår (okänt och icke-sträng bort)', ($clean['queue'] ?? null) === ['music/zz_b.mp3']);
check('okända nycklar kastas', !isset($clean['gammal']));
check('playMode, hastighet och köposition behålls', $clean['playMode'] === 'shuffle' && $clean['playbackRate'] === 1.25 && $clean['queueCursor'] === 0);
foreach ([['playMode' => 'turbo'], ['playMode' => 3], ['playbackRate' => 9], ['playbackRate' => 0.1], ['playbackRate' => '1'],
          ['queue' => 'x'], ['queue' => array_fill(0, MAX_QUEUE_LENGTH + 1, 'music/zz_b.mp3')],
          ['queueCursor' => -2], ['queueCursor' => 1.5], ['queueCursor' => MAX_QUEUE_LENGTH + 1]] as $settings) {
    [, $error] = validate_profile_settings('_settings', $settings, $known);
    check('avvisas: ogiltig global inställning ' . implode(',', array_keys($settings)), $error !== '');
}
[$clean, $error] = validate_profile_settings('_settings', ['queueCursor' => -1, 'queue' => []], $known);
check('tom kö och köposition -1 godtas', $error === '' && $clean === ['queue' => [], 'queueCursor' => -1]);

echo "== Spellistor\n";
[$name, $error] = validate_playlist_name("  Min lista\x00\x1F\n ");
check('kontrolltecken rensas och blanksteg trimmas', $error === '' && $name === 'Min lista');
[$name, $error] = validate_playlist_name('Åsa & "Bo" <b>');
check('vanliga tecken (även å, citattecken) godtas', $error === '' && $name === 'Åsa & "Bo" <b>');
foreach ([['tomt', ''], ['bara blanksteg', "  \t "], ['bara kontrolltecken', "\x01\x02"], ['för långt', str_repeat('x', MAX_PLAYLIST_NAME_LENGTH + 1)],
          ['ogiltig UTF-8', "ab\xff"], ['array', ['x']], ['null', null], ['tal', 5]] as [$label, $value]) {
    [, $error] = validate_playlist_name($value);
    check("namn avvisas: $label", $error !== '');
}
[$name, $error] = validate_playlist_name(str_repeat('x', MAX_PLAYLIST_NAME_LENGTH));
check('namn på exakt maxlängd godtas', $error === '');
[$list, $error] = validate_playlist_tracks(['music/zz_b.mp3', 'music/hittepa.mp3', 3, null, 'music/zz_a_msc.mp3'], $known);
check('okända och icke-strängar filtreras bort, ordningen bevaras', $error === '' && $list === ['music/zz_b.mp3', 'music/zz_a_msc.mp3']);
[$list, $error] = validate_playlist_tracks([], $known);
check('tom spellista godtas', $error === '' && $list === []);
[, $error] = validate_playlist_tracks(array_fill(0, MAX_TRACKS_PER_PLAYLIST + 1, 'music/zz_b.mp3'), $known);
check('för många spår avvisas', $error !== '');
[, $error] = validate_playlist_tracks('inte array', $known);
check('spår som inte är array avvisas', $error !== '');

echo "== json_store: läs-ändra-skriv\n";
$path = $dir . '/store.json';
check('ny fil skapas', json_file_update($path, fn(array $d) => $d + ['a' => 1]) && json_file_read($path) === ['a' => 1]);
check('befintliga nycklar bevaras', json_file_update($path, fn(array $d) => $d + ['b' => 2]) && json_file_read($path) === ['a' => 1, 'b' => 2]);
$before = file_get_contents($path);
check('null från mutatorn skriver inget', json_file_update($path, fn(array $d) => null) && file_get_contents($path) === $before);
file_put_contents($path, '{trasig');
check('abort: trasig fil skrivs inte över', json_file_update($path, fn(array $d) => ['x' => 1], 'abort') === false && file_get_contents($path) === '{trasig');
check('reset: trasig fil börjar om', json_file_update($path, fn(array $d) => ['x' => 1], 'reset') && json_file_read($path) === ['x' => 1]);
file_put_contents($path, '{trasig');
check('json_file_read: trasig fil ger []', json_file_read($path) === []);
check('json_file_read: saknad fil ger []', json_file_read($dir . '/finns_inte.json') === []);
file_put_contents($path, '{"gammal_nyckel": {"volume": 7}, "music/x.mp3": {"msc": 1}}');
check('json_file_read: äldre filer med okända nycklar läses som de är', json_file_read($path)['gammal_nyckel'] === ['volume' => 7]);
check('okänd katalog ger false', json_file_update($dir . '/finns_inte/x.json', fn(array $d) => $d) === false);

echo "== rate_limit_hit\n";
define('RATE_LIMIT_DIR', $dir . '/rate_limits');
require_once dirname(__DIR__) . '/rate_limit.php';
$bucket = 'unit_test_' . bin2hex(random_bytes(4));
$results = [];
for ($i = 1; $i <= 12; $i++) $results[] = rate_limit_hit($bucket, 'nyckel', 10, 60);
check('de 10 första träffarna släpps igenom', array_slice($results, 0, 10) === array_fill(0, 10, 0));
check('träff 11 och 12 spärras med Retry-After mellan 1 och 60', $results[10] >= 1 && $results[10] <= 60 && $results[11] >= 1);
check('annan nyckel har egen räknare', rate_limit_hit($bucket, 'annan', 10, 60) === 0);
check('annan hink har egen räknare', rate_limit_hit($bucket . 'x', 'nyckel', 10, 60) === 0);
file_put_contents(rate_limit_file($bucket, 'gammal'), json_encode(['window_start' => time() - 120, 'hits' => 99]));
check('nytt fönster nollställer räknaren', rate_limit_hit($bucket, 'gammal', 10, 60) === 0);
foreach (['nyckel', 'annan', 'gammal'] as $key) unlink(rate_limit_file($bucket, $key));
unlink(rate_limit_file($bucket . 'x', 'nyckel'));

echo "\nResultat: $pass OK, $fail FEL\n";
exit($fail === 0 ? 0 : 1);
