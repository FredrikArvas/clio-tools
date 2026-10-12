<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * tests/groups_store_test.php — test av admin/groups_store.php mot syntetiska fixture-filer.
 *
 * Körs lokalt eller på servern:  php tests/groups_store_test.php
 * Rör aldrig data/users.csv eller data/track_groups.csv: allt skrivs i en tillfällig katalog
 * som raderas vid avslut. Avslutskod 0 = alla tester gröna.
 *
 * Testar både lyckade och misslyckade vägar: validering (vitlista, injektion), att ofarliga
 * sparningar lämnar filerna byte för byte oförändrade, att bara grupp-kolumnen ändras,
 * skydd för sista admin och att inga tempfiler blir kvar.
 */

require_once dirname(__DIR__) . '/admin/groups_store.php';

$pass = 0;
$fail = 0;

function check(string $description, bool $condition): void {
    global $pass, $fail;
    if ($condition) { $pass++; echo "  OK    $description\n"; return; }
    $fail++;
    echo "  FEL   $description\n";
}

function make_fixture_dir(): string {
    $dir = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'groups_store_test_' . bin2hex(random_bytes(4));
    mkdir($dir . DIRECTORY_SEPARATOR . 'music', 0775, true);
    return $dir;
}

function remove_dir(string $dir): void {
    foreach (scandir($dir) as $entry) {
        if ($entry === '.' || $entry === '..') continue;
        $path = $dir . DIRECTORY_SEPARATOR . $entry;
        is_dir($path) ? remove_dir($path) : unlink($path);
    }
    rmdir($dir);
}

/** Speglar load_track_groups() i access.php men mot en fixture-fil (den läser en fast sökväg). */
function parse_fixture_map(string $path): array {
    $map = [];
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $parts = explode(';', $line, 2);
        if (count($parts) === 2) $map[trim($parts[0])] = trim($parts[1]);
    }
    return $map;
}

/** Skickar in det formuläret skulle skicka för en oförändrad sparning. */
function unchanged_selection(array $users): array {
    $submitted = [];
    foreach ($users as $username => $user) {
        foreach ($user['groups'] as $group) $submitted[$username][$group] = '1';
    }
    return $submitted;
}

$dir = make_fixture_dir();
register_shutdown_function(fn() => remove_dir($dir));
$users_path  = $dir . '/users.csv';
$tracks_path = $dir . '/track_groups.csv';

$hash_a = '$2y$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.';
$hash_b = '$2y$12$ZYXWVUTSRQPONMLKJIHGFEdcbaZYXWVUTSRQPONMLKJIHGFEDCBA.0123';
$users_lf = "# Användarfil\n# Format: användarnamn;hash;...\n#\n"
    . "roger;$hash_a;Roger G;1;1;Alla\n"
    . "fredrik;$hash_b;Fredrik A;1;1;Ljudvägg|RIM1|RIM2\n"
    . "ulrika;$hash_b;Ulrika A;1;0;RIM1\n"
    . "gammal;$hash_a;Gammal;0;0;\n"
    . "kort;$hash_a;Kort;1\n";

echo "== Namnvalidering\n";
foreach (['RIM1', 'Ulrikas_35_årslåt', 'Ljud-vägg', 'En grupp', str_repeat('x', 40)] as $name) {
    check("giltigt gruppnamn: $name", is_valid_group_name($name));
}
$bad_names = [
    'a;b' => 'semikolon', 'a|b' => 'pipe', "a\nb" => 'radbrytning i mitten', "RIM1\n" => 'avslutande radbrytning',
    "a\rb" => 'CR', 'a"b' => 'citattecken', "a'b" => 'apostrof', '<b>' => 'HTML', '' => 'tomt',
    ' ' => 'bara blanksteg', ' RIM1' => 'inledande blanksteg', 'RIM1 ' => 'avslutande blanksteg',
    str_repeat('x', 41) => '41 tecken', str_repeat('x', 200) => '200 tecken', "a\0b" => 'NUL', "\xff\xfe" => 'ogiltig UTF-8',
    '../x' => 'sökväg', '#kommentar' => 'kommentarstecken',
];
foreach ($bad_names as $name => $label) {
    check("avvisas: $label", !is_valid_group_name((string)$name));
}
check('filnamn med blanksteg och punkt är CSV-säkert', is_csv_safe_field('Aim for the Stars_Suno-version.mp3'));
foreach (["a;b.mp3", "a\nb.mp3", "a\rb.mp3", '#x.mp3', ''] as $name) {
    check('filnamn avvisas: ' . json_encode($name), !is_csv_safe_field($name));
}

echo "== users.csv: ofarlig sparning ändrar ingenting\n";
$variants = [
    'LF'                      => $users_lf,
    'CRLF'                    => str_replace("\n", "\r\n", $users_lf),
    'utan avslutande radslut' => rtrim($users_lf, "\n"),
];
foreach ($variants as $label => $content) {
    file_put_contents($users_path, $content);
    $users = read_admin_users($users_path);
    $known = collect_known_groups($users, []);
    [$new_groups, $error] = validate_user_group_selection($users, $known, unchanged_selection($users));
    $save_error = $error === '' ? save_user_groups($users_path, $new_groups) : $error;
    check("$label: ingen felkod", $save_error === '');
    check("$label: filen identisk byte för byte", file_get_contents($users_path) === $content);
}

echo "== users.csv: ändring rör bara grupp-kolumnen\n";
file_put_contents($users_path, $users_lf);
$users = read_admin_users($users_path);
$known = collect_known_groups($users, [], 'Nygrupp');
$submitted = unchanged_selection($users);
unset($submitted['fredrik']['RIM1']);          // fredrik tappar RIM1
$submitted['ulrika']['Nygrupp'] = '1';          // ulrika får en ny grupp
$submitted['gammal']['Gäst'] = '1';             // gammal (inaktiv, tom grupp-kolumn) får Gäst
$submitted['kort']['RIM2'] = '1';               // kort har bara 4 kolumner
[$new_groups, $error] = validate_user_group_selection($users, $known, $submitted);
check('giltig ändring validerar', $error === '');
check('ordning bevaras för befintliga grupper', $new_groups['fredrik'] === ['Ljudvägg', 'RIM2']);
check('save_user_groups ok', save_user_groups($users_path, $new_groups) === '');
$before = explode("\n", $users_lf);
$after  = explode("\n", file_get_contents($users_path));
check('lika många rader', count($before) === count($after));
check('kommentarsrader oförändrade', array_slice($after, 0, 3) === array_slice($before, 0, 3));
check('roger oförändrad', $after[3] === $before[3]);
check('fredrik: bara grupp-kolumnen ändrad', $after[4] === "fredrik;$hash_b;Fredrik A;1;1;Ljudvägg|RIM2");
check('ulrika fick ny grupp', $after[5] === "ulrika;$hash_b;Ulrika A;1;0;RIM1|Nygrupp");
check('gammal fick Gäst', $after[6] === "gammal;$hash_a;Gammal;0;0;Gäst");
check('kort paddades till 6 kolumner', $after[7] === "kort;$hash_a;Kort;1;;RIM2");
check('lösenordshashar finns kvar', str_contains(file_get_contents($users_path), $hash_a) && str_contains(file_get_contents($users_path), $hash_b));

echo "== users.csv: injektion och förfalskade fält avvisas, filen orörd\n";
file_put_contents($users_path, $users_lf);
$users = read_admin_users($users_path);
$known = collect_known_groups($users, []);
foreach (['a;b', "a\nb", 'a|b', str_repeat('x', 200), 'a"b'] as $name) {
    $label = json_encode(substr($name, 0, 20));
    check("save_user_groups avvisar direkt: $label", save_user_groups($users_path, ['roger' => [$name]]) !== '');
}
check('filen oförändrad efter avvisade försök', file_get_contents($users_path) === $users_lf);
[, $error] = validate_user_group_selection($users, $known, ['roger' => ['Hittepå' => '1']]);
check('okänd grupp i ug avvisas', $error !== '');
[, $error] = validate_user_group_selection($users, $known, ['hittepa' => ['RIM1' => '1']]);
check('okänd användare i ug avvisas', $error !== '');
[, $error] = validate_user_group_selection($users, $known, ['roger' => 'RIM1']);
check('ug med fel form avvisas', $error !== '');
[, $error] = validate_user_group_selection($users, $known, 'x');
check('ug som inte är array avvisas', $error !== '');
[, $error] = validate_user_group_selection($users, array_merge($known, ['evil;group']), []);
check('äldre ogiltigt gruppnamn i kända grupper stoppar sparning', $error !== '');

echo "== users.csv: sista admin skyddas\n";
$no_admin = str_replace(';1;1;', ';1;0;', $users_lf);
file_put_contents($users_path, $no_admin);
$result = save_user_groups($users_path, ['ulrika' => ['RIM1', 'RIM2']]);
check('sparning utan aktiv admin avvisas', $result !== '');
check('filen oförändrad', file_get_contents($users_path) === $no_admin);
check('find_missing_admin: inaktiv admin räknas inte', find_missing_admin("a;h;A;0;1;x\n") !== '');
check('find_missing_admin: aktiv admin ok', find_missing_admin("a;h;A;1;1;x\n") === '');

echo "== users.csv: citerade fält skrivs inte om\n";
$quoted = "# k\nroger;$hash_a;\"Roger; G\";1;1;Alla\n";
file_put_contents($users_path, $quoted);
$result = save_user_groups($users_path, ['roger' => ['Alla', 'RIM1']]);
check('rad med citerat fält avvisas', $result !== '');
check('filen oförändrad', file_get_contents($users_path) === $quoted);

echo "== track_groups.csv\n";
$music_dir = $dir . '/music';
foreach (['a_msc.mp3', 'a_vce.mp3', 'b.mp3', 'Aim for the Stars.mp3', 'sem;ikolon.mp3', 'x.txt'] as $name) {
    touch($music_dir . '/' . $name);
}
$music_files = list_music_files($music_dir);
check('list_music_files: bara mp3, inklusive kanalfiler', $music_files === ['Aim for the Stars.mp3', 'a_msc.mp3', 'a_vce.mp3', 'b.mp3', 'sem;ikolon.mp3']);
$tracks_lf = "# Låt-grupptillhörighet\n# kommentar\na_msc.mp3;RIM1\nAim;Ljudvägg\nb.mp3;RIM2\n";
file_put_contents($tracks_path, $tracks_lf);
$map = parse_fixture_map($tracks_path);
$known = collect_known_groups(['x' => ['groups' => ['RIM1', 'RIM2', 'Ljudvägg']]], $map);

$current = [];
foreach ($music_files as $file) $current[$file] = track_group($file, $map);
unset($current['sem;ikolon.mp3']);   // formuläret kan inte skicka ett osparbart filnamn
[$assignments, $error] = validate_track_assignments($current, $music_files, $known);
check('oförändrat formulär validerar', $error === '');
check('ofarlig sparning ger ingen felkod', save_track_groups($tracks_path, $assignments, $map) === '');
check('ofarlig sparning: filen identisk (prefixregel + exakta rader)', file_get_contents($tracks_path) === $tracks_lf);

$changed = $assignments;
$changed['b.mp3'] = 'Ljudvägg';
$changed['Aim for the Stars.mp3'] = '';     // prefixregeln 'Aim' ger Ljudvägg → ska övertrumfas av tom rad
$changed['a_vce.mp3'] = 'RIM2';
check('ändring sparas', save_track_groups($tracks_path, $changed, $map) === '');
$new_map = parse_fixture_map($tracks_path);
check('b.mp3 → Ljudvägg', track_group('b.mp3', $new_map) === 'Ljudvägg');
check('Aim for the Stars.mp3 → ingen grupp trots prefixregel', track_group('Aim for the Stars.mp3', $new_map) === '');
check('a_vce.mp3 → RIM2', track_group('a_vce.mp3', $new_map) === 'RIM2');
check('a_msc.mp3 oförändrad', track_group('a_msc.mp3', $new_map) === 'RIM1');
check('prefixregeln finns kvar', ($new_map['Aim'] ?? '') === 'Ljudvägg');
check('kommentarsrader kvar', str_contains(file_get_contents($tracks_path), "# kommentar\n"));
check('describe_track_group_changes hittar 3 ändringar', count(describe_track_group_changes($changed, $map)) === 3);

echo "== track_groups.csv: avvisade indata\n";
[, $error] = validate_track_assignments(['hittepa.mp3' => ''], $music_files, $known);
check('okänd fil avvisas', $error !== '');
[, $error] = validate_track_assignments(['../users.csv' => ''], $music_files, $known);
check('sökväg i filnamn avvisas', $error !== '');
[, $error] = validate_track_assignments(['b.mp3' => 'Hittepå'], $music_files, $known);
check('okänd grupp avvisas', $error !== '');
[, $error] = validate_track_assignments(['b.mp3' => 'Alla'], $music_files, $known);
check("gruppen 'Alla' kan inte tilldelas ett spår", $error !== '');
[, $error] = validate_track_assignments(['b.mp3' => ['x']], $music_files, $known);
check('grupp som array avvisas', $error !== '');
[, $error] = validate_track_assignments(['sem;ikolon.mp3' => ''], $music_files, $known);
check('filnamn med semikolon avvisas', $error !== '');
$before_bad = file_get_contents($tracks_path);
check('save_track_groups avvisar grupp med semikolon', save_track_groups($tracks_path, ['b.mp3' => 'a;b'], $new_map) !== '');
check('save_track_groups avvisar radbrytning i filnamn', save_track_groups($tracks_path, ["b\n.mp3" => 'RIM1'], $new_map) !== '');
check('filen oförändrad efter avvisade försök', file_get_contents($tracks_path) === $before_bad);

echo "== track_groups.csv: ny fil får rubrikrader\n";
$fresh_path = $dir . '/fresh_track_groups.csv';
check('skapar fil', save_track_groups($fresh_path, ['b.mp3' => 'RIM1'], []) === '');
check('rubrik + rad', file_get_contents($fresh_path) === implode("\n", TRACK_GROUPS_HEADER) . "\nb.mp3;RIM1\n");

echo "== Filhantering\n";
$leftovers = array_filter(scandir($dir), fn($entry) => str_contains($entry, '.tmp'));
check('inga tempfiler blir kvar', $leftovers === []);
check('låsfiler skapas bredvid datafilerna', is_file($tracks_path . '.lock'));
if (PHP_OS_FAMILY !== 'Windows') {
    $mode_path = $dir . '/mode.csv';
    file_put_contents($mode_path, "x;1\n");
    chmod($mode_path, 0644);
    write_file_atomically($mode_path, "y;2\n");
    check('filrättigheter bevaras', (fileperms($mode_path) & 0777) === 0644);
}
check('skrivning till ej skrivbar katalog ger fel', write_file_atomically($dir . '/finns_inte/x.csv', 'x') !== '');

echo "\nResultat: $pass OK, $fail FEL\n";
exit($fail === 0 ? 0 : 1);
