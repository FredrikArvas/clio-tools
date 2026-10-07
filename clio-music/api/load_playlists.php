<?php
require_once '../auth.php';
require_login();
$user = current_user()['username'];
header('Content-Type: application/json');
$file = __DIR__ . '/../data/playlists/' . basename($user) . '.json';
$data = file_exists($file) ? json_decode(file_get_contents($file), true) : [];
echo json_encode(is_array($data) ? $data : [], JSON_UNESCAPED_UNICODE);
