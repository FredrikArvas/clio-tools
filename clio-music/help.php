<?php
require_once 'auth.php';
require_once 'config.php';
require_login();
$user     = current_user();
$is_admin = !empty($user['admin']);
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hjälp — <?= htmlspecialchars($site_title) ?></title>
<link rel="stylesheet" href="style.css">
<style>
.help-wrap { max-width:720px; margin:0 auto; padding:28px 24px 60px; }
h2 { font-size:1.15rem; color:var(--accent2); margin:32px 0 10px; padding-bottom:6px;
     border-bottom:1px solid var(--border); }
h2:first-of-type { margin-top:0; }
h3 { font-size:0.95rem; color:var(--text); margin:20px 0 6px; }
p  { color:var(--text-muted, #b0b8cc); line-height:1.65; margin-bottom:10px; }
ul, ol { padding-left:1.4em; color:var(--text-muted, #b0b8cc); line-height:1.7; margin-bottom:10px; }
li { margin-bottom:3px; }
code { background:var(--surface2); border:1px solid var(--border); border-radius:4px;
       padding:1px 6px; font-size:0.82rem; color:var(--accent2); font-family:monospace; }
kbd  { background:var(--surface2); border:1px solid var(--border); border-radius:4px;
       padding:1px 7px; font-size:0.82rem; font-family:monospace; }
.note { background:var(--surface2); border-left:3px solid var(--accent);
        border-radius:0 6px 6px 0; padding:10px 14px; margin:12px 0;
        color:var(--text-muted, #b0b8cc); font-size:0.88rem; line-height:1.55; }
table.shortcuts { border-collapse:collapse; width:100%; margin:8px 0 12px; }
table.shortcuts td { padding:5px 10px; border-bottom:1px solid var(--border); font-size:0.86rem;
                     color:var(--text-muted, #b0b8cc); }
table.shortcuts td:first-child { color:var(--text); font-weight:500; width:50%; }
.admin-link-box {
  display:flex; align-items:center; gap:12px;
  background:color-mix(in srgb, var(--accent) 6%, var(--surface2));
  border:1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  border-radius:8px; padding:12px 16px; margin-bottom:28px;
  font-size:0.88rem; color:var(--text-muted, #b0b8cc);
}
.admin-link-box a { color:var(--accent); font-weight:600; white-space:nowrap; }
</style>
</head>
<body>
<div class="app" style="min-height:100vh">
  <header class="header">
    <h1><?= htmlspecialchars($site_title) ?> — Hjälp</h1>
    <div class="header-user">
      <a href="index.php" style="color:var(--accent);font-size:0.9rem">← Tillbaka</a>
    </div>
  </header>

  <div class="help-wrap">

<?php if ($is_admin): ?>
    <div class="admin-link-box">
      ⚙ Du är inloggad som administratör.
      <a href="help_admin.php">Öppna admin-manualen →</a>
    </div>
<?php endif ?>

    <h2>Spelaren</h2>
    <p>Klicka på en låt i biblioteket för att börja spela. Kontrollerna i mitten navigerar mellan spår.</p>
    <table class="shortcuts">
      <tr><td>&#9654; / &#9646;&#9646;</td><td>Spela / Pausa</td></tr>
      <tr><td>&#9664;&#9664;</td><td>Föregående låt</td></tr>
      <tr><td>&#9654;&#9654;</td><td>Nästa låt</td></tr>
      <tr><td>Tidslinjalen</td><td>Klicka eller dra för att spola</td></tr>
      <tr><td>🔂 Repetera låt</td><td>Loopar det aktuella spåret</td></tr>
      <tr><td>🔁 Upprepa lista</td><td>Fortsätter från början när listan/kön är slut</td></tr>
      <tr><td>🔀 Slumpa</td><td>Spelar nästa spår slumpmässigt</td></tr>
    </table>

    <h2>Album-mappar</h2>
    <p>Låtar grupperas automatiskt i kollapsibara album-sektioner utifrån albumtaggen i varje MP3-fil.</p>
    <ul>
      <li>Klicka på album-rubriken (eller <kbd>▾</kbd>-pilen) för att fälla ihop eller expandera ett album.</li>
      <li>Klicka på <kbd>▶</kbd>-knappen på albumraden för att lägga hela albumet i kön och starta direkt.</li>
      <li>Kollapsade album minns sin position nästa gång du öppnar sidan (sparas per enhet).</li>
      <li>Spår utan albumtagg visas direkt i listan utan sektionsomslutning.</li>
    </ul>

    <h2>Kö</h2>
    <p>Med kön bygger du en anpassad ordning oberoende av biblioteket.</p>
    <ul>
      <li>Klicka på <kbd>+</kbd> bredvid en låt för att lägga den i kön.</li>
      <li>Byt till fliken <kbd>Kö</kbd> för att se och hantera kön.</li>
      <li>Ändra ordning med <kbd>▲</kbd> / <kbd>▼</kbd> — eller dra med handtaget till vänster (desktop).</li>
      <li>Ta bort ett spår med <kbd>✕</kbd>.</li>
      <li>Klicka på ett spår i kön för att spela det direkt.</li>
    </ul>
    <div class="note">Kön sparas automatiskt på servern och finns kvar nästa gång du loggar in, även om du byter enhet.</div>

    <h2>Spellistor</h2>
    <p>Spellistor är namngivna, permanenta samlingar av spår som sparas på servern.</p>

    <h3>Lägga till ett spår i en spellista</h3>
    <ul>
      <li>Klicka på <kbd>☰</kbd>-knappen till vänster om <kbd>+</kbd> bredvid låten.</li>
      <li>Välj en befintlig spellista i dropdown:en — eller välj <kbd>+ Ny spellista…</kbd> för att skapa en ny.</li>
    </ul>

    <h3>Hantera spellistor</h3>
    <ul>
      <li>Byt till fliken <kbd>Spellistor</kbd>.</li>
      <li>Skriv ett namn och klicka <kbd>Skapa</kbd> (eller tryck Enter) för att skapa en tom spellista.</li>
      <li>Klicka <kbd>▶</kbd> för att lägga hela spellistan i kön och starta.</li>
      <li>Klicka <kbd>✕</kbd> för att ta bort en spellista permanent.</li>
    </ul>
    <div class="note">Spellistor sparas per användare på servern och synkroniseras mellan enheter. Samma spår kan inte läggas till dubbelt i samma spellista.</div>

    <h2>Ljudinställningar</h2>
    <p>Klicka på <kbd>⚙ Ljud</kbd> för att öppna inställningspanelen.</p>
    <ul>
      <li><strong>Musik / Binauralt / Röst / Miljö</strong> — volym per kanal, 0–100 %. Bara kanalerna som finns i spåret visas.</li>
      <li><strong>Balans</strong> — vänster (V) / höger (H). C = mitt.</li>
      <li><strong>Bas / Diskant</strong> — ± 12 dB, påverkar musikkanalen.</li>
      <li><strong>Hastighet</strong> — 0.5× till 2.0×, alla kanaler synkroniseras.</li>
    </ul>
    <div class="note">Alla inställningar sparas per spår och per användare på servern. Det binaurala lagret spelas i ren stereo utan EQ så att frekvenserna bevaras exakt.</div>

    <h2>Låttillgång</h2>
    <p>Låtarna är indelade i grupper. Du ser bara spår som din användare har tillgång till. Kontakta administratören om du saknar ett spår.</p>

    <h2>Logga ut</h2>
    <p>Klicka på <kbd>Logga ut</kbd> längst upp till höger.</p>

  </div><!-- .help-wrap -->
</div>
</body>
</html>
