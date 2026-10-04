<?php
require_once 'auth.php';
require_once 'config.php';
require_login();
$user = current_user();
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hjälp — <?= htmlspecialchars($site_title) ?></title>
<link rel="stylesheet" href="style.css">
<style>
.help-wrap { max-width:720px; margin:0 auto; padding:28px 24px 60px; }
h2 { font-size:1.25rem; color:var(--accent2); margin:32px 0 10px; padding-bottom:6px;
     border-bottom:1px solid var(--border); }
h2:first-child { margin-top:0; }
h3 { font-size:0.95rem; color:var(--text); margin:20px 0 6px; }
p  { color:var(--text-muted, #b0b8cc); line-height:1.65; margin-bottom:10px; }
ul, ol { padding-left:1.4em; color:var(--text-muted, #b0b8cc); line-height:1.7; margin-bottom:10px; }
li { margin-bottom:3px; }
code { background:var(--surface2); border:1px solid var(--border); border-radius:4px;
       padding:1px 6px; font-size:0.82rem; color:var(--accent2); font-family:monospace; }
.note { background:var(--surface2); border-left:3px solid var(--accent);
        border-radius:0 6px 6px 0; padding:10px 14px; margin:12px 0;
        color:var(--text-muted, #b0b8cc); font-size:0.88rem; line-height:1.55; }
.admin-section { border:1px solid var(--border); border-radius:8px;
                 padding:18px 20px; margin-top:12px;
                 background:color-mix(in srgb, var(--accent) 5%, var(--surface)); }
.admin-section h2 { color:var(--accent); margin-top:0; border-color:color-mix(in srgb, var(--accent) 30%, transparent); }
kbd { background:var(--surface2); border:1px solid var(--border); border-radius:4px;
      padding:1px 7px; font-size:0.82rem; font-family:monospace; }
table.shortcuts { border-collapse:collapse; width:100%; margin:8px 0 12px; }
table.shortcuts td { padding:5px 10px; border-bottom:1px solid var(--border); font-size:0.86rem;
                     color:var(--text-muted, #b0b8cc); }
table.shortcuts td:first-child { color:var(--text); font-weight:500; width:50%; }
</style>
</head>
<body>
<div class="app" style="min-height:100vh">
  <header class="header">
    <h1><?= htmlspecialchars($site_title) ?> — Hjälp</h1>
    <div class="header-user">
      <a href="index.php" style="color:var(--accent);font-size:0.9rem">← Tillbaka till spelaren</a>
    </div>
  </header>

  <div class="help-wrap">

    <h2>Spelaren</h2>
    <p>Välj en låt i listan till vänster (eller nedanför på mobil) för att börja spela. Du kan också använda knapparna i mitten för att navigera mellan spår.</p>

    <table class="shortcuts">
      <tr><td>&#9654; / &#9646;&#9646;</td><td>Spela / Pausa</td></tr>
      <tr><td>&#9664;&#9664;</td><td>Föregående låt</td></tr>
      <tr><td>&#9654;&#9654;</td><td>Nästa låt</td></tr>
      <tr><td>Tidslinjalen</td><td>Klicka eller dra för att spola</td></tr>
    </table>

    <p>När ett spår är slut startar nästa automatiskt.</p>

    <h2>Ljudinställningar</h2>
    <p>Klicka på <kbd>&#9881; Ljud</kbd> för att öppna inställningspanelen.</p>
    <ul>
      <li><strong>Volym</strong> — generell nivå, 0–100 %.</li>
      <li><strong>Balans</strong> — fördelar ljudet mellan vänster (V) och höger (H) kanal. C = mitt.</li>
      <li><strong>Bas</strong> — förstärker eller dämpar de lägre frekvenserna (± 12 dB).</li>
      <li><strong>Diskant</strong> — förstärker eller dämpar de högre frekvenserna (± 12 dB).</li>
      <li><strong>Binauralt</strong> — justerar volymen på det binaurala lagret, oberoende av huvudljudet. Syns bara när spåret har ett binauralt lager.</li>
    </ul>
    <div class="note">Inställningarna sparas automatiskt i din webbläsare och gäller bara för dig — andra lyssnare påverkas inte. Det binaurala lagret spelas alltid i ren stereo utan EQ-påverkan, så frekvenserna bevaras exakt som Roger exporterat dem.</div>

    <h2>Grupper och låttillgång</h2>
    <p>Låtarna är indelade i grupper. Du ser bara de låtar som din användare har tillgång till. Om du saknar en låt du förväntar dig — kontakta administratören.</p>

    <h2>Logga ut</h2>
    <p>Klicka på <kbd>Logga ut</kbd> längst upp till höger. Din session avslutas och du skickas till inloggningssidan.</p>

<?php if (!empty($user['admin'])): ?>

    <div class="admin-section">
      <h2>&#9881; Adminfunktioner</h2>

      <h3>Dashboard — spelstatistik</h3>
      <p>Nås via <a href="admin/index.php">Admin-länken</a> i spelaren. Visar antal spelningar per låt och per användare. En spelning räknas efter 5 sekunders sammanhängande uppspelning (för att undvika oavsiktliga klick).</p>
      <ul>
        <li><strong>Per låt</strong> — stapeldiagram + vilka användare som lyssnat och hur många gånger.</li>
        <li><strong>Per användare</strong> — totalt antal spelningar och vilka låtar.</li>
        <li><strong>Gruppfilter</strong> — filtrera vyn till en specifik grupp.</li>
      </ul>

      <h3>Grupper</h3>
      <p>Nås via <a href="admin/groups.php">Grupper-länken</a> i admin-headern.</p>
      <ul>
        <li><strong>Användare-tabben</strong> — kryssa i vilka grupper varje användare tillhör. Spara med knappen längst ner. En användare i gruppen <em>Alla</em> ser alltid alla låtar oavsett låttilldelning.</li>
        <li><strong>Låtar-tabben</strong> — välj grupp per låt med radioknappar. <em>Alla</em> = låten syns för alla inloggade.</li>
        <li>Nya grupper kan skapas direkt i formuläret — skriv ett namn och klicka <kbd>+ Lägg till grupp</kbd>.</li>
      </ul>

      <h3>Lägga till användare</h3>
      <ol>
        <li>Öppna <code>admin/hash_tool.php</code> i webbläsaren och generera ett bcrypt-lösenordshash.</li>
        <li>Öppna <code>data/users.csv</code> via SFTP och lägg till en rad:<br>
            <code>användarnamn;[hash];Visningsnamn;1;0;Grupp1|Grupp2</code></li>
        <li>Spara filen. Användaren kan logga in direkt — ingen omstart krävs.</li>
        <li>Ta bort <code>hash_tool.php</code> igen när du är klar.</li>
      </ol>
      <div class="note">Kolumnerna i users.csv: användarnamn ; bcrypt-hash ; visningsnamn ; aktiv (1/0) ; admin (1/0) ; grupper (pipe-separerade)</div>

      <h3>Lägga till låtar</h3>
      <ol>
        <li>Ladda upp MP3-filen till mappen <code>music/</code> via SFTP.</li>
        <li>Låten dyker upp i spellistan direkt för användare med rätt gruppåtkomst.</li>
        <li>Tilldela grupp i <a href="admin/groups.php?tab=tracks">Grupper → Låtar</a> om den inte ska synas för alla.</li>
      </ol>
      <div class="note">Filnamnet används som låttitel om MP3-filen saknar ID3-taggar. Understreck och bindestreck ersätts automatiskt med mellanslag.</div>

      <h3>Binaurala lager</h3>
      <p>Varje spår kan ha ett separat binauralt lager som lyssnaren justerar på egen hand. Spela in/exportera två filer med identiskt namn, men lägg till <code>_bin</code> före <code>.mp3</code>:</p>
      <ul>
        <li>Huvudljud: <code>001-Meditation.mp3</code></li>
        <li>Binauralt lager: <code>001-Meditation_bin.mp3</code></li>
      </ul>
      <p>Ladda upp båda filerna till <code>music/</code>. Spelaren känner igen paret automatiskt och visar en "Binauralt"-slider i inställningspanelen. Lagret spelas alltid i ren stereo utan EQ-filter, vilket bevarar de binaurala frekvenserna exakt.</p>

      <h3>Spelloggen</h3>
      <p>Rådata lagras i <code>data/plays.jsonl</code> — en JSON-rad per spelning med användarnamn, filnamn och Unix-tidsstämpel. Filen kan laddas ner via SFTP för vidare analys.</p>
    </div>

<?php endif ?>

  </div><!-- .help-wrap -->
</div>
</body>
</html>
