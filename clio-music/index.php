<?php
require_once 'auth.php';
require_once 'config.php';
require_login();

$user = current_user();

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
// Kanalernas suffix: _msc=musik, _bin=binauralt, _vce=röst, _env=miljö
// Filer utan suffix behandlas som fristående musikspår (bakåtkompatibilitet).

const CH_SUFFIXES = ['_msc', '_bin', '_vce', '_env'];

$all_files = is_dir($music_dir)
    ? (glob($music_dir . DIRECTORY_SEPARATOR . '*.mp3') ?: [])
    : [];
sort($all_files);

$groups     = [];   // [base => ['_msc'=>filename, ...]]
$standalone = [];   // filer utan igenkänt suffix

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

// Grupperade spår (4-kanals meditationer)
foreach ($groups as $base => $chans) {
    $main_fn = $chans['_msc'] ?? $chans['_vce'] ?? $chans['_env'] ?? $chans['_bin'] ?? null;
    if (!$main_fn) continue;
    $tgroup = track_group($main_fn, $track_group_map);
    if (!user_can_see($tgroup, $user)) continue;
    $u = fn($fn) => $fn ? $music_url . '/' . rawurlencode($fn) : null;
    // msc är master i JS-spelaren (driver progress/ended).
    // Om _msc saknas: använd primary-filen som msc och nolla ur dess kanal för att undvika dubbelspelning.
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
        'title'  => clean_filename($base),
        'artist' => '',
        'album'  => '',
        'msc'    => $u($ch_msc ?? $main_fn),
        'bin'    => $u($ch_bin),
        'vce'    => $u($ch_vce),
        'env'    => $u($ch_env),
    ];
}

// Fristående filer (bakåtkompatibilitet)
foreach ($standalone as $file) {
    $fn = basename($file);
    $tgroup = track_group($fn, $track_group_map);
    if (!user_can_see($tgroup, $user)) continue;
    $meta = read_id3v1($file);
    $tracks[] = [
        'file'   => $music_url . '/' . rawurlencode($fn),
        'title'  => $meta['title'] ?? clean_filename($fn),
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
<link rel="stylesheet" href="style.css">
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
    <?php if (empty($tracks)): ?>
    <div class="empty">Inga MP3-filer hittades i <code>/music/</code>.</div>
    <?php else: ?>
    <ul id="track-list">
      <?php foreach ($tracks as $i => $t): ?>
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
      </li>
      <?php endforeach ?>
    </ul>
    <?php endif ?>
  </section>
</div>

<footer class="app-version">v<?= APP_VERSION ?></footer>

<script>
const TRACKS  = <?= $tracks_json ?>;
const CM_USER = <?= json_encode($user['username']) ?>;
</script>
<script src="player.js?v=<?= APP_VERSION ?>"></script>
</body>
</html>
