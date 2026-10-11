<?php
/**
 * admin/groups_store.php — läsning, validering och säker skrivning av användar- och spårgrupper.
 *
 * Anropas av: admin/groups.php (vyn) och tests/groups_store_test.php. Filen har inga
 * bieffekter vid inläsning och rör varken session, header eller utskrift, så den går att
 * testa med php CLI mot fixture-filer.
 *
 * Säkerhetsantaganden:
 * - Allt som skrivs till data/users.csv eller data/track_groups.csv har först validerats här
 *   (vitlista för gruppnamn, "CSV-säkert" för filnamn). Inget fält får innehålla ; | CR LF.
 * - Servern litar aldrig på formulärets dolda fält: användare, grupper och filer måste finnas
 *   i de kända mängderna (users.csv, track_groups.csv, music/) eller vara ett giltigt nytt namn.
 * - Skrivning är atomisk (tempfil i samma katalog + rename) och serialiserad med flock på en
 *   separat låsfil, så att två samtidiga sparningar inte kan blanda ihop varandra och ett
 *   avbrott aldrig lämnar en halv fil.
 * - Rader som inte ändras skrivs tillbaka byte för byte (kommentarer, lösenordshashar,
 *   radslut). Bara grupp-kolumnen i users.csv ändras.
 * - Reglerna för vilken grupp ett spår har kommer från access.php (track_group), så att
 *   admin ser exakt det stream.php tillämpar.
 * - Servern saknar mbstring: inga mb_*-funktioner här.
 *
 * Felkonvention: funktioner som skriver returnerar '' vid lyckat resultat, annars ett
 * felmeddelande på svenska (visas för admin). Tekniska detaljer går till error_log.
 */

require_once dirname(__DIR__) . '/config.php';
require_once dirname(__DIR__) . '/access.php';

const ALL_USERS_GROUP     = 'Alla';
const USERS_GROUP_COLUMN  = 5;   // users.csv: användarnamn;hash;visningsnamn;aktiv;admin;grupper
const USERS_MIN_COLUMNS   = 4;
const TRACK_GROUPS_HEADER = [
    '# Låt-grupptillhörighet',
    '# Format: filnamn.mp3;grupp  (sparat av admin-gränssnittet)',
    '# Låtar utan rad visas för alla inloggade.',
];

// ── Validering ────────────────────────────────────────────────────────────────

/** Gruppnamn enligt vitlistan i config.php, utan inledande/avslutande blanksteg. */
function is_valid_group_name(string $name): bool {
    return $name === trim($name) && $name !== '' && preg_match(GROUP_NAME_PATTERN, $name) === 1;
}

/**
 * Får värdet skrivas som ett fält i en ;-avgränsad rad? Förbjuder avgränsare, radbrytningar,
 * NUL och inledande # (skulle tolkas som kommentarsrad). Används för filnamn, som kommer från
 * filsystemet och därför inte följer gruppnamnens vitlista.
 */
function is_csv_safe_field(string $value): bool {
    return $value !== '' && $value[0] !== '#' && preg_match('/[;\r\n\0]/', $value) !== 1;
}

// ── Läsning ───────────────────────────────────────────────────────────────────

/** Alla användare i users.csv (även inaktiva): [användarnamn => [display, active, admin, groups]]. */
function read_admin_users(string $users_path): array {
    $users = [];
    $lines = is_file($users_path) ? file($users_path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) : false;
    if ($lines === false) return $users;
    foreach ($lines as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $fields = str_getcsv($line, ';');
        if (count($fields) < USERS_MIN_COLUMNS) continue;
        $users[strtolower(trim($fields[0]))] = [
            'display' => trim($fields[2]),
            'active'  => (int)$fields[3],
            'admin'   => isset($fields[4]) ? (int)trim($fields[4]) : 0,
            'groups'  => parse_group_field($fields[USERS_GROUP_COLUMN] ?? ''),
        ];
    }
    return $users;
}

/** "A|B| C" → ['A', 'B', 'C']; tomt fält → []. */
function parse_group_field(string $field): array {
    if (trim($field) === '') return [];
    return array_values(array_map('trim', explode('|', $field)));
}

/** Spårfilerna i music/ (samma uppsättning som stream.php och index.php ser via scan_music). */
function list_music_files(string $music_dir): array {
    $scan  = scan_music($music_dir);
    $files = $scan['standalone'];
    foreach ($scan['channels'] as $channel_files) {
        $files = array_merge($files, array_values($channel_files));
    }
    sort($files);
    return $files;
}

/**
 * Den kända gruppmängden: gäst-gruppen, grupper som någon användare har och grupper som något
 * spår har. $extra_group är ett nytt, redan validerat namn som admin just skrivit in.
 */
function collect_known_groups(array $users, array $track_map, string $extra_group = ''): array {
    $groups = [GUEST_GROUP];
    foreach ($users as $user) {
        $groups = array_merge($groups, $user['groups']);
    }
    $groups = array_merge($groups, array_values($track_map));
    if ($extra_group !== '') $groups[] = $extra_group;
    $groups = array_values(array_unique(array_filter($groups, fn($group) => $group !== '')));
    sort($groups);
    return $groups;
}

/** Kända grupper som bryter mot vitlistan (äldre handredigerade data). Tom lista = allt ok. */
function find_invalid_group_names(array $groups): array {
    return array_values(array_filter($groups, fn($group) => !is_valid_group_name($group)));
}

// ── Validering av inskickade formulär ────────────────────────────────────────

/**
 * Validerar ug[användare][grupp]=1 mot kända användare och grupper. Okända nycklar avvisar hela
 * begäran (ett bortglömt eller förfalskat fält ska inte tyst ge fel behörigheter).
 * Returnerar [nya grupper per användare, felmeddelande]. Ordningen bevaras för grupper som
 * användaren redan har, så att en ofarlig sparning inte ändrar filen.
 */
function validate_user_group_selection(array $users, array $known_groups, mixed $submitted): array {
    if (!is_array($submitted)) return [[], 'Ogiltigt formulär.'];
    $invalid = find_invalid_group_names($known_groups);
    if ($invalid) {
        return [[], 'Gruppnamnet "' . $invalid[0] . '" följer inte namnreglerna. Rätta det i datafilerna först.'];
    }
    foreach ($submitted as $username => $checked) {
        if (!isset($users[(string)$username]) || !is_array($checked)) {
            return [[], 'Okänd användare i formuläret. Ladda om sidan.'];
        }
        foreach (array_keys($checked) as $group) {
            if (!in_array((string)$group, $known_groups, true)) {
                return [[], 'Okänd grupp i formuläret. Ladda om sidan.'];
            }
        }
    }
    $new_groups = [];
    foreach ($users as $username => $user) {
        $flags   = $submitted[$username] ?? [];
        $checked = array_map('strval', array_keys(array_filter($flags, fn($flag) => !empty($flag))));
        $kept    = array_values(array_filter($user['groups'], fn($group) => in_array($group, $checked, true)));
        $added   = array_values(array_filter(
            $known_groups,
            fn($group) => in_array($group, $checked, true) && !in_array($group, $kept, true)
        ));
        $new_groups[(string)$username] = array_merge($kept, $added);
    }
    return [$new_groups, ''];
}

/**
 * Validerar tg[filnamn]=grupp. Filen måste finnas i music/, gruppen vara tom ("alla inloggade")
 * eller en känd grupp (men inte 'Alla'). Returnerar [filnamn => grupp, felmeddelande].
 */
function validate_track_assignments(mixed $submitted, array $music_files, array $known_groups): array {
    if (!is_array($submitted)) return [[], 'Ogiltigt formulär.'];
    $assignable  = array_values(array_diff($known_groups, [ALL_USERS_GROUP]));
    $assignments = [];
    foreach ($submitted as $filename => $group) {
        $filename = (string)$filename;
        if (basename($filename) !== $filename || !in_array($filename, $music_files, true)) {
            return [[], 'Okänd låt i formuläret. Ladda om sidan.'];
        }
        if (!is_csv_safe_field($filename)) {
            return [[], 'Filnamnet "' . $filename . '" innehåller tecken som inte kan sparas.'];
        }
        if (!is_string($group) || ($group !== '' && !in_array($group, $assignable, true))) {
            return [[], 'Okänd grupp för låten "' . $filename . '".'];
        }
        $assignments[$filename] = $group;
    }
    return [$assignments, ''];
}

// ── Ändringsbeskrivningar till auditloggen ───────────────────────────────────

/** [användare => ['added' => [...], 'removed' => [...]]] för användare vars grupper ändras. */
function describe_user_group_changes(array $users, array $new_groups): array {
    $changes = [];
    foreach ($new_groups as $username => $groups) {
        $before  = $users[$username]['groups'] ?? [];
        $added   = array_values(array_diff($groups, $before));
        $removed = array_values(array_diff($before, $groups));
        if ($added || $removed) $changes[$username] = ['added' => $added, 'removed' => $removed];
    }
    return $changes;
}

/** [filnamn => ['from' => gammal grupp, 'to' => ny grupp]] för spår vars effektiva grupp ändras. */
function describe_track_group_changes(array $assignments, array $current_map): array {
    $changes = [];
    foreach ($assignments as $filename => $group) {
        $before = track_group($filename, $current_map);
        if ($before !== $group) $changes[$filename] = ['from' => $before, 'to' => $group];
    }
    return $changes;
}

// ── Skrivning: users.csv ─────────────────────────────────────────────────────

/**
 * Sparar användarnas grupper i users.csv. Ändrar bara grupp-kolumnen på rader där listan
 * faktiskt skiljer sig; allt annat skrivs tillbaka oförändrat. Vägrar skriva om resultatet
 * saknar en aktiv admin.
 */
function save_user_groups(string $users_path, array $new_groups): string {
    foreach ($new_groups as $groups) {
        if (find_invalid_group_names($groups)) return 'Ogiltigt gruppnamn avvisades.';
    }
    return with_file_lock($users_path, function () use ($users_path, $new_groups): string {
        $raw = is_file($users_path) ? file_get_contents($users_path) : false;
        if ($raw === false) return 'Filen users.csv saknas eller kan inte läsas.';
        $lines = explode("\n", $raw);   // sista elementet är '' om filen slutar med radbrytning
        foreach ($lines as $index => $line) {
            $result = rewrite_user_line($line, $new_groups);
            if ($result['error'] !== '') return $result['error'];
            $lines[$index] = $result['line'];
        }
        $content = implode("\n", $lines);
        $error   = find_missing_admin($content);
        return $error !== '' ? $error : write_file_atomically($users_path, $content);
    });
}

/** En rad i users.csv → ['line' => ny rad, 'error' => '']. Orörda rader returneras identiska. */
function rewrite_user_line(string $line, array $new_groups): array {
    $has_cr    = str_ends_with($line, "\r");
    $body      = $has_cr ? substr($line, 0, -1) : $line;
    $unchanged = ['line' => $line, 'error' => ''];
    if (trim($body) === '' || str_starts_with(trim($body), '#')) return $unchanged;
    $parsed   = str_getcsv($body, ';');
    $username = strtolower(trim((string)$parsed[0]));
    if (count($parsed) < USERS_MIN_COLUMNS || !isset($new_groups[$username])) return $unchanged;
    if (parse_group_field((string)($parsed[USERS_GROUP_COLUMN] ?? '')) === $new_groups[$username]) return $unchanged;
    $fields = explode(';', $body);
    if (count($fields) !== count($parsed)) {
        // Citerade fält: att bygga om raden skulle kunna ändra hashen eller visningsnamnet.
        error_log('clio_music: users.csv-raden för "' . $username . '" har citerade fält och skrivs inte om');
        return ['line' => $line, 'error' => 'Raden för "' . $username . '" i users.csv har ett format som inte kan skrivas om säkert.'];
    }
    while (count($fields) <= USERS_GROUP_COLUMN) $fields[] = '';
    $fields[USERS_GROUP_COLUMN] = implode('|', $new_groups[$username]);
    return ['line' => implode(';', $fields) . ($has_cr ? "\r" : ''), 'error' => ''];
}

/** Felmeddelande om ingen aktiv admin (aktiv=1, admin=1) finns i filinnehållet, annars ''. */
function find_missing_admin(string $content): string {
    foreach (explode("\n", $content) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $fields = str_getcsv(rtrim($line, "\r"), ';');
        if (count($fields) >= 5 && (int)$fields[3] === 1 && (int)trim((string)$fields[4]) === 1) return '';
    }
    return 'Minst en aktiv admin måste finnas kvar. Ändringen sparades inte.';
}

// ── Skrivning: track_groups.csv ──────────────────────────────────────────────

/**
 * Sparar spårens grupper i track_groups.csv. $assignments är [filnamn => grupp] för de spår som
 * formuläret skickade; '' betyder "ingen grupp". $current_map är load_track_groups() från access.php.
 * Rader för andra nycklar (prefixregler, kommentarer, spår som inte skickades) behålls oförändrade,
 * och rader vars grupp inte ändras ligger kvar på samma plats.
 */
function save_track_groups(string $tracks_path, array $assignments, array $current_map): string {
    foreach ($assignments as $filename => $group) {
        if (!is_csv_safe_field((string)$filename) || ($group !== '' && !is_valid_group_name($group))) {
            return 'Ogiltigt filnamn eller gruppnamn avvisades.';
        }
    }
    return with_file_lock($tracks_path, function () use ($tracks_path, $assignments, $current_map): string {
        $raw   = is_file($tracks_path) ? file_get_contents($tracks_path) : false;
        $lines = $raw === false ? TRACK_GROUPS_HEADER : explode("\n", rtrim($raw, "\n"));
        [$kept, $unchanged] = split_track_lines($lines, $assignments, $current_map);
        $new_lines = build_changed_track_lines($assignments, $unchanged, $kept);
        array_splice($kept, find_first_data_line($kept), 0, $new_lines);
        return write_file_atomically($tracks_path, implode("\n", $kept) . "\n");
    });
}

/**
 * Delar filens rader i de som behålls och de som ersätts. Returnerar [behållna rader, filnamn
 * vars befintliga rad redan har rätt grupp]. Rader för inskickade spår vars grupp ändras (och
 * dubbletter) tas bort här; nya rader byggs i build_changed_track_lines.
 */
function split_track_lines(array $lines, array $assignments, array $current_map): array {
    $kept      = [];
    $unchanged = [];
    $seen      = [];
    foreach ($lines as $line) {
        $key     = trim(explode(';', $line, 2)[0]);
        $is_data = $key !== '' && !str_starts_with($key, '#');
        if (!$is_data || !array_key_exists($key, $assignments)) {
            $kept[] = $line;
            continue;
        }
        $is_first = !isset($seen[$key]);
        $seen[$key] = true;
        if ($is_first && ($current_map[$key] ?? null) === $assignments[$key]) {
            $kept[] = $line;   // rätt grupp redan: ligger kvar byte för byte
            $unchanged[$key] = true;
        }
    }
    return [$kept, $unchanged];
}

/**
 * Nya rader för spår vars grupp ändrats: 'fil;grupp', eller 'fil;' (uttryckligen ingen grupp)
 * när en kvarvarande prefixregel annars skulle ge spåret en grupp. Ingen rad behövs när
 * spåret redan får rätt grupp via en prefixregel.
 */
function build_changed_track_lines(array $assignments, array $unchanged, array $kept_lines): array {
    $rules = [];   // regler som gäller när spårets egen rad tagits bort
    foreach ($kept_lines as $line) {
        $parts = explode(';', $line, 2);
        $key   = trim($parts[0]);
        if (count($parts) === 2 && $key !== '' && !str_starts_with($key, '#') && !array_key_exists($key, $assignments)) {
            $rules[$key] = trim($parts[1]);
        }
    }
    $new_lines = [];
    foreach ($assignments as $filename => $group) {
        if (isset($unchanged[$filename]) || $group === track_group($filename, $rules)) continue;
        $new_lines[] = $filename . ';' . $group;
    }
    return $new_lines;
}

/**
 * Index för första datarad: nya filnamnsrader läggs före den, så att de kommer först i kartan
 * som load_track_groups() bygger och därmed vinner över bredare prefixregler (track_group tar
 * första träffen). Finns ingen datarad hamnar de sist.
 */
function find_first_data_line(array $lines): int {
    foreach ($lines as $index => $line) {
        $key = trim(explode(';', $line, 2)[0]);
        if ($key !== '' && !str_starts_with($key, '#')) return $index;
    }
    return count($lines);
}

// ── Filhantering ─────────────────────────────────────────────────────────────

/**
 * Kör $callback under exklusivt lås på en separat låsfil. Låsfilen behövs eftersom rename()
 * byter ut själva datafilen: ett lås på datafilen skulle följa med den gamla inoden.
 */
function with_file_lock(string $path, callable $callback): string {
    $lock = fopen($path . '.lock', 'c');
    if ($lock === false || !flock($lock, LOCK_EX)) {
        error_log('clio_music: kunde inte ta lås för ' . basename($path));
        return 'Kunde inte låsa filen. Försök igen.';
    }
    try {
        return $callback();
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

/**
 * Skriver via tempfil i samma katalog + rename (atomiskt på samma filsystem). Behåller filens
 * rättigheter. Katalogen måste vara skrivbar: tempnam() skulle annars tyst lägga tempfilen i
 * systemets tempkatalog, och rename dit är inte atomisk.
 */
function write_file_atomically(string $path, string $content): string {
    $directory = dirname($path);
    $temp_path = is_writable($directory) ? tempnam($directory, basename($path) . '.tmp') : false;
    if ($temp_path === false) {
        error_log('clio_music: kunde inte skapa tempfil i katalogen för ' . basename($path));
        return 'Kunde inte skriva ' . basename($path) . '.';
    }
    $mode       = is_file($path) ? (fileperms($path) & 0777) : 0640;
    $is_written = file_put_contents($temp_path, $content, LOCK_EX) === strlen($content)
        && chmod($temp_path, $mode)
        && rename($temp_path, $path);
    if (!$is_written) {
        error_log('clio_music: skrivning av ' . basename($path) . ' misslyckades');
        if (is_file($temp_path)) unlink($temp_path);
        return 'Kunde inte skriva ' . basename($path) . '.';
    }
    return '';
}
