<?php
require_once dirname(__DIR__) . '/auth.php';
require_login();

header('Content-Type: application/json');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo '{"error":"method not allowed"}';
    exit;
}

$body  = json_decode(file_get_contents('php://input'), true);
$track = trim($body['track'] ?? '');

if ($track === '') {
    http_response_code(400);
    echo '{"error":"missing track"}';
    exit;
}

$user = current_user();
$entry = json_encode([
    'user'  => $user['username'],
    'track' => $track,
    'ts'    => time(),
], JSON_UNESCAPED_UNICODE) . "\n";

$log = dirname(__DIR__) . '/data/plays.jsonl';
file_put_contents($log, $entry, FILE_APPEND | LOCK_EX);

echo '{"ok":true}';
