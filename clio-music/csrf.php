<?php
/**
 * csrf.php — skydd mot förfalskade anrop (CSRF) för formulär och JSON-API:er.
 *
 * Användning:
 * - HTML-formulär: skriv ut `<?= csrf_field() ?>` i formuläret och anropa `csrf_require()`
 *   först i POST-hanteringen.
 * - JSON-API:er: player.js skickar token i headern `X-CSRF-Token` (värdet kommer från
 *   `CM_CSRF` som index.php skriver ut). api/_bootstrap.php kontrollerar den.
 *
 * Säkerhetsantaganden:
 * - En token per session (synchronizer token), slumpad med random_bytes, jämförd med hash_equals.
 * - Token byts vid inloggning (auth.php: login_user) så att en token från före inloggningen
 *   inte går att återanvända.
 * - Kräver aktiv session; auth.php startar den.
 */

require_once __DIR__ . '/audit.php';

const CSRF_SESSION_KEY = 'csrf_token';
const CSRF_FIELD_NAME  = 'csrf_token';
const CSRF_HEADER_KEY  = 'HTTP_X_CSRF_TOKEN';

function csrf_token(): string {
    if (empty($_SESSION[CSRF_SESSION_KEY])) {
        $_SESSION[CSRF_SESSION_KEY] = bin2hex(random_bytes(32));
    }
    return $_SESSION[CSRF_SESSION_KEY];
}

function csrf_field(): string {
    return '<input type="hidden" name="' . CSRF_FIELD_NAME . '" value="' . htmlspecialchars(csrf_token(), ENT_QUOTES) . '">';
}

/**
 * Utloggningsknapp som litet POST-formulär (logout.php kräver POST + token).
 * $action är sökvägen till logout.php sett från anropande sida, t.ex. '../logout.php' i admin/.
 */
function logout_button(string $action = 'logout.php'): string {
    return '<form method="post" action="' . htmlspecialchars($action, ENT_QUOTES) . '" class="logout-form">'
        . csrf_field()
        . '<button type="submit" class="btn-logout">Logga ut</button></form>';
}

/** Sant om begäran bär rätt token, i formulärfältet eller i X-CSRF-Token-headern. */
function csrf_verify(): bool {
    $submitted = $_POST[CSRF_FIELD_NAME] ?? $_SERVER[CSRF_HEADER_KEY] ?? '';
    $expected  = $_SESSION[CSRF_SESSION_KEY] ?? '';
    return is_string($submitted) && $expected !== '' && hash_equals($expected, $submitted);
}

/** Avbryter med 403 om token saknas eller är fel. För HTML-sidor; API:er använder api_bootstrap(). */
function csrf_require(): void {
    if (csrf_verify()) return;
    audit_log('csrf_rejected', ['path' => $_SERVER['SCRIPT_NAME'] ?? '']);
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    exit('Sidan hade gått ut. Gå tillbaka, ladda om sidan och försök igen.');
}
