<?php
require_once 'auth.php';
require_once 'config.php';
require_login();

$user = current_user();

// ── ID3-läsare ────────────────────────────────────────────────────────────────

function read_id3v1(string $path): array {
    $meta = [];
    $size = @filesize($path);
    if ($size < 128) return $meta;
    $fp = @fopen($path, 'rb');
    if (!$fp) return $meta;
    fseek($fp, -128, SEEK_END);
    $tag = fread($fp, 128);
    fclose($fp);
    if (substr($tag, 0, 3) !== 'TAG') return $meta;
    $title  = rtrim(substr($tag, 3, 30));
    $artist = rtrim(substr($tag, 33, 30));
    $album  = rtrim(substr($tag, 63, 30));
    if ($title)  $meta['title']  = $title;
    if ($artist) $meta['artist'] = $artist;
    if ($album)  $meta['album']  = $album;
    return $meta;
}

function read_id3v2(string $path): array {
    $meta = [];
    $fp = @fopen($path, 'rb');
    if (!$fp) return $meta;
    $hdr = fread($fp, 10);
    if (strlen($hdr) < 10 || substr($hdr, 0, 3) !== 'ID3') { fclose($fp); return $meta; }
    $ver   = ord($hdr[3]);
    $flags = ord($hdr[5]);
    $total = (ord($hdr[6]) << 21) | (ord($hdr[7]) << 14) | (ord($hdr[8]) << 7) | ord($hdr[9]);
    if ($flags & 0x40) {
        $sz   = fread($fp, 4);
        $skip = ($ver === 4)
            ? ((ord($sz[0]) << 21) | (ord($sz[1]) << 14) | (ord($sz[2]) << 7) | ord($sz[3]))
            : unpack('N', $sz)[1];
        fseek($fp, $skip - 4, SEEK_CUR);
    }
    $id_len = ($ver === 2) ? 3 : 4;
    $end    = 10 + $total;
    $want   = ($ver === 2)
        ? ['TT2' => 'title', 'TP1' => 'artist', 'TAL' => 'album']
        : ['TIT2' => 'title', 'TPE1' => 'artist', 'TALB' => 'album'];
    while (count($meta) < 3 && ftell($fp) < $end - $id_len - 3) {
        $fid = fread($fp, $id_len);
        if ($fid === false || ltrim($fid, "\x00") === '') break;
        if ($ver === 2) {
            $sz  = fread($fp, 3);
            $fsz = (ord($sz[0]) << 16) | (ord($sz[1]) << 8) | ord($sz[2]);
        } elseif ($ver === 4) {
            $sz  = fread($fp, 4);
            $fsz = (ord($sz[0]) << 21) | (ord($sz[1]) << 14) | (ord($sz[2]) << 7) | ord($sz[3]);
            fread($fp, 2);
        } else {
            $sz  = fread($fp, 4);
            $fsz = unpack('N', $sz)[1];
            fread($fp, 2);
        }
        if ($fsz <= 0 || $fsz > 100000) break;
        $data = fread($fp, $fsz);
        if (!isset($want[$fid]) || strlen($data) < 2) continue;
        $enc  = ord($data[0]);
        $text = substr($data, 1);
        switch ($enc) {
            case 0:
                $text = mb_convert_encoding(rtrim($text, "\x00"), 'UTF-8', 'ISO-8859-1');
                break;
            case 1:
                $bom = substr($text, 0, 2);
                $cs  = $bom === "\xfe\xff" ? 'UTF-16BE' : 'UTF-16LE';
                $text = mb_convert_encoding(substr($text, 2), 'UTF-8', $cs);
                break;
            case 2:
                $text = mb_convert_encoding($text, 'UTF-8', 'UTF-16BE');
                break;
            default:
                $text = rtrim($text, "\x00");
        }
        $text = trim($text);
        if ($text !== '') $meta[$want[$fid]] = $text;
    }
    fclose($fp);
    return $meta;
}

function read_metadata(string $path): array {
    $m = read_id3v2($path);
    return $m ?: read_id3v1($path);
}

function clean_filename(string $name): string {
    $name = preg_replace('/\.mp3$/i', '', $name);
    $name = str_replace(['_', '-'], ' ', $name);
    return strtoupper(substr($name, 0, 1)) . substr($name, 1);
}

function load_track_groups(): array {
    $path = __DIR__ . '/data/track_groups.csv';
    $map  = [];
    if (!file_exists($path)) return $map;
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $parts = explode(';', $line, 2);
        if (count($parts) === 2) $map[trim($parts[0])] = trim($parts[1]);
    }
    return $map;
}

function track_group(string $filename, array $map): string {
    foreach ($map as $prefix => $group) {
        if (str_starts_with($filename, $prefix)) return $group;
    }
    return '';
}

function user_can_see(string $track_group, array $user): bool {
    if ($user['admin']) return true;
    if (in_array('Alla', $user['groups'])) return true;
    if ($track_group === '') return true;
    return in_array($track_group, $user['groups']);
}

$track_group_map = load_track_groups();

// ── Skanna och gruppera filer per kanal ───────────────────────────────────────
const CH_SUFFIXES = ['_msc', '_bin', '_vce', '_env'];

$all_files = is_dir($music_dir)
    ? (glob($music_dir . DIRECTORY_SEPARATOR . '*.mp3') ?: [])
    : [];
sort($all_files);

$groups     = [];
$standalone = [];

foreach ($all_files as $f) {
    $fn = basename($f);
    if (preg_match('/^(.+?)(_msc|_bin|_vce|_env)\.mp3$/i', $fn, $m)) {
        $base = $m[1];
        $sfx  = strtolower($m[2]);
        if (!array_key_exists($base, $groups)) $groups[$base] = [];
        $groups[$base][$sfx] = $fn;
    } else {
        $standalone[] = $f;
    }
}

$tracks = [];

foreach ($groups as $base => $chans) {
    $main_fn = $chans['_msc'] ?? $chans['_vce'] ?? $chans['_env'] ?? $chans['_bin'] ?? null;
    if (!$main_fn) continue;
    $tgroup = track_group($main_fn, $track_group_map);
    if (!user_can_see($tgroup, $user)) continue;
    $meta = read_metadata($music_dir . DIRECTORY_SEPARATOR . ($chans['_msc'] ?? $main_fn));
    $u = fn($fn) => $fn ? $music_url . '/' . rawurlencode($fn) : null;
    $ch_msc = $chans['_msc'] ?? null;
    $ch_bin = $chans['_bin'] ?? null;
    $ch_vce = $chans['_vce'] ?? null;
    $ch_env = $chans['_env'] ?? null;
    if (!$ch_msc) {
        if ($ch_vce === $main_fn) $ch_vce = null;
        elseif ($ch_env === $main_fn) $ch_env = null;
        elseif ($ch_bin === $main_fn) $ch_bin = null;
    }
    $tracks[] = [
        'file'   => $music_url . '/' . rawurlencode($main_fn),
        'title'  => $meta['title']  ?? clean_filename($base),
        'artist' => $meta['artist'] ?? '',
        'album'  => $meta['album']  ?? '',
        'msc'    => $u($ch_msc ?? $main_fn),
        'bin'    => $u($ch_bin),
        'vce'    => $u($ch_vce),
        'env'    => $u($ch_env),
    ];
}

foreach ($standalone as $file) {
    $fn = basename($file);
    $tgroup = track_group($fn, $track_group_map);
    if (!user_can_see($tgroup, $user)) continue;
    $meta = read_metadata($file);
    $tracks[] = [
        'file'   => $music_url . '/' . rawurlencode($fn),
        'title'  => $meta['title']  ?? clean_filename($fn),
        'artist' => $meta['artist'] ?? '',
        'album'  => $meta['album']  ?? '',
        'msc'    => $music_url . '/' . rawurlencode($fn),
        'bin'    => null,
        'vce'    => null,
        'env'    => null,
    ];
}

$tracks_json = json_encode($tracks, JSON_UNESCAPED_UNICODE | JSON_HEX_TAG);
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title><?= htmlspecialchars($site_title) ?></title>
<link rel="stylesheet" href="style.css?v=<?= APP_VERSION ?>">
</head>
<body>
<div class="app">
  <header class="header">
    <h1><?= htmlspecialchars($site_title) ?></h1>
    <div class="header-user">
      <span><?= htmlspecialchars($user['display']) ?></span>
      <?php if (!empty($user['admin'])): ?><a href="admin/" style="font-size:0.82rem">Admin</a><?php endif ?>
      <a href="help.php" style="font-size:0.82rem">Hjälp</a>
      <a href="logout.php" class="btn-logout">Logga ut</a>
    </div>
  </header>

  <main class="player-area">
    <div class="now-playing" id="now-playing">
      <div class="track-title" id="track-title">Välj en låt</div>
      <div class="track-artist" id="track-artist"></div>
    </div>

    <audio id="audio-msc" preload="none"></audio>
    <audio id="audio-bin" preload="none"></audio>
    <audio id="audio-vce" preload="none"></audio>
    <audio id="audio-env" preload="none"></audio>

    <div class="controls">
      <button class="btn" id="btn-prev" title="Föregående">&#9664;&#9664;</button>
      <button class="btn btn-play" id="btn-play" title="Spela/Pausa">&#9654;</button>
      <button class="btn" id="btn-next" title="Nästa">&#9654;&#9654;</button>
    </div>

    <div class="progress-wrap">
      <span class="time" id="time-cur">0:00</span>
      <input type="range" id="seek" min="0" max="100" value="0" step="0.1">
      <span class="time" id="time-dur">0:00</span>
    </div>

    <div class="player-footer">
      <div class="mode-buttons">
        <button class="btn-mode" id="btn-repeat-one" title="Repetera låt">🔂</button>
        <button class="btn-mode" id="btn-repeat-all" title="Spela lista i loop">🔁</button>
        <button class="btn-mode" id="btn-shuffle"    title="Slumpa">🔀</button>
      </div>
      <button class="btn-settings-toggle" id="btn-settings" title="Ljudinställningar">&#9881; Ljud</button>
    </div>

    <div class="settings-panel" id="settings-panel">

      <div class="settings-section-title">Kanaler</div>

      <div class="setting-row" id="row-msc">
        <label>&#127925; Musik</label>
        <input type="range" id="s-msc" min="0" max="1" step="0.01" value="0.8">
        <span class="setting-val" id="lbl-msc">80%</span>
      </div>
      <div class="setting-row" id="row-bin" style="display:none">
        <label>&#128264; Binauralt</label>
        <input type="range" id="s-bin" min="0" max="1" step="0.01" value="0.5">
        <span class="setting-val" id="lbl-bin">50%</span>
      </div>
      <div class="setting-row" id="row-vce" style="display:none">
        <label>&#127897; Röst</label>
        <input type="range" id="s-vce" min="0" max="1" step="0.01" value="0.9">
        <span class="setting-val" id="lbl-vce">90%</span>
      </div>
      <div class="setting-row" id="row-env" style="display:none">
        <label>&#127807; Miljö</label>
        <input type="range" id="s-env" min="0" max="1" step="0.01" value="0.4">
        <span class="setting-val" id="lbl-env">40%</span>
      </div>

      <div class="settings-divider"></div>
      <div class="settings-section-title">Equalizer — musikkanal</div>

      <div class="setting-row">
        <label>Balans</label>
        <input type="range" id="s-balance" min="-1" max="1" step="0.01" value="0">
        <span class="setting-val" id="lbl-balance">C</span>
      </div>
      <div class="setting-row">
        <label>Bas</label>
        <input type="range" id="s-bass" min="-12" max="12" step="0.5" value="0">
        <span class="setting-val" id="lbl-bass">0.0 dB</span>
      </div>
      <div class="setting-row">
        <label>Diskant</label>
        <input type="range" id="s-treble" min="-12" max="12" step="0.5" value="0">
        <span class="setting-val" id="lbl-treble">0.0 dB</span>
      </div>

      <div class="settings-divider"></div>
      <div class="settings-section-title">Uppspelning</div>

      <div class="setting-row">
        <label>Hastighet</label>
        <input type="range" id="s-speed" min="0.5" max="2" step="0.05" value="1">
        <span class="setting-val" id="lbl-speed">1×</span>
      </div>

      <p class="settings-note">Sparas automatiskt. Övriga kanaler spelas i ren stereo utan EQ.</p>
    </div>
  </main>

  <section class="playlist" id="playlist">

    <div class="playlist-tabs">
      <button class="tab-btn active" id="tab-lib">Bibliotek</button>
      <button class="tab-btn" id="tab-queue">Kö <span class="queue-badge" id="queue-badge">0</span></button>
      <button class="tab-btn" id="tab-pl">Spellistor</button>
    </div>

    <div id="view-lib">
    <?php if (empty($tracks)): ?>
    <div class="empty">Inga MP3-filer hittades i <code>/music/</code>.</div>
    <?php else: ?>
    <ul id="track-list">
      <?php
      // Gruppera spår efter album i ursprunglig ordning
      $album_order  = [];
      $album_groups = [];
      foreach ($tracks as $i => $t) {
          $al = $t['album'];
          if (!array_key_exists($al, $album_groups)) {
              $album_order[]     = $al;
              $album_groups[$al] = [];
          }
          $album_groups[$al][] = $i;
      }
      foreach ($album_order as $al):
          $indices = $album_groups[$al];
          if ($al !== ''):
      ?>
      <li class="album-section" data-album="<?= htmlspecialchars($al, ENT_QUOTES) ?>">
        <div class="album-header">
          <button class="album-toggle" title="Visa/dölj">▾</button>
          <span class="album-name"><?= htmlspecialchars($al) ?></span>
          <span class="album-count"><?= count($indices) ?></span>
          <button class="btn-play-album" data-album="<?= htmlspecialchars($al, ENT_QUOTES) ?>" title="Spela hela albumet">▶</button>
        </div>
        <ul class="album-tracks">
      <?php endif ?>
      <?php foreach ($indices as $i): $t = $tracks[$i]; ?>
          <li class="track-item" data-index="<?= $i ?>">
            <span class="track-num"><?= $i + 1 ?></span>
            <div class="track-info">
              <span class="t-title"><?= htmlspecialchars($t['title']) ?></span>
              <?php if ($t['artist']): ?>
              <span class="t-artist"><?= htmlspecialchars($t['artist']) ?></span>
              <?php endif ?>
              <span class="t-channels">
                <?php foreach (['msc'=>'♪','bin'=>'≋','vce'=>'◎','env'=>'〜'] as $ch => $icon): ?>
                  <?php if ($t[$ch]): ?><span title="<?= ['msc'=>'Musik','bin'=>'Binauralt','vce'=>'Röst','env'=>'Miljö'][$ch] ?>"><?= $icon ?></span><?php endif ?>
                <?php endforeach ?>
              </span>
            </div>
            <button class="btn-add-pl" data-index="<?= $i ?>" title="Spara i spellista">☰</button>
            <button class="btn-add-queue" data-index="<?= $i ?>" title="Lägg till i kö">+</button>
          </li>
      <?php endforeach ?>
      <?php if ($al !== ''): ?>
        </ul>
      </li>
      <?php endif ?>
      <?php endforeach ?>
    </ul>
    <?php endif ?>
    </div>

    <div id="view-queue" hidden>
      <ul id="queue-list"></ul>
      <p class="queue-empty-msg" id="queue-empty-msg">Kön är tom — lägg till spår med <strong>+</strong> i biblioteket.</p>
    </div>

    <div id="view-pl" hidden>
      <div class="pl-toolbar">
        <input type="text" id="pl-new-name" class="pl-new-input" placeholder="Ny spellista…" maxlength="80">
        <button class="btn-create-pl" id="btn-create-pl">Skapa</button>
      </div>
      <ul id="pl-list"></ul>
      <p class="queue-empty-msg" id="pl-empty-msg">Inga spellistor ännu — lägg till spår med ☰.</p>
    </div>

  </section>

  <div id="pl-dropdown" class="pl-dropdown" hidden>
    <ul id="pl-dropdown-list"></ul>
  </div>
</div>

<footer class="app-version">v<?= APP_VERSION ?></footer>

<script>
const TRACKS  = <?= $tracks_json ?>;
const CM_USER = <?= json_encode($user['username']) ?>;
</script>
<script src="player.js?v=<?= APP_VERSION ?>"></script>
</body>
</html>
