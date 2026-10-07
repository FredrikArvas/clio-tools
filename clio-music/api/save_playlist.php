<?php
require_once '../auth.php';
require_login();
$user = current_user()['username'];
header('Content-Type: application/json');

$body   = json_decode(file_get_contents('php://input'), true);
$name   = trim($body['name'] ?? '');
$delete = !empty($body['delete']);
$tracks = $body['tracks'] ?? null;

if ($name === '' || strlen($name) > 100) {
    http_response_code(400);
    echo json_encode(['error' => 'invalid_name']);
    exit;
}

$dir  = __DIR__ . '/../data/playlists';
$file = $dir . '/' . basename($user) . '.json';

if (!is_dir($dir)) mkdir($dir, 0775, true);

$all = file_exists($file) ? json_decode(file_get_contents($file), true) : [];
if (!is_array($all)) $all = [];

if ($delete) {
    unset($all[$name]);
} elseif (is_array($tracks)) {
    $all[$name] = array_values(array_filter($tracks, 'is_string'));
} else {
    http_response_code(400);
    echo json_encode(['error' => 'invalid']);
    exit;
}

file_put_contents($file, json_encode($all, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT), LOCK_EX);
echo json_encode(['ok' => true]);
