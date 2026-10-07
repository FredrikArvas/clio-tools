<?php
require_once 'auth.php';
require_once 'config.php';
require_login();
$user = current_user();
if (empty($user['admin'])) {
    header('Location: help.php');
    exit;
}
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin-hjälp — <?= htmlspecialchars($site_title) ?></title>
<link rel="stylesheet" href="style.css">
<style>
.help-wrap { max-width:720px; margin:0 auto; padding:28px 24px 60px; }
h2 { font-size:1.15rem; color:var(--accent); margin:32px 0 10px; padding-bottom:6px;
     border-bottom:1px solid color-mix(in srgb, var(--accent) 30%, transparent); }
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
.user-help-link {
  display:inline-flex; align-items:center; gap:8px;
  background:color-mix(in srgb, var(--accent2) 6%, var(--surface2));
  border:1px solid color-mix(in srgb, var(--accent2) 25%, transparent);
  border-radius:8px; padding:10px 14px; margin-bottom:28px;
  font-size:0.85rem; color:var(--text-muted, #b0b8cc);
}
.user-help-link a { color:var(--accent2); }
</style>
</head>
<body>
<div class="app" style="min-height:100vh">
  <header class="header">
    <h1><?= htmlspecialchars($site_title) ?> — Admin-hjälp</h1>
    <div class="header-user">
      <a href="index.php" style="color:var(--accent);font-size:0.9rem">← Spelaren</a>
    </div>
  </header>

  <div class="help-wrap">

    <div class="user-help-link">
      ♪ Letar du efter användar-manualen?
      <a href="help.php">Öppna hjälp för lyssnare →</a>
    </div>

    <h2>Dashboard — spelstatistik</h2>
    <p>Nås via <a href="admin/index.php" style="color:var(--accent2)">Admin-länken</a> i spelaren.</p>
    <ul>
      <li><strong>Per låt</strong> — stapeldiagram + vilka användare som lyssnat och hur många gånger.</li>
      <li><strong>Per användare</strong> — totalt antal spelningar och vilka låtar.</li>
      <li><strong>Gruppfilter</strong> — filtrera vyn till en specifik grupp.</li>
    </ul>
    <div class="note">En spelning räknas efter 5 sekunders sammanhängande uppspelning. Rådata finns i <code>data/plays.jsonl</code> — en JSON-rad per spelning med användarnamn, filnamn och Unix-tidsstämpel.</div>

    <h2>Grupper och behörigheter</h2>
    <p>Nås via <a href="admin/groups.php" style="color:var(--accent2)">Grupper</a> i admin-headern.</p>
    <ul>
      <li><strong>Användare-tabben</strong> — kryssa i vilka grupper varje användare tillhör. Gruppen <em>Alla</em> ger tillgång till samtliga låtar.</li>
      <li><strong>Låtar-tabben</strong> — välj grupp per låt. <em>Alla</em> = synlig för alla inloggade.</li>
      <li>Nya grupper skapas direkt med <kbd>+ Lägg till grupp</kbd>.</li>
    </ul>

    <h2>Lägga till användare</h2>
    <ol>
      <li>Öppna <code>admin/hash_tool.php</code> och generera ett bcrypt-hash för lösenordet.</li>
      <li>Redigera <code>data/users.csv</code> via SFTP och lägg till en rad:<br>
          <code>användarnamn;[hash];Visningsnamn;1;0;Grupp1|Grupp2</code></li>
      <li>Ta bort <code>hash_tool.php</code> igen när du är klar.</li>
    </ol>
    <div class="note">Kolumnerna: användarnamn ; bcrypt-hash ; visningsnamn ; aktiv (1/0) ; admin (1/0) ; grupper (pipe-separerade)</div>

    <h2>Lägga till låtar</h2>
    <ol>
      <li>Tagga MP3-filerna med albumnamn, titel och artist i ditt DAW eller en taggeditor (t.ex. Mp3tag, Logic, iTunes). Spelaren läser ID3v2 (v2.2, v2.3, v2.4) och faller tillbaka på ID3v1.</li>
      <li>Ladda upp till <code>music/</code> via SFTP. Låtarna dyker upp direkt i spelaren.</li>
      <li>Album-sektioner genereras automatiskt — lika albumnamn grupperas i en kollapsibel sektion med en ▶-knapp.</li>
      <li>Tilldela grupp i <a href="admin/groups.php?tab=tracks" style="color:var(--accent2)">Grupper → Låtar</a> vid behov.</li>
    </ol>
    <div class="note">Saknar filen ID3-taggar används filnamnet som titel — understreck och bindestreck ersätts med mellanslag.</div>

    <h2>4-kanalsspår</h2>
    <p>Exportera upp till fyra filer med identisk bas och suffixen <code>_msc</code>, <code>_bin</code>, <code>_vce</code>, <code>_env</code>:</p>
    <ul>
      <li><code>001-Meditation_msc.mp3</code> — musik (master, driver progress och EQ)</li>
      <li><code>001-Meditation_bin.mp3</code> — binauralt lager (spelas i ren stereo utan EQ)</li>
      <li><code>001-Meditation_vce.mp3</code> — röst</li>
      <li><code>001-Meditation_env.mp3</code> — miljöljud</li>
    </ul>
    <p>Ladda upp alla filer till <code>music/</code>. Spelaren känner igen gruppen automatiskt utifrån filnamnsbasen. Metadata läses från <code>_msc</code>-filen.</p>

    <h2>Serverupplägg och deploy</h2>
    <p>Applikationen körs på EliteDesk GPU (<code>clioadmin@100.107.127.104</code>) med PHP 8.3-FPM + nginx på port 8091, bakom Cloudflare.</p>
    <ul>
      <li>Deploya PHP/JS/CSS: <code>scp</code> filerna till <code>/var/www/clio_music/</code></li>
      <li>Musik: <code>scp music/*.mp3 clioadmin@…:/var/www/clio_music/music/</code></li>
      <li>Cache-bust sker automatiskt via <code>?v=APP_VERSION</code> på <code>player.js</code> — uppdatera konstanten i <code>config.php</code> vid driftsättning.</li>
    </ul>

    <h2>Filrättigheter — skrivbara mappar</h2>
    <p>Följande mappar måste ägas av <code>clioadmin:www-data</code> med <code>chmod 775</code> för att PHP-FPM (kör som www-data) ska kunna skriva:</p>
    <ul>
      <li><code>data/profiles/</code> — serverside ljudprofiler per användare</li>
      <li><code>data/playlists/</code> — spellistor per användare (skapas automatiskt vid första sparning)</li>
    </ul>

  </div><!-- .help-wrap -->
</div>
</body>
</html>
