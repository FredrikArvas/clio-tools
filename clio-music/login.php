<?php
/**
 * login.php — inloggningsformulär.
 *
 * Säkerhetsantaganden:
 * - CSRF-token även på inloggningen (förhindrar att en främmande sida loggar in offret på
 *   angriparens konto).
 * - Spärr per användarnamn och IP (login_throttle.php) kontrolleras FÖRE lösenordet, så att en
 *   spärrad angripare inte får något svar om lösenordet var rätt.
 * - Felmeddelandet är detsamma för okänt namn och fel lösenord.
 */
require_once 'auth.php';
require_once 'config.php';
require_once 'csrf.php';
require_once 'login_throttle.php';

if (is_logged_in()) {
    header('Location: index.php');
    exit;
}

$error = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    csrf_require();
    $username = substr((string)($_POST['username'] ?? ''), 0, 100);
    $password = (string)($_POST['password'] ?? '');
    $lock_seconds = login_lock_remaining($username);
    if ($lock_seconds > 0) {
        http_response_code(429);
        audit_log('login_blocked', ['username' => $username, 'seconds' => $lock_seconds]);
        $error = 'För många misslyckade försök. Vänta en stund och försök igen.';
    } elseif ($user = verify_login($username, $password)) {
        login_record_success($username);
        login_user($user);
        audit_log('login_ok');
        header('Location: index.php');
        exit;
    } else {
        login_record_failure($username);
        audit_log('login_failed', ['username' => $username]);
        $error = 'Fel användarnamn eller lösenord.';
    }
}
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title><?= htmlspecialchars($site_title) ?> — Logga in</title>
<link rel="stylesheet" href="style.css?v=<?= APP_VERSION ?>">
</head>
<body class="login-page">
<div class="login-wrap">
  <h1><?= htmlspecialchars($site_title) ?></h1>
  <?php if ($error): ?>
  <p class="login-error"><?= htmlspecialchars($error) ?></p>
  <?php endif ?>
  <form method="post" class="login-form" autocomplete="on">
    <?= csrf_field() ?>
    <input type="text"     name="username" placeholder="Användarnamn"
           autocomplete="username" required autofocus maxlength="100">
    <input type="password" name="password" placeholder="Lösenord"
           autocomplete="current-password" required>
    <button type="submit">Logga in</button>
  </form>
  <p class="login-guest-link"><a href="index.php">Fortsätt utan konto →</a></p>
</div>
</body>
</html>
