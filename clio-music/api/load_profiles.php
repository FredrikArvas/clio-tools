<?php
require_once dirname(__DIR__) . '/auth.php';

header('Content-Type: application/json');

if (!is_logged_in()) { echo '{}'; exit; }
$user = current_user();
$file = dirname(__DIR__) . '/data/profiles/' . $user['username'] . '.json';

if (!file_exists($file)) {
    echo '{}';
    exit;
}

echo file_get_contents($file);
