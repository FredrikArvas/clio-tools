<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * auth.php — sessioner, inloggning och användarmodell.
 *
 * Anropas av: alla PHP-sidor och API:er (require_once). Att inkludera filen startar sessionen.
 *
 * Säkerhetsantaganden:
 * - Sessionscookien är HttpOnly, SameSite=Lax och Secure när begäran kom över HTTPS
 *   (via Cloudflare, se client_ip.php). Vid lokal HTTP-test är Secure av, annars fungerar inget.
 * - use_strict_mode: PHP vägrar sessions-id som servern inte själv har skapat (session fixation).
 * - Sessions-id byts vid inloggning (login_user) och sessionen töms helt vid utloggning.
 * - Inloggade sessioner har absolut livslängd och inaktivitetsgräns (se konstanterna).
 * - Okända användarnamn kör ändå password_verify mot en dummy-hash, så att svarstiden inte
 *   avslöjar vilka konton som finns.
 */

require_once __DIR__ . '/client_ip.php';
require_once __DIR__ . '/audit.php';

const SESSION_ABSOLUTE_TIMEOUT = 12 * 3600;
// Debians cron-städning (phpsessionclean) raderar sessionsfiler som inte rörts på
// php.ini:s session.gc_maxlifetime (1440 s på servern), oavsett vad koden säger.
// Inaktivitetsgränsen läses därför därifrån, så att koden inte lovar mer än servern håller.
define('SESSION_IDLE_TIMEOUT', (int)ini_get('session.gc_maxlifetime') ?: 1440);

const PASSWORD_HASH_OPTIONS = ['cost' => 12];
// Hash av ett slumpat, kastat lösenord, med samma kostnad som riktiga hashar. Används bara för
// att okända användarnamn ska ta lika lång tid som kända.
const DUMMY_PASSWORD_HASH = '$2y$12$98euiq9J4MIRmVn4MK5wLuvtLOj/h4SSjjjDDpj/XDcCdNqzSJ7uK';

function start_session(): void {
    if (session_status() === PHP_SESSION_ACTIVE) return;
    ini_set('session.use_strict_mode', '1');
    ini_set('session.use_only_cookies', '1');
    session_set_cookie_params([
        'lifetime' => 0,
        'path'     => '/',
        'secure'   => request_is_https(),
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    session_start();
    enforce_session_timeouts();
}

/** Loggar ut inloggade sessioner som passerat absolut- eller inaktivitetsgränsen. */
function enforce_session_timeouts(): void {
    if (empty($_SESSION['cm_user'])) return;
    $now = time();
    $_SESSION['cm_created'] ??= $now;   // sessioner från före v1.5.1 saknar tidsstämpel
    $is_expired = $now - $_SESSION['cm_created'] > SESSION_ABSOLUTE_TIMEOUT
        || $now - ($_SESSION['cm_last_seen'] ?? $now) > SESSION_IDLE_TIMEOUT;
    if ($is_expired) {
        audit_log('session_expired');
        $_SESSION = [];
        session_regenerate_id(true);
        return;
    }
    $_SESSION['cm_last_seen'] = $now;
}

function is_logged_in(): bool {
    return !empty($_SESSION['cm_user']);
}

function require_login(): void {
    if (!is_logged_in()) {
        header('Location: /login.php');   // absolut: anropas även från admin/
        exit;
    }
}

function current_user(): array {
    return $_SESSION['cm_user'] ?? [];
}

function guest_user(): array {
    return [
        'username' => '__guest__',
        'display'  => 'Gäst',
        'admin'    => false,
        'groups'   => ['Gäst'],
        'is_guest' => true,
    ];
}

function is_guest(array $user): bool {
    return !empty($user['is_guest']);
}

function current_user_or_guest(): array {
    return is_logged_in() ? current_user() : guest_user();
}

function load_users(): array {
    $path = __DIR__ . '/data/users.csv';
    if (!file_exists($path)) return [];
    $users = [];
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $parts = str_getcsv($line, ';');
        if (count($parts) < 4) continue;
        [$username, $hash, $display, $active] = $parts;
        $admin  = isset($parts[4]) ? (int)trim($parts[4]) : 0;
        $groups = isset($parts[5]) ? array_map('trim', explode('|', $parts[5])) : [];
        if ((int)$active === 1) {
            $users[strtolower(trim($username))] = [
                'hash'    => trim($hash),
                'display' => trim($display),
                'admin'   => $admin,
                'groups'  => $groups,
            ];
        }
    }
    return $users;
}

function verify_login(string $username, string $password): ?array {
    $users  = load_users();
    $key    = strtolower(trim($username));
    $record = $users[$key] ?? null;
    // Kör alltid password_verify, även för okända namn: jämn svarstid.
    $is_valid = password_verify($password, $record['hash'] ?? DUMMY_PASSWORD_HASH);
    if ($record === null || !$is_valid) return null;
    if (password_needs_rehash($record['hash'], PASSWORD_BCRYPT, PASSWORD_HASH_OPTIONS)) {
        $new_hash = password_hash($password, PASSWORD_BCRYPT, PASSWORD_HASH_OPTIONS);
        $saved    = save_user_hash($key, $new_hash);
        audit_log($saved ? 'password_rehashed' : 'password_rehash_needed', ['username' => $key]);
    }
    return ['username' => $key, 'display' => $record['display'], 'admin' => $record['admin'], 'groups' => $record['groups']];
}

/**
 * Byter hash-kolumnen (index 1) för $username i data/users.csv atomiskt.
 * Alla andra kolumner och rader skrivs tillbaka byte för byte.
 * Använder samma låsfil som admin/groups_store.php för att undvika konflikter.
 * Returnerar true vid lyckat resultat, false annars.
 */
function save_user_hash(string $username, string $new_hash): bool {
    if (strpbrk($new_hash, ";\r\n") !== false) {
        error_log('clio_music: ogiltig teckenuppsättning i ny hash för ' . $username);
        return false;
    }
    $path = __DIR__ . '/data/users.csv';
    $lock = @fopen($path . '.lock', 'c');
    if ($lock === false || !flock($lock, LOCK_EX)) {
        error_log('clio_music: kunde inte ta lås för users.csv (rehash)');
        if ($lock !== false) fclose($lock);
        return false;
    }
    $success = false;
    try {
        $raw = is_file($path) ? file_get_contents($path) : false;
        if ($raw === false) {
            error_log('clio_music: users.csv saknas vid rehash av ' . $username);
            return false;
        }
        $lines   = explode("\n", $raw);
        $matched = false;
        foreach ($lines as $i => $line) {
            $has_cr = str_ends_with($line, "\r");
            $body   = $has_cr ? substr($line, 0, -1) : $line;
            if (trim($body) === '' || str_starts_with(trim($body), '#')) continue;
            $fields = explode(';', $body);
            if (count($fields) < 2 || strtolower(trim($fields[0])) !== $username) continue;
            $fields[1] = $new_hash;
            $lines[$i] = implode(';', $fields) . ($has_cr ? "\r" : '');
            $matched   = true;
            break;
        }
        if (!$matched) {
            error_log('clio_music: hittade inte användaren "' . $username . '" i users.csv (rehash)');
            return false;
        }
        $content = implode("\n", $lines);
        $dir     = dirname($path);
        $tmp     = is_writable($dir) ? tempnam($dir, 'users.tmp') : false;
        if ($tmp === false) {
            error_log('clio_music: kunde inte skapa tempfil i data/ för rehash');
            return false;
        }
        $mode    = is_file($path) ? (fileperms($path) & 0777) : 0640;
        $success = file_put_contents($tmp, $content, LOCK_EX) === strlen($content)
                && chmod($tmp, $mode)
                && rename($tmp, $path);
        if (!$success) {
            error_log('clio_music: skrivning av users.csv (rehash) misslyckades');
            if (is_file($tmp)) unlink($tmp);
        }
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
    return $success;
}

/** Gör sessionen inloggad. Nytt sessions-id och ny CSRF-token förhindrar session fixation. */
function login_user(array $user): void {
    session_regenerate_id(true);
    $_SESSION = [
        'cm_user'      => $user,
        'cm_created'   => time(),
        'cm_last_seen' => time(),
    ];
}

/** Töm sessionen, radera cookien och förstör sessionsfilen. */
function logout_user(): void {
    $_SESSION = [];
    $params = session_get_cookie_params();
    setcookie(session_name(), '', [
        'expires'  => time() - 3600,
        'path'     => $params['path'],
        'secure'   => $params['secure'],
        'httponly' => $params['httponly'],
        'samesite' => $params['samesite'],
    ]);
    session_destroy();
}

start_session();
