<?php
require_once dirname(__DIR__) . '/auth.php';
require_once dirname(__DIR__) . '/config.php';
require_login();

$user = current_user();
if (empty($user['admin'])) {
    http_response_code(403);
    echo '<h2>Åtkomst nekad</h2>';
    exit;
}

$users_file  = dirname(__DIR__) . '/data/users.csv';
$tracks_file = dirname(__DIR__) . '/data/track_groups.csv';

// ── Hjälpfunktioner ───────────────────────────────────────────────────────────

function read_users(): array {
    global $users_file;
    $out = [];
    if (!file_exists($users_file)) return $out;
    foreach (file($users_file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $p = str_getcsv($line, ';');
        if (count($p) < 4) continue;
        $uname = strtolower(trim($p[0]));
        $out[$uname] = [
            'display' => trim($p[2]),
            'active'  => (int)$p[3],
            'admin'   => isset($p[4]) ? (int)trim($p[4]) : 0,
            'groups'  => isset($p[5]) && trim($p[5]) !== ''
                         ? array_map('trim', explode('|', $p[5]))
                         : [],
        ];
    }
    return $out;
}

function read_track_groups(): array {
    global $tracks_file;
    $map = [];
    if (!file_exists($tracks_file)) return $map;
    foreach (file($tracks_file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $p = explode(';', $line, 2);
        if (count($p) === 2) $map[trim($p[0])] = trim($p[1]);
    }
    return $map;
}

function all_groups(array $users, array $tg_map): array {
    $groups = [GUEST_GROUP];
    foreach ($users as $u) {
        foreach ($u['groups'] as $g) {
            if (!in_array($g, $groups)) $groups[] = $g;
        }
    }
    foreach ($tg_map as $g) {
        if (!in_array($g, $groups)) $groups[] = $g;
    }
    sort($groups);
    return $groups;
}

function scan_tracks(): array {
    global $music_dir;
    $files = glob($music_dir . DIRECTORY_SEPARATOR . '*.mp3') ?: [];
    sort($files);
    return array_map('basename', $files);
}

function track_assigned_group(string $filename, array $tg_map): string {
    // Exact match first, then prefix
    if (isset($tg_map[$filename])) return $tg_map[$filename];
    foreach ($tg_map as $prefix => $group) {
        if (str_starts_with($filename, $prefix)) return $group;
    }
    return '';
}

function save_user_groups(array $new_groups): string {
    global $users_file;
    if (!file_exists($users_file)) return 'Filen users.csv saknas.';
    $lines = file($users_file, FILE_IGNORE_NEW_LINES);
    $out   = [];
    foreach ($lines as $line) {
        if (str_starts_with(trim($line), '#') || trim($line) === '') {
            $out[] = $line;
            continue;
        }
        $p = str_getcsv($line, ';');
        if (count($p) >= 4) {
            $uname = strtolower(trim($p[0]));
            while (count($p) < 6) $p[] = '';
            $p[5] = implode('|', $new_groups[$uname] ?? []);
        }
        $out[] = implode(';', $p);
    }
    if (file_put_contents($users_file, implode("\n", $out) . "\n") === false)
        return 'Kunde inte skriva users.csv.';
    return '';
}

function save_track_groups(array $assignments): string {
    global $tracks_file;
    $lines = [
        '# Låt-grupptillhörighet',
        '# Format: filnamn.mp3;grupp  (sparat av admin-gränssnittet)',
        '# Låtar utan rad visas för alla inloggade.',
    ];
    foreach ($assignments as $file => $group) {
        if ($group !== '') $lines[] = $file . ';' . $group;
    }
    if (file_put_contents($tracks_file, implode("\n", $lines) . "\n") === false)
        return 'Kunde inte skriva track_groups.csv.';
    return '';
}

// ── POST-hantering ────────────────────────────────────────────────────────────
$flash = '';
$tab   = $_GET['tab'] ?? 'users';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (isset($_POST['save_users'])) {
        $tab       = 'users';
        $submitted = $_POST['ug'] ?? [];          // [username][group] => '1'
        $all_u     = read_users();
        $new_groups = [];
        foreach (array_keys($all_u) as $uname) {
            $checked = [];
            foreach ($_POST['groups_list'] ?? [] as $g) {
                if (!empty($submitted[$uname][$g])) $checked[] = $g;
            }
            $new_groups[$uname] = $checked;
        }
        $err   = save_user_groups($new_groups);
        $flash = $err ?: 'Användargrupper sparade.';
    } elseif (isset($_POST['save_tracks'])) {
        $tab         = 'tracks';
        $assignments = [];
        foreach ($_POST['tg'] ?? [] as $file => $group) {
            $assignments[basename($file)] = $group;
        }
        $err   = save_track_groups($assignments);
        $flash = $err ?: 'Låtgrupper sparade.';
    } elseif (isset($_POST['add_group'])) {
        $tab      = 'users';
        $new_name = trim($_POST['new_group_name'] ?? '');
        $flash    = $new_name ? '' : 'Ange ett gruppnamn.';
        // Groups are implicit — just remind admin to assign users
        if ($new_name) $flash = "Gruppen \"$new_name\" är redo att tilldelas. Kryssa i den nedan.";
    }
}

// ── Data till vyn ─────────────────────────────────────────────────────────────
$all_users    = read_users();
$tg_map       = read_track_groups();
$groups       = all_groups($all_users, $tg_map);
$track_groups_noalla = array_values(array_filter($groups, fn($g) => $g !== 'Alla'));
$tracks       = scan_tracks();

// Pending new group from form
$pending_new  = trim($_POST['new_group_name'] ?? '');
if ($pending_new && !in_array($pending_new, $groups)) {
    $groups[] = $pending_new;
    sort($groups);
    if ($pending_new !== 'Alla') $track_groups_noalla[] = $pending_new;
}
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Grupper — <?= htmlspecialchars($site_title) ?></title>
<style>
:root {
  --bg:#111317; --surface:#1c1f26; --surface2:#252932;
  --border:#2e3340; --accent:#4e9eff; --accent2:#7ec8e3;
  --text:#e2e6ef; --muted:#7a8299; --pos:#4ade80; --neg:#f87171;
}
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; font-size:14px; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }

.header { padding:16px 24px; background:var(--surface); border-bottom:1px solid var(--border);
  display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }
.header h1 { font-size:1.1rem; color:var(--accent2); }
.header-links { display:flex; gap:12px; font-size:0.85rem; }

.flash { padding:10px 24px; font-size:0.88rem;
  background:color-mix(in srgb, var(--pos) 15%, var(--surface));
  border-bottom:1px solid color-mix(in srgb, var(--pos) 40%, transparent);
  color:var(--pos); }
.flash.err { background:color-mix(in srgb, var(--neg) 15%, var(--surface));
  border-color:color-mix(in srgb, var(--neg) 40%, transparent); color:var(--neg); }

.tabs { display:flex; padding:0 24px; border-bottom:1px solid var(--border); margin-top:4px; }
.tab { padding:10px 18px; font-size:0.88rem; color:var(--muted);
  border-bottom:2px solid transparent; text-decoration:none; }
.tab.active { color:var(--accent2); border-color:var(--accent2); }

.content { padding:20px 24px; }

table { width:100%; border-collapse:collapse; font-size:0.85rem; }
th { text-align:left; padding:8px 10px; color:var(--muted); font-weight:500;
  border-bottom:1px solid var(--border); white-space:nowrap; }
td { padding:8px 10px; border-bottom:1px solid var(--border); vertical-align:middle; }
tr:hover td { background:var(--surface); }

.cb-wrap { display:flex; flex-wrap:wrap; gap:12px; }
.cb-label { display:flex; align-items:center; gap:5px; cursor:pointer;
  background:var(--surface2); border:1px solid var(--border);
  border-radius:14px; padding:3px 10px; font-size:0.82rem; color:var(--muted);
  transition:border-color .15s, color .15s; }
.cb-label:has(input:checked) { border-color:var(--accent); color:var(--text); }
.cb-label input { accent-color:var(--accent); }

.radio-wrap { display:flex; flex-wrap:wrap; gap:10px; }
.rb-label { display:flex; align-items:center; gap:5px; cursor:pointer;
  background:var(--surface2); border:1px solid var(--border);
  border-radius:14px; padding:3px 10px; font-size:0.82rem; color:var(--muted);
  transition:border-color .15s, color .15s; }
.rb-label:has(input:checked) { border-color:var(--accent2); color:var(--text); }
.rb-label input { accent-color:var(--accent2); }

.save-bar { position:sticky; bottom:0; background:var(--surface);
  border-top:1px solid var(--border); padding:12px 24px;
  display:flex; align-items:center; gap:12px; }
.btn-save { background:var(--accent); color:#fff; border:none; border-radius:6px;
  padding:8px 22px; font-size:0.9rem; cursor:pointer; font-weight:600; }
.btn-save:hover { opacity:.88; }

.new-group-row { display:flex; gap:8px; align-items:center; margin-bottom:16px; }
.new-group-row input[type=text] { background:var(--surface2); border:1px solid var(--border);
  border-radius:6px; padding:6px 12px; color:var(--text); font-size:0.88rem; width:180px; }
.new-group-row input[type=text]:focus { outline:none; border-color:var(--accent); }
.btn-add { background:var(--surface2); border:1px solid var(--border); color:var(--text);
  border-radius:6px; padding:6px 14px; font-size:0.85rem; cursor:pointer; }
.btn-add:hover { border-color:var(--accent); }

.track-num { color:var(--muted); font-size:0.8rem; width:36px; flex-shrink:0; }
.track-name { flex:1; }
.no-tracks { padding:30px; text-align:center; color:var(--muted); }
</style>
</head>
<body>
<div class="header">
  <h1>&#128101; Grupper — <?= htmlspecialchars($site_title) ?></h1>
  <div class="header-links">
    <a href="index.php">← Dashboard</a>
    <a href="../index.php">Spelaren</a>
    <a href="../logout.php">Logga ut</a>
  </div>
</div>

<?php if ($flash): ?>
<div class="flash <?= str_contains($flash, 'Kunde') ? 'err' : '' ?>"><?= htmlspecialchars($flash) ?></div>
<?php endif ?>

<div class="tabs">
  <a class="tab <?= $tab === 'users'  ? 'active' : '' ?>" href="?tab=users">Användare</a>
  <a class="tab <?= $tab === 'tracks' ? 'active' : '' ?>" href="?tab=tracks">Låtar</a>
</div>

<div class="content">

<?php if ($tab === 'users'): ?>
<!-- ── Användar-grupptillhörighet ──────────────────────────────────────────── -->
<form method="post" action="?tab=users">
  <?php foreach ($groups as $g): ?>
  <input type="hidden" name="groups_list[]" value="<?= htmlspecialchars($g) ?>">
  <?php endforeach ?>

  <div class="new-group-row">
    <input type="text" name="new_group_name" placeholder="Ny grupp…"
           value="<?= htmlspecialchars($pending_new) ?>" maxlength="40">
    <button type="submit" name="add_group" class="btn-add">+ Lägg till grupp</button>
  </div>

  <table>
    <thead>
      <tr>
        <th>Användare</th>
        <?php foreach ($groups as $g): ?>
        <th><?= htmlspecialchars($g) ?></th>
        <?php endforeach ?>
      </tr>
    </thead>
    <tbody>
    <?php foreach ($all_users as $uname => $udata): ?>
      <tr>
        <td>
          <strong><?= htmlspecialchars($udata['display']) ?></strong><br>
          <span style="color:var(--muted);font-size:0.78rem"><?= htmlspecialchars($uname) ?></span>
        </td>
        <?php foreach ($groups as $g): ?>
        <td>
          <label class="cb-label">
            <input type="checkbox" name="ug[<?= htmlspecialchars($uname) ?>][<?= htmlspecialchars($g) ?>]"
              value="1" <?= in_array($g, $udata['groups']) ? 'checked' : '' ?>>
            <?= htmlspecialchars($g) ?>
          </label>
        </td>
        <?php endforeach ?>
      </tr>
    <?php endforeach ?>
    </tbody>
  </table>

  <div class="save-bar">
    <button type="submit" name="save_users" class="btn-save">Spara användargrupper</button>
    <span style="color:var(--muted);font-size:0.82rem">Användare i "Alla" ser alla låtar oavsett låttilldelning.</span>
  </div>
</form>

<?php elseif ($tab === 'tracks'): ?>
<!-- ── Låt-grupptillhörighet ──────────────────────────────────────────────── -->
<?php if (empty($tracks)): ?>
  <div class="no-tracks">Inga MP3-filer hittades i <code>/music/</code>.</div>
<?php else: ?>
<form method="post" action="?tab=tracks">
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Låt</th>
        <th>Grupp</th>
      </tr>
    </thead>
    <tbody>
    <?php foreach ($tracks as $i => $filename): ?>
      <?php $assigned = track_assigned_group($filename, $tg_map); ?>
      <tr>
        <td class="track-num"><?= $i + 1 ?></td>
        <td class="track-name"><?= htmlspecialchars(preg_replace('/\.mp3$/i', '', str_replace(['_','-'], ' ', $filename))) ?></td>
        <td>
          <div class="radio-wrap">
            <label class="rb-label">
              <input type="radio" name="tg[<?= htmlspecialchars($filename) ?>]"
                value="" <?= $assigned === '' ? 'checked' : '' ?>>
              Alla
            </label>
            <?php foreach ($track_groups_noalla as $g): ?>
            <label class="rb-label">
              <input type="radio" name="tg[<?= htmlspecialchars($filename) ?>]"
                value="<?= htmlspecialchars($g) ?>" <?= $assigned === $g ? 'checked' : '' ?>>
              <?= htmlspecialchars($g) ?>
            </label>
            <?php endforeach ?>
          </div>
        </td>
      </tr>
    <?php endforeach ?>
    </tbody>
  </table>

  <div class="save-bar">
    <button type="submit" name="save_tracks" class="btn-save">Spara låtgrupper</button>
    <span style="color:var(--muted);font-size:0.82rem">"Alla" = låten visas för alla inloggade.</span>
  </div>
</form>
<?php endif ?>
<?php endif ?>

</div><!-- .content -->
</body>
</html>
