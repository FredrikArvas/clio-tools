<?php
/**
 * logout.php — utloggning.
 *
 * Kräver POST + CSRF-token, så att en främmande sida (t.ex. en <img src="logout.php">) inte kan
 * logga ut användaren. GET visar bara en knapp. Sidorna länkar hit via logout_button() i csrf.php.
 */
require_once __DIR__ . '/auth.php';
require_once __DIR__ . '/csrf.php';
require_once __DIR__ . '/config.php';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    csrf_require();
    audit_log('logout');
    logout_user();
    header('Location: login.php');
    exit;
}
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title><?= htmlspecialchars($site_title) ?> — Logga ut</title>
<link rel="stylesheet" href="style.css?v=<?= APP_VERSION ?>">
</head>
<body class="login-page">
<div class="login-wrap">
  <h1><?= htmlspecialchars($site_title) ?></h1>
  <?= logout_button() ?>
  <p class="login-guest-link"><a href="index.php">← Tillbaka till spelaren</a></p>
</div>
</body>
</html>
