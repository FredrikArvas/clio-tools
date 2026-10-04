<?php
session_start();

function is_logged_in(): bool {
    return !empty($_SESSION['cm_user']);
}

function require_login(): void {
    if (!is_logged_in()) {
        header('Location: login.php');
        exit;
    }
}

function current_user(): array {
    return $_SESSION['cm_user'] ?? [];
}

function load_users(): array {
    $path = __DIR__ . '/data/users.csv';
    if (!file_exists($path)) return [];
    $users = [];
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $parts = str_getcsv($line, ';');
        if (count($parts) < 4) continue;
        [$username, $hash, $display, $active] = $parts;
        $admin  = isset($parts[4]) ? (int)trim($parts[4]) : 0;
        $groups = isset($parts[5]) ? array_map('trim', explode('|', $parts[5])) : [];
        if ((int)$active === 1) {
            $users[strtolower(trim($username))] = [
                'hash'    => trim($hash),
                'display' => trim($display),
                'admin'   => $admin,
                'groups'  => $groups,
            ];
        }
    }
    return $users;
}

function verify_login(string $username, string $password): ?array {
    $users = load_users();
    $key = strtolower(trim($username));
    if (!isset($users[$key])) return null;
    if (!password_verify($password, $users[$key]['hash'])) return null;
    return ['username' => $key, 'display' => $users[$key]['display'], 'admin' => $users[$key]['admin'], 'groups' => $users[$key]['groups']];
}
