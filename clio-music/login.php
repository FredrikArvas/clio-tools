<?php
require_once 'auth.php';
require_once 'config.php';

if (is_logged_in()) {
    header('Location: index.php');
    exit;
}

$error = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $user = verify_login($_POST['username'] ?? '', $_POST['password'] ?? '');
    if ($user) {
        $_SESSION['cm_user'] = $user;
        header('Location: index.php');
        exit;
    }
    $error = 'Fel användarnamn eller lösenord.';
}
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title><?= htmlspecialchars($site_title) ?> — Logga in</title>
<link rel="stylesheet" href="style.css">
</head>
<body class="login-page">
<div class="login-wrap">
  <h1><?= htmlspecialchars($site_title) ?></h1>
  <?php if ($error): ?>
  <p class="login-error"><?= htmlspecialchars($error) ?></p>
  <?php endif ?>
  <form method="post" class="login-form" autocomplete="on">
    <input type="text"     name="username" placeholder="Användarnamn"
           autocomplete="username" required autofocus>
    <input type="password" name="password" placeholder="Lösenord"
           autocomplete="current-password" required>
    <button type="submit">Logga in</button>
  </form>
  <p class="login-guest-link"><a href="index.php">Fortsätt utan konto →</a></p>
</div>
</body>
</html>
