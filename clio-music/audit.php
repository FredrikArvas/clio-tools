<?php
/**
 * audit.php — säkerhetsrelevanta händelser till data/audit.jsonl (en JSON-rad per händelse).
 *
 * Anropas av: auth.php/login.php (inloggning ok/fel, spärr, utloggning), csrf.php (avvisad token),
 * admin-sidorna (ändringar, från S4).
 *
 * Säkerhetsantaganden:
 * - Lösenord, hashar och tokens får aldrig hamna i loggen. Nycklar som liknar sådana filtreras
 *   bort även om en anropare råkar skicka med dem.
 * - Loggen ligger i data/, som nginx spärrar (403). Skrivfel loggas via error_log, aldrig tyst.
 */

require_once __DIR__ . '/client_ip.php';

const AUDIT_LOG_FILE        = __DIR__ . '/data/audit.jsonl';
const AUDIT_FORBIDDEN_KEYS  = '/pass|hash|token|secret/i';
const AUDIT_MAX_VALUE_CHARS = 200;

function audit_log(string $event, array $context = []): void {
    $clean_context = [];
    foreach ($context as $key => $value) {
        if (preg_match(AUDIT_FORBIDDEN_KEYS, (string)$key)) continue;
        $clean_context[$key] = is_scalar($value) ? substr((string)$value, 0, AUDIT_MAX_VALUE_CHARS) : $value;
    }
    $entry = [
        'ts'    => time(),
        'event' => $event,
        'user'  => $_SESSION['cm_user']['username'] ?? null,
        'ip'    => client_ip(),
    ] + $clean_context;
    $line = json_encode($entry, JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE) . "\n";
    if (file_put_contents(AUDIT_LOG_FILE, $line, FILE_APPEND | LOCK_EX) === false) {
        error_log('clio_music: kunde inte skriva auditlogg (' . $event . ')');
    }
}
