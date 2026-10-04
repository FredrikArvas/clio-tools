<?php
// Verktyg för att generera bcrypt-hash av ett lösenord.
// Öppna i webbläsaren, använd en gång, radera eller lösenordsskydda sen.
$hash = '';
$plain = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && !empty($_POST['password'])) {
    $plain = $_POST['password'];
    $hash  = password_hash($plain, PASSWORD_BCRYPT, ['cost' => 12]);
}
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hash-verktyg</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 560px; margin: 60px auto; padding: 0 20px; }
input, button { font-size: 1rem; padding: 8px 12px; margin: 6px 0; width: 100%; box-sizing: border-box; }
code { display: block; background: #f0f0f0; padding: 12px; word-break: break-all; margin-top: 12px; }
.warn { color: #c00; font-size: 0.85rem; margin-top: 16px; }
</style>
</head>
<body>
<h2>Generera lösenords-hash</h2>
<form method="post">
  <input type="text" name="password" placeholder="Skriv lösenordet" autocomplete="off" required>
  <button type="submit">Generera hash</button>
</form>
<?php if ($hash): ?>
<p>Lägg till i <code>data/users.csv</code>:</p>
<code>användarnamn;<?= htmlspecialchars($hash) ?>;Visningsnamn;1</code>
<p class="warn">⚠️ Stäng eller ta bort den här sidan efter att du är klar.</p>
<?php endif ?>
</body>
</html>
