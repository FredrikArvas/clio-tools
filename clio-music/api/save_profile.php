<?php
require_once dirname(__DIR__) . '/auth.php';

header('Content-Type: application/json');

if (!is_logged_in()) { echo '{"ok":true}'; exit; }

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo '{"error":"method not allowed"}';
    exit;
}

$body     = json_decode(file_get_contents('php://input'), true);
$track    = trim($body['track'] ?? '');
$settings = $body['settings'] ?? null;

if ($track === '' || !is_array($settings)) {
    http_response_code(400);
    echo '{"error":"missing track or settings"}';
    exit;
}

$user = current_user();
$dir  = dirname(__DIR__) . '/data/profiles';
if (!is_dir($dir)) mkdir($dir, 0750, true);

$file = $dir . '/' . $user['username'] . '.json';

$profiles = [];
if (file_exists($file)) {
    $profiles = json_decode(file_get_contents($file), true) ?? [];
}
$profiles[$track] = $settings;

file_put_contents($file, json_encode($profiles, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT), LOCK_EX);

echo '{"ok":true}';
