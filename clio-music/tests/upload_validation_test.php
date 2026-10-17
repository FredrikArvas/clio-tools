<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * tests/upload_validation_test.php — test av admin/upload_validation.php (namn, storlek, innehåll,
 * kanalvarningar) och av regeln för UPLOAD_GROUP i user_can_see() (access.php).
 *
 * Körs lokalt eller på servern:  php tests/upload_validation_test.php
 * Rör aldrig data/ eller music/: små ljud-fixtures skapas i en tillfällig katalog som raderas
 * vid avslut (inga binärer i repot). Avslutskod 0 = alla tester gröna.
 */

// access.php anropar is_guest() från auth.php, men auth.php startar en session vid inläsning.
function is_guest(array $user): bool {
    return !empty($user['is_guest']);
}

require_once dirname(__DIR__) . '/admin/upload_validation.php';

$pass = 0;
$fail = 0;

function check(string $description, bool $condition): void {
    global $pass, $fail;
    if ($condition) { $pass++; echo "  OK    $description\n"; return; }
    $fail++;
    echo "  FEL   $description\n";
}

$music_url = 'music';
$name_ok   = fn(string $name) => validate_upload_filename($name, $music_url)[1] === '';
$name_code = fn(string $name) => validate_upload_filename($name, $music_url)[1];

echo "== Filnamn: giltiga\n";
foreach (['solo.mp3', '001_djup-avslappning_msc.mp3', 'kör_ch3.m4a', 'Aim for the Stars.mp3', 'Åsa ängel öga.mp3', 'a.b.c.mp3'] as $name) {
    check("giltigt: $name", $name_ok($name));
}
[$normalized] = validate_upload_filename('Sång_msc.M4A', $music_url);
check('.M4A godtas och sparas som .m4a', $normalized === 'Sång_msc.m4a');
[$normalized] = validate_upload_filename('x.Mp3', $music_url);
check('.Mp3 sparas som .mp3', $normalized === 'x.mp3');
[$normalized] = validate_upload_filename('Åsa.mp3', $music_url);
check('namnet i övrigt orört', $normalized === 'Åsa.mp3');

echo "== Filnamn: ogiltiga\n";
$max_name   = str_repeat('a', MAX_TRACK_URL_LENGTH - strlen($music_url . '/') - 4) . '.mp3';
$long_utf8  = str_repeat('å', 40) . '.mp3';   // 84 byte, 250 tecken som URL (%C3%A5 per å)
$bad_names = [
    '../x.mp3'         => 'invalid_name',
    'a/b.mp3'          => 'invalid_name',
    'a\\b.mp3'         => 'invalid_name',
    '.hidden.mp3'      => 'invalid_name',
    '#x.mp3'           => 'invalid_name',
    ' x.mp3'           => 'invalid_name',
    'a;b.mp3'          => 'invalid_name',
    "a\nb.mp3"         => 'invalid_name',
    "a\rb.mp3"         => 'invalid_name',
    "a\0b.mp3"         => 'invalid_name',
    "a\tb.mp3"         => 'invalid_name',
    "a\x7Fb.mp3"       => 'invalid_name',
    "a\u{202E}3pm.mp3" => 'invalid_name',   // RTL-override (visas som annat namn)
    "\xff\xfe.mp3"     => 'invalid_name',   // ogiltig UTF-8
    "a\xC3.mp3"        => 'invalid_name',   // avhuggen UTF-8-sekvens
    ''                 => 'invalid_name',
    'x.php'            => 'invalid_extension',
    'x.mp3.php'        => 'invalid_extension',
    'x.mp3 '           => 'invalid_name',
    'x.wav'            => 'invalid_extension',
    'mp3'              => 'invalid_extension',
    '.mp3'             => 'invalid_name',
    "x.mp3\n"          => 'invalid_name',
    $max_name . 'x'    => 'invalid_extension',
    'a' . $max_name    => 'name_too_long',
    $long_utf8 . $long_utf8 => 'name_too_long',
];
foreach ($bad_names as $name => $expected) {
    $code = $name_code((string)$name);
    check('avvisas (' . $expected . '): ' . json_encode(substr((string)$name, 0, 40), JSON_INVALID_UTF8_SUBSTITUTE), $code === $expected);
}
check('längsta tillåtna namn godtas', $name_ok($max_name));
check('URL-längden räknas kodad (å = %C3%A5)', $name_ok($long_utf8) && strlen(track_file_url($music_url, $long_utf8)) <= MAX_TRACK_URL_LENGTH);

echo "== Storlek\n";
check('0 byte avvisas', validate_upload_size(0)[1] === 'empty_file');
check('negativ storlek avvisas', validate_upload_size(-1)[1] === 'empty_file');
check('1 byte godtas', validate_upload_size(1) === [1, '']);
check('exakt gränsen godtas', validate_upload_size(UPLOAD_MAX_BYTES) === [UPLOAD_MAX_BYTES, '']);
check('gränsen + 1 avvisas', validate_upload_size(UPLOAD_MAX_BYTES + 1)[1] === 'too_large');
check('gränsen är 95 MB', UPLOAD_MAX_BYTES === 95 * 1024 * 1024);

echo "== Innehåll\n";
ini_set('error_log', PHP_OS_FAMILY === 'Windows' ? 'NUL' : '/dev/null');   // "fileinfo saknas" där tillägget inte finns
$dir = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'upload_validation_test_' . bin2hex(random_bytes(4));
mkdir($dir);
register_shutdown_function(function () use ($dir): void {
    foreach (scandir($dir) as $entry) if ($entry !== '.' && $entry !== '..') unlink($dir . DIRECTORY_SEPARATOR . $entry);
    rmdir($dir);
});
$fixtures = [
    'id3.mp3'   => "ID3\x04\x00\x00\x00\x00\x00\x00" . str_repeat("\x00", 54),
    'frame.mp3' => "\xFF\xFB\x90\x64" . str_repeat("\x00", 60),            // MPEG-1 Layer III, 128 kbit/s, 44,1 kHz
    'mpeg2.mp3' => "\xFF\xF3\x90\x64" . str_repeat("\x00", 60),            // MPEG-2 Layer III
    'ftyp.m4a'  => "\x00\x00\x00\x20ftypM4A \x00\x00\x02\x00M4A isom" . str_repeat("\x00", 40),
    'png.mp3'   => "\x89PNG\r\n\x1a\n" . str_repeat("\x00", 56),
    'php.mp3'   => "<?php echo 'x'; ?>\n" . str_repeat(' ', 40),
    'bad_sync.mp3' => "\xFF\xFF\xFF\xFF" . str_repeat("\x00", 60),         // ogiltig bithastighet/lager
    'short.m4a' => "\x00\x00\x00",
    'empty.mp3' => '',
];
foreach ($fixtures as $name => $content) file_put_contents($dir . DIRECTORY_SEPARATOR . $name, $content);
$content_ok = fn(string $file, string $ext) => validate_upload_content($dir . DIRECTORY_SEPARATOR . $file, $ext)[1] === '';

check('mp3 med ID3-tagg godtas', $content_ok('id3.mp3', 'mp3'));
check('mp3 med MPEG-1-ramsynk godtas', $content_ok('frame.mp3', 'mp3'));
check('mp3 med MPEG-2-ramsynk godtas', $content_ok('mpeg2.mp3', 'mp3'));
check('m4a med ftyp godtas', $content_ok('ftyp.m4a', 'm4a'));
check('ändelsen jämförs skiftlägesokänsligt (M4A)', $content_ok('ftyp.m4a', 'M4A'));
check('mp3-ändelse med PNG-innehåll avvisas', !$content_ok('png.mp3', 'mp3'));
check('mp3-ändelse med PHP-kod avvisas', !$content_ok('php.mp3', 'mp3'));
check('m4a-ändelse med mp3-innehåll avvisas', !$content_ok('id3.mp3', 'm4a'));
check('m4a-ändelse med mp3-ramsynk avvisas', !$content_ok('frame.mp3', 'm4a'));
check('mp3-ändelse med m4a-innehåll avvisas', !$content_ok('ftyp.m4a', 'mp3'));
check('ogiltig ramsynk avvisas', !$content_ok('bad_sync.mp3', 'mp3'));
check('för kort m4a avvisas', !$content_ok('short.m4a', 'm4a'));
check('tom fil avvisas', !$content_ok('empty.mp3', 'mp3'));
check('saknad fil avvisas', !$content_ok('finns_inte.mp3', 'mp3'));
check('okänd ändelse avvisas', !$content_ok('id3.mp3', 'wav'));
check('felkoden är content_mismatch (415)', validate_upload_content($dir . '/png.mp3', 'mp3')[1] === 'content_mismatch'
    && upload_error('content_mismatch')[0] === 415);
echo '  (finfo ' . (class_exists('finfo') ? 'finns och kontrolleras också' : 'saknas här: bara magiska byte testas') . ")\n";

echo "== Felkoder\n";
$expected_status = ['exists' => 409, 'too_large' => 413, 'invalid_extension' => 415, 'invalid_name' => 400,
    'rate_limited' => 429, 'csrf' => 403, 'forbidden' => 403, 'not_logged_in' => 401];
foreach ($expected_status as $code => $status) check("$code → $status", upload_error($code)[0] === $status);
check('okänd kod → 500', upload_error('hittepå')[0] === 500);
check('alla meddelanden är ifyllda', count(array_filter(UPLOAD_ERRORS, fn($e) => is_int($e[0]) && $e[1] !== '')) === count(UPLOAD_ERRORS));

echo "== Kanalvarningar\n";
$existing = ['a_msc.mp3', 'a_bin.mp3', 'a_vce.mp3', 'b_vce.mp3', 'solo.mp3', 'k_msc.mp3', 'k_ch2.mp3', 'k_ch3.mp3', 'k_ch4.mp3'];
check('fristående spår: inga varningar', check_channel_rules('ny.mp3', $existing) === []);
check('_msc till nytt spår: inga varningar', check_channel_rules('ny_msc.mp3', $existing) === []);
check('_env till spår med _msc (3 → 4 kanaler): inga varningar', check_channel_rules('a_env.mp3', $existing) === []);
check('_bin utan _msc varnar', count(check_channel_rules('c_bin.mp3', $existing)) === 1);
check('_bin till spår som bara har _vce varnar', count(check_channel_rules('b_bin.mp3', $existing)) === 1);
$fifth = check_channel_rules('k_vce.mp3', $existing);
check('femte kanalen varnar (en varning)', count($fifth) === 1 && str_contains($fifth[0], (string)MAX_CHANNEL_SLOTS));
check('samma kanal i två format varnar', count(check_channel_rules('a_bin.m4a', $existing)) === 1);
check('_BIN med versaler räknas som _bin (utan _msc)', count(check_channel_rules('c_BIN.mp3', $existing)) === 1);

echo "== Gruppärvning för kanalfiler\n";
$map = ['a_msc.mp3' => 'Kör', 'b_vce.mp3' => 'RIM1'];
check('fristående spår: ingen ärvningsvarning', check_group_inheritance('ny.mp3', $existing, $map) === []);
check('kanal till nytt spår: ingen ärvningsvarning', check_group_inheritance('ny_bin.mp3', $existing, $map) === []);
$inherit = check_group_inheritance('a_env.mp3', $existing, $map);
check('kanal till befintligt spår ärver gruppen (varning nämner Kör)', count($inherit) === 1 && str_contains($inherit[0], 'Kör'));
$takeover = check_group_inheritance('b_msc.mp3', $existing, $map);
check('ny _msc tar över befintligt spår (varning nämner RIM1)', count($takeover) === 1 && str_contains($takeover[0], 'RIM1'));
$ungrouped = check_group_inheritance('k_env.mp3', $existing, $map);
check('spår utan grupp beskrivs som alla inloggade', count($ungrouped) === 1 && str_contains($ungrouped[0], 'alla inloggade'));

echo "== user_can_see() och UPLOAD_GROUP\n";
$admin   = ['username' => 'admin', 'admin' => true, 'groups' => []];
$alla    = ['username' => 'alla', 'admin' => false, 'groups' => ['Alla']];
$regular = ['username' => 'vanlig', 'admin' => false, 'groups' => ['RIM1']];
$sneaky  = ['username' => 'smyg', 'admin' => false, 'groups' => [UPLOAD_GROUP]];
$guest   = ['username' => '__guest__', 'admin' => false, 'groups' => [GUEST_GROUP], 'is_guest' => true];
check('admin ser uppladdade spår', user_can_see(UPLOAD_GROUP, $admin));
check("användare i 'Alla' ser inte uppladdade spår", !user_can_see(UPLOAD_GROUP, $alla));
check('vanlig användare ser inte uppladdade spår', !user_can_see(UPLOAD_GROUP, $regular));
check('användare med gruppen uploaded ser dem inte heller', !user_can_see(UPLOAD_GROUP, $sneaky));
check('gäst ser inte uppladdade spår', !user_can_see(UPLOAD_GROUP, $guest));
check("oförändrat: 'Alla' ser andra grupper", user_can_see('RIM2', $alla));
check('oförändrat: vanlig användare ser sin grupp och spår utan grupp', user_can_see('RIM1', $regular) && user_can_see('', $regular));
check('oförändrat: gäst ser bara gästspår', user_can_see(GUEST_GROUP, $guest) && !user_can_see('', $guest));
check('UPLOAD_GROUP är ett giltigt gruppnamn', preg_match(GROUP_NAME_PATTERN, UPLOAD_GROUP) === 1);

echo "\nResultat: $pass OK, $fail FEL\n";
exit($fail === 0 ? 0 : 1);
