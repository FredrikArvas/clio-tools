<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * login_throttle.php — spärr mot lösenordsgissning (brute force) utan databas.
 *
 * Anropas av: login.php — `login_lock_remaining()` före lösenordskontrollen,
 * `login_record_failure()` vid fel, `login_record_success()` vid lyckad inloggning.
 *
 * Princip: räknare per användarnamn OCH per klient-IP (client_ip.php), som JSON-filer i
 * data/login_attempts/. Efter LOGIN_FREE_ATTEMPTS fel spärras nyckeln i en tid som dubblas
 * för varje nytt fel (max LOGIN_MAX_LOCK_SECONDS). Räknaren nollas efter LOGIN_RESET_SECONDS
 * utan fel, eller vid lyckad inloggning.
 *
 * Säkerhetsantaganden:
 * - Spärren gäller lika för existerande och påhittade användarnamn, så den avslöjar inte
 *   vilka konton som finns.
 * - IP-gränsen är högre än namngränsen: flera hushållsmedlemmar kan dela publik IP.
 * - Filnamnen är sha256 av nyckeln: användarinmatning når aldrig filsystemet som sökväg.
 * - Detta kompletteras av nginx limit_req på POST /login.php (grov hastighetsgräns).
 */

require_once __DIR__ . '/client_ip.php';
require_once __DIR__ . '/json_store.php';

const LOGIN_ATTEMPTS_DIR       = __DIR__ . '/data/login_attempts';
const LOGIN_FREE_ATTEMPTS      = 5;      // per användarnamn
const LOGIN_FREE_ATTEMPTS_IP   = 20;     // per IP
const LOGIN_BASE_LOCK_SECONDS  = 30;
const LOGIN_MAX_LOCK_SECONDS   = 900;
const LOGIN_RESET_SECONDS      = 3600;

function login_throttle_keys(string $username): array {
    return ['user:' . strtolower(trim($username)), 'ip:' . client_ip()];
}

function login_attempt_file(string $key): string {
    return LOGIN_ATTEMPTS_DIR . '/' . hash('sha256', $key) . '.json';
}

function login_read_attempts(string $key): array {
    $empty = ['failures' => 0, 'last_failure' => 0, 'locked_until' => 0];
    $path  = login_attempt_file($key);
    if (!is_file($path)) return $empty;
    $data = json_decode((string)file_get_contents($path), true);
    if (!is_array($data) || time() - (int)($data['last_failure'] ?? 0) > LOGIN_RESET_SECONDS) return $empty;
    return $data + $empty;
}

/** Sekunder kvar av spärren för detta användarnamn eller denna IP (0 = inte spärrad). */
function login_lock_remaining(string $username): int {
    $remaining = 0;
    foreach (login_throttle_keys($username) as $key) {
        $remaining = max($remaining, login_read_attempts($key)['locked_until'] - time());
    }
    return max(0, $remaining);
}

function login_record_failure(string $username): void {
    if (!is_dir(LOGIN_ATTEMPTS_DIR) && !mkdir(LOGIN_ATTEMPTS_DIR, 0770, true) && !is_dir(LOGIN_ATTEMPTS_DIR)) {
        error_log('clio_music: kan inte skapa ' . LOGIN_ATTEMPTS_DIR . ' — spärren mot inloggningsförsök fungerar inte');
        return;
    }
    foreach (login_throttle_keys($username) as $key) {
        $free_attempts = str_starts_with($key, 'ip:') ? LOGIN_FREE_ATTEMPTS_IP : LOGIN_FREE_ATTEMPTS;
        login_increment_attempts($key, $free_attempts);
    }
}

/**
 * Läs-ändra-skriv under exklusivt fil-lås (json_store.php). Utan låset kunde parallella
 * gissningar läsa samma räknarvärde och tillsammans bara räknas som ett fel.
 */
function login_increment_attempts(string $key, int $free_attempts): void {
    $is_saved = json_file_update(login_attempt_file($key), function (array $attempts) use ($free_attempts): array {
        if (time() - (int)($attempts['last_failure'] ?? 0) > LOGIN_RESET_SECONDS) {
            $attempts = ['failures' => 0, 'locked_until' => 0];
        }
        $attempts['failures']++;
        $attempts['last_failure'] = time();
        $over_limit = $attempts['failures'] - $free_attempts;
        if ($over_limit >= 0) {
            $lock_seconds = min(LOGIN_MAX_LOCK_SECONDS, LOGIN_BASE_LOCK_SECONDS * (2 ** min($over_limit, 10)));
            $attempts['locked_until'] = time() + $lock_seconds;
        }
        return $attempts;
    });
    if (!$is_saved) error_log('clio_music: kunde inte uppdatera räknare för inloggningsförsök');
}

/** Nollar namnräknaren. IP-räknaren lämnas: en lyckad inloggning ska inte ge fria gissningar mot andra konton. */
function login_record_success(string $username): void {
    $path = login_attempt_file(login_throttle_keys($username)[0]);
    if (is_file($path) && !unlink($path)) error_log('clio_music: kunde inte nolla inloggningsräknare');
}
