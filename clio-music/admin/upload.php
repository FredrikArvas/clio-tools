<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * admin/upload.php — tar emot en ljudfil (multipart, fältet "file") och lägger den i music/.
 *
 * Anropas av: admin/upload.js (fliken "Ladda upp" i admin/index.php), en fil per anrop.
 * Svarar alltid JSON: {ok: true, filename, bytes, warnings: [...]} eller
 * {ok: false, error: "<kod>", message: "<svensk text>"} (koder i admin/upload_validation.php).
 *
 * Säkerhetsantaganden:
 * - Bara inloggad admin (401/403), bara POST (405), CSRF-token i X-CSRF-Token (403) och
 *   högst UPLOAD_MAX_PER_HOUR anrop per admin och timme (429). api_bootstrap() används inte:
 *   den kräver JSON-kropp.
 * - Namn, storlek och innehåll valideras i upload_validation.php. Klientens MIME-typ används aldrig.
 * - Raden "fil;UPLOAD_GROUP" skrivs i track_groups.csv INNAN filen hamnar i music/, och
 *   kontrolleras efteråt: ett spår utan rad syns för alla inloggade. Misslyckas flytten
 *   återställs gruppraden.
 * - Filen skrivs först till music/.incoming/<slump>.part och byter sedan namn till music/<fil>
 *   (samma filsystem = atomiskt). .incoming/ matchas inte av scan_music() och nås inte via
 *   stream.php (som bara godtar ett sökvägssegment).
 * - Kontroll av befintlig fil, gruppraden och namnbytet sker under ett lås, så att två samtidiga
 *   uppladdningar av samma namn inte kan skriva över varandra (409 för den andra).
 * - Varje lyckad och avvisad uppladdning loggas i auditloggen.
 */
require_once dirname(__DIR__) . '/auth.php';
require_once dirname(__DIR__) . '/config.php';
require_once dirname(__DIR__) . '/csrf.php';
require_once dirname(__DIR__) . '/access.php';
require_once dirname(__DIR__) . '/rate_limit.php';
require_once __DIR__ . '/groups_store.php';
require_once __DIR__ . '/upload_validation.php';

const UPLOAD_INCOMING_DIR  = '.incoming';   // under music/
const UPLOAD_DIR_MODE      = 0770;
const UPLOAD_FILE_MODE     = 0664;
const UPLOAD_LOCK_FILENAME = 'upload';      // with_file_lock() lägger till .lock

function upload_respond(int $status, array $data): never {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}

/** Avvisar med felkoden, loggar i auditloggen (utom för ej inloggade) och avslutar. */
function upload_reject(string $code, string $filename = '', bool $is_audited = true): never {
    [$status, $message] = upload_error($code);
    if ($is_audited) audit_log('admin_upload_rejected', ['reason' => $code, 'file' => $filename]);
    upload_respond($status, ['ok' => false, 'error' => $code, 'message' => $message]);
}

/** Felkoden för ett $_FILES-fel, eller '' om filen kom fram. */
function upload_php_error_code(int $php_error): string {
    return match ($php_error) {
        UPLOAD_ERR_OK                              => '',
        UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE  => 'too_large',
        UPLOAD_ERR_PARTIAL                         => 'partial',
        UPLOAD_ERR_NO_FILE                         => 'no_file',
        default                                    => 'server_error',   // NO_TMP_DIR, CANT_WRITE, EXTENSION
    };
}

/** Den enda filen i fältet "file", eller avvisning. Tom $_FILES med kropp = post_max_size överskriden. */
function read_uploaded_file(): array {
    $file = $_FILES['file'] ?? null;
    if ($file === null) {
        upload_reject((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 0 && empty($_POST) ? 'too_large' : 'no_file');
    }
    if (!is_array($file) || is_array($file['name'] ?? null) || count($_FILES) !== 1) upload_reject('multiple_files');
    $name  = is_string($file['name'] ?? null) ? $file['name'] : '';
    $error = upload_php_error_code((int)($file['error'] ?? UPLOAD_ERR_NO_FILE));
    if ($error !== '') {
        if ($error === 'server_error') error_log('clio_music: uppladdning, PHP-fel ' . (int)$file['error']);
        upload_reject($error, $name);
    }
    if (!is_uploaded_file($file['tmp_name'])) upload_reject('server_error', $name);
    return ['name' => $name, 'tmp_name' => $file['tmp_name']];
}

/** Alla ljudfiler i music/ (filnamn), även kanalfiler i flera format, som scan_music() hittar dem. */
function list_audio_files(string $music_dir): array {
    $files = [];
    foreach (AUDIO_EXTENSIONS as $ext) {
        $files = array_merge($files, array_map('basename', glob($music_dir . '/*.' . $ext) ?: []));
    }
    sort($files);
    return $files;
}

/** Skapar music/.incoming/ vid behov. Returnerar sökvägen eller null (loggat). */
function ensure_incoming_dir(string $music_dir): ?string {
    $incoming = $music_dir . '/' . UPLOAD_INCOMING_DIR;
    if (is_dir($incoming)) return $incoming;
    if (!mkdir($incoming, UPLOAD_DIR_MODE) && !is_dir($incoming)) {
        error_log('clio_music: kan inte skapa ' . UPLOAD_INCOMING_DIR . ' i musikkatalogen');
        return null;
    }
    chmod($incoming, UPLOAD_DIR_MODE);   // mkdir påverkas av umask
    return $incoming;
}

/**
 * Lägger filen i music/ under lås. Returnerar '' vid lyckat resultat, annars en felkod.
 * Ordning: finns redan → grupprad → kontrollera raden → .part → rename. Fel efter gruppraden
 * återställer spårets tidigare grupp.
 */
function store_upload(string $tmp_name, string $filename, string $music_dir, string $tracks_path, string $incoming): string {
    $final_path = $music_dir . '/' . $filename;
    if (file_exists($final_path)) return 'exists';
    $map_before     = load_track_groups();
    $previous_group = track_group($filename, $map_before);
    $error = save_track_groups($tracks_path, [$filename => UPLOAD_GROUP], $map_before);
    if ($error !== '') {
        error_log('clio_music: uppladdning, grupprad kunde inte skrivas: ' . $error);
        return 'server_error';
    }
    if (track_group($filename, load_track_groups()) !== UPLOAD_GROUP) {
        error_log('clio_music: uppladdning, grupprad ger inte ' . UPLOAD_GROUP . ' för filen');
        restore_track_group($tracks_path, $filename, $previous_group);
        return 'server_error';
    }
    $part_path = $incoming . '/' . bin2hex(random_bytes(16)) . '.part';
    $is_moved  = move_uploaded_file($tmp_name, $part_path)
        && chmod($part_path, UPLOAD_FILE_MODE)
        && rename($part_path, $final_path);
    if (!$is_moved) {
        error_log('clio_music: uppladdning, filen kunde inte flyttas till musikkatalogen');
        if (is_file($part_path) && !unlink($part_path)) error_log('clio_music: kunde inte städa ' . basename($part_path));
        restore_track_group($tracks_path, $filename, $previous_group);
        return 'server_error';
    }
    return '';
}

/** Återställer spårets grupp efter en misslyckad uppladdning. Fel loggas (svaret är redan 500). */
function restore_track_group(string $tracks_path, string $filename, string $previous_group): void {
    $error = save_track_groups($tracks_path, [$filename => $previous_group], load_track_groups());
    if ($error !== '') error_log('clio_music: uppladdning, grupprad kunde inte återställas: ' . $error);
}

// ── Begäran ───────────────────────────────────────────────────────────────────
if (!is_logged_in()) upload_reject('not_logged_in', '', false);
$user = current_user();
if (empty($user['admin'])) upload_reject('forbidden');
if ($_SERVER['REQUEST_METHOD'] !== 'POST') upload_reject('method');
if (!csrf_verify()) {
    audit_log('csrf_rejected', ['path' => $_SERVER['SCRIPT_NAME'] ?? '']);
    upload_reject('csrf', '', false);
}
session_write_close();   // sessionen behövs inte längre; släpp låset under filhanteringen

$retry_after = rate_limit_hit('upload', $user['username'], UPLOAD_MAX_PER_HOUR, 3600);
if ($retry_after > 0) {
    header('Retry-After: ' . $retry_after);
    upload_reject('rate_limited');
}

$upload = read_uploaded_file();
[$filename, $error] = validate_upload_filename($upload['name'], $music_url);
if ($error !== '') upload_reject($error, $upload['name']);
[$bytes, $error] = validate_upload_size((int)filesize($upload['tmp_name']));
if ($error !== '') upload_reject($error, $filename);
[, $error] = validate_upload_content($upload['tmp_name'], pathinfo($filename, PATHINFO_EXTENSION));
if ($error !== '') upload_reject($error, $filename);

$tracks_path = dirname(__DIR__) . '/data/track_groups.csv';
$incoming    = ensure_incoming_dir($music_dir);
if ($incoming === null) upload_reject('server_error', $filename);

$existing_files = list_audio_files($music_dir);
$warnings = array_merge(
    check_channel_rules($filename, $existing_files),
    check_group_inheritance($filename, $existing_files, load_track_groups())
);

$code = '';
$lock_error = with_file_lock($incoming . '/' . UPLOAD_LOCK_FILENAME, function () use (&$code, $upload, $filename, $music_dir, $tracks_path, $incoming): string {
    $code = store_upload($upload['tmp_name'], $filename, $music_dir, $tracks_path, $incoming);
    return '';
});
if ($lock_error !== '') $code = 'server_error';
if ($code !== '') upload_reject($code, $filename);

audit_log('admin_upload_ok', ['file' => $filename, 'bytes' => $bytes, 'warnings' => count($warnings)]);
upload_respond(200, ['ok' => true, 'filename' => $filename, 'bytes' => $bytes, 'warnings' => $warnings]);
