<?php
require_once dirname(__DIR__) . '/auth.php';
require_login();

header('Content-Type: application/json');

$user = current_user();
$file = dirname(__DIR__) . '/data/profiles/' . $user['username'] . '.json';

if (!file_exists($file)) {
    echo '{}';
    exit;
}

echo file_get_contents($file);
