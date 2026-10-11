<?php
/**
 * api/_bootstrap.php — gemensam start för alla JSON-API:er i api/.
 *
 * Kontrakt (för S3 och framåt):
 *
 *   require_once __DIR__ . '/_bootstrap.php';
 *   ['user' => $user, 'body' => $body] = api_bootstrap([
 *       'method'      => 'POST',   // 'POST' eller 'GET' (krävs)
 *       'allow_guest' => false,    // true = gäster tillåts (user blir guest_user())
 *       'max_bytes'   => 16384,    // valfri; standard API_DEFAULT_MAX_BYTES
 *   ]);
 *   ... validera fälten i $body ...
 *   api_respond(['ok' => true]);           // eller api_error(400, 'invalid track');
 *
 * Det api_bootstrap() garanterar när den returnerar:
 * - Rätt HTTP-metod (annars 405).
 * - Inloggad användare, eller gäst om allow_guest (annars 401).
 * - För POST: Content-Type application/json, kropp högst max_bytes (annars 413),
 *   giltig JSON som är ett objekt/array (annars 400), och rätt X-CSRF-Token (annars 403).
 *   $body är då en array. För GET är $body null.
 * - Sessionslåset är släppt (session_write_close), så API:er kan inte ändra $_SESSION.
 *   Det hindrar att samtidiga anrop köar bakom varandra.
 *
 * Det anroparen själv måste göra: validera innehållet i $body (typer, längder, tillåtna nycklar).
 */

require_once dirname(__DIR__) . '/auth.php';
require_once dirname(__DIR__) . '/csrf.php';

const API_DEFAULT_MAX_BYTES = 65536;
const API_JSON_MAX_DEPTH    = 16;

function api_error(int $status, string $message): never {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode(['ok' => false, 'error' => $message]);
    exit;
}

function api_respond(array $data): never {
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

function api_bootstrap(array $options): array {
    $method = $options['method'] ?? 'GET';
    if ($_SERVER['REQUEST_METHOD'] !== $method) api_error(405, 'method not allowed');

    if (!is_logged_in() && empty($options['allow_guest'])) api_error(401, 'login required');
    $user = current_user_or_guest();

    $body = null;
    if ($method === 'POST') {
        if (!csrf_verify()) {
            audit_log('csrf_rejected', ['path' => $_SERVER['SCRIPT_NAME'] ?? '']);
            api_error(403, 'invalid csrf token');
        }
        $body = api_read_json_body($options['max_bytes'] ?? API_DEFAULT_MAX_BYTES);
    }
    session_write_close();
    return ['user' => $user, 'body' => $body];
}

/** Läser och avkodar JSON-kroppen med hård storleksgräns, oavsett vad Content-Length påstår. */
function api_read_json_body(int $max_bytes): array {
    $content_type = strtolower($_SERVER['CONTENT_TYPE'] ?? '');
    if (!str_starts_with($content_type, 'application/json')) api_error(415, 'content-type must be application/json');
    if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > $max_bytes) api_error(413, 'payload too large');

    $raw = file_get_contents('php://input', false, null, 0, $max_bytes + 1);
    if ($raw === false) api_error(400, 'unreadable body');
    if (strlen($raw) > $max_bytes) api_error(413, 'payload too large');

    $body = json_decode($raw, true, API_JSON_MAX_DEPTH);
    if (!is_array($body)) api_error(400, 'invalid json');
    return $body;
}
