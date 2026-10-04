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

// ── Läs och aggregera spelloggen ──────────────────────────────────────────────
$log_file = dirname(__DIR__) . '/data/plays.jsonl';
$plays    = [];   // [track][username] = count
$totals   = [];   // [track] = total count
$user_totals = []; // [username] = total count
$last_play   = []; // [track][username] = ts

if (file_exists($log_file)) {
    foreach (file($log_file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $e = json_decode($line, true);
        if (!$e || empty($e['user']) || empty($e['track'])) continue;
        $u = $e['user'];
        $t = $e['track'];
        $plays[$t][$u] = ($plays[$t][$u] ?? 0) + 1;
        $totals[$t]     = ($totals[$t] ?? 0) + 1;
        $user_totals[$u]= ($user_totals[$u] ?? 0) + 1;
        if (!isset($last_play[$t][$u]) || $e['ts'] > $last_play[$t][$u]) {
            $last_play[$t][$u] = $e['ts'];
        }
    }
}

arsort($totals);
arsort($user_totals);

// Hämta alla aktiva användare från users.csv
function get_all_users(): array {
    $path = dirname(__DIR__) . '/data/users.csv';
    $out  = [];
    if (!file_exists($path)) return $out;
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $p = str_getcsv($line, ';');
        if (count($p) >= 4 && (int)$p[3] === 1) {
            $groups = isset($p[5]) ? array_map('trim', explode('|', $p[5])) : [];
            $out[strtolower(trim($p[0]))] = [
                'display' => trim($p[2]),
                'groups'  => $groups,
            ];
        }
    }
    return $out;
}

$all_users = get_all_users(); // [username => ['display'=>..., 'groups'=>[...]]]

// Collect all groups
$all_groups = ['Alla lyssnare'];
foreach ($all_users as $u) {
    foreach ($u['groups'] as $g) {
        if (!in_array($g, $all_groups)) $all_groups[] = $g;
    }
}
sort($all_groups);

$group_filter = $_GET['group'] ?? '';

function load_track_groups(): array {
    $path = dirname(__DIR__) . '/data/track_groups.csv';
    $map  = [];
    if (!file_exists($path)) return $map;
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (str_starts_with(trim($line), '#')) continue;
        $parts = explode(';', $line, 2);
        if (count($parts) === 2) $map[trim($parts[0])] = trim($parts[1]);
    }
    return $map;
}

function track_group_label(string $track, array $map): string {
    $filename = preg_replace('#^music/#', '', $track);
    $filename = rawurldecode($filename);
    foreach ($map as $prefix => $group) {
        if (str_starts_with($filename, $prefix)) return $group;
    }
    return '';
}

$track_group_map = load_track_groups();

function track_label(string $t): string {
    $name = preg_replace('#^music/#', '', $t);
    $name = rawurldecode($name);
    $name = preg_replace('/\.mp3$/i', '', $name);
    return str_replace(['_', '-'], ' ', $name);
}

function fmt_ts(int $ts): string {
    return date('Y-m-d H:i', $ts);
}

$total_plays = array_sum($totals);
$view = $_GET['view'] ?? 'tracks'; // tracks | users
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin — <?= htmlspecialchars($site_title) ?></title>
<style>
:root {
  --bg:#111317; --surface:#1c1f26; --surface2:#252932;
  --border:#2e3340; --accent:#4e9eff; --accent2:#7ec8e3;
  --text:#e2e6ef; --muted:#7a8299; --pos:#4ade80;
}
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; font-size:14px; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }

.header { padding:16px 24px; background:var(--surface); border-bottom:1px solid var(--border);
  display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }
.header h1 { font-size:1.1rem; color:var(--accent2); }
.header-links { display:flex; gap:12px; font-size:0.85rem; }

.stats-row { display:flex; gap:12px; padding:16px 24px; flex-wrap:wrap; }
.stat-card { background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:12px 20px; min-width:130px; }
.stat-card .val { font-size:1.6rem; font-weight:700; color:var(--accent); }
.stat-card .lbl { font-size:0.78rem; color:var(--muted); margin-top:2px; }

.tabs { display:flex; gap:0; padding:0 24px; border-bottom:1px solid var(--border); margin-top:4px; }
.tab { padding:10px 18px; font-size:0.88rem; color:var(--muted); cursor:pointer;
  border-bottom:2px solid transparent; text-decoration:none; }
.tab.active { color:var(--accent2); border-color:var(--accent2); }

.content { padding:16px 24px; }

/* ── Track table ── */
table { width:100%; border-collapse:collapse; font-size:0.85rem; }
th { text-align:left; padding:8px 10px; color:var(--muted); font-weight:500;
  border-bottom:1px solid var(--border); white-space:nowrap; }
td { padding:7px 10px; border-bottom:1px solid var(--border); vertical-align:top; }
tr:hover td { background:var(--surface); }

.badge { display:inline-block; background:var(--accent); color:#fff;
  border-radius:10px; padding:1px 8px; font-size:0.78rem; font-weight:600; }
.badge-muted { background:var(--surface2); color:var(--muted); }

.bar-wrap { display:flex; align-items:center; gap:8px; }
.bar { height:6px; background:var(--accent); border-radius:3px; min-width:2px; }

.user-pills { display:flex; flex-wrap:wrap; gap:4px; margin-top:4px; }
.pill { background:var(--surface2); border:1px solid var(--border); border-radius:12px;
  padding:2px 8px; font-size:0.75rem; color:var(--muted); }
.pill strong { color:var(--text); }

.empty { padding:40px; text-align:center; color:var(--muted); }

.group-bar { display:flex; align-items:center; gap:6px; padding:10px 24px;
  background:var(--surface); border-bottom:1px solid var(--border); flex-wrap:wrap; }
.group-label { font-size:0.78rem; color:var(--muted); margin-right:2px; }
.group-btn { padding:3px 12px; border-radius:12px; font-size:0.82rem;
  background:var(--surface2); color:var(--muted); text-decoration:none;
  border:1px solid var(--border); }
.group-btn:hover { color:var(--text); text-decoration:none; }
.group-btn.active { background:var(--accent); color:#fff; border-color:var(--accent); }
</style>
</head>
<body>
<div class="header">
  <h1>&#9881; Admin — <?= htmlspecialchars($site_title) ?></h1>
  <div class="header-links">
    <a href="groups.php">&#128101; Grupper</a>
    <a href="../help.php">Hjälp</a>
    <a href="../index.php">← Spelaren</a>
    <a href="../logout.php">Logga ut</a>
  </div>
</div>

<div class="stats-row">
  <div class="stat-card"><div class="val"><?= $total_plays ?></div><div class="lbl">Spelningar totalt</div></div>
  <div class="stat-card"><div class="val"><?= count($totals) ?></div><div class="lbl">Låtar spelade</div></div>
  <div class="stat-card"><div class="val"><?= count($user_totals) ?></div><div class="lbl">Aktiva lyssnare</div></div>
  <div class="stat-card"><div class="val"><?= count($all_users) ?></div><div class="lbl">Registrerade</div></div>
</div>

<div class="tabs">
  <a class="tab <?= $view === 'tracks' ? 'active' : '' ?>" href="?view=tracks&group=<?= urlencode($group_filter) ?>">Per låt</a>
  <a class="tab <?= $view === 'users'  ? 'active' : '' ?>" href="?view=users&group=<?= urlencode($group_filter) ?>">Per användare</a>
</div>
<div class="group-bar">
  <span class="group-label">Grupp:</span>
  <a class="group-btn <?= $group_filter === '' ? 'active' : '' ?>" href="?view=<?= $view ?>">Alla lyssnare</a>
  <?php foreach (array_filter($all_groups, fn($g) => $g !== 'Alla lyssnare') as $g): ?>
  <a class="group-btn <?= $group_filter === $g ? 'active' : '' ?>" href="?view=<?= $view ?>&group=<?= urlencode($g) ?>"><?= htmlspecialchars($g) ?></a>
  <?php endforeach ?>
</div>

<div class="content">
<?php if ($total_plays === 0): ?>
  <div class="empty">Inga spelningar loggade än. Spela en låt i spelaren för att börja.</div>

<?php elseif ($view === 'tracks'): ?>
  <?php $max = max($totals ?: [1]); ?>
  <table>
    <thead>
      <tr><th>Låt</th><th>Grupp</th><th>Spelningar</th><th>Lyssnare</th><th>Senast spelad</th></tr>
    </thead>
    <tbody>
    <?php foreach ($totals as $track => $cnt): ?>
      <?php
        $user_plays = $plays[$track] ?? [];
        arsort($user_plays);
        $latest_ts = max(array_map('max', array_map(fn($u) => [$last_play[$track][$u] ?? 0], array_keys($user_plays))));
      ?>
      <?php $tgrp = track_group_label($track, $track_group_map); ?>
      <tr>
        <td><?= htmlspecialchars(track_label($track)) ?></td>
        <td><?php if ($tgrp): ?><span class="pill" style="background:var(--accent);color:#fff"><?= htmlspecialchars($tgrp) ?></span><?php else: ?><span style="color:var(--muted)">—</span><?php endif ?></td>
        <td>
          <div class="bar-wrap">
            <div class="bar" style="width:<?= round($cnt / $max * 120) ?>px"></div>
            <span class="badge"><?= $cnt ?></span>
          </div>
        </td>
        <td>
          <div class="user-pills">
          <?php foreach ($user_plays as $u => $n): ?>
            <span class="pill"><strong><?= htmlspecialchars($all_users[$u]['display'] ?? $u) ?></strong> &times;<?= $n ?></span>
          <?php endforeach ?>
          </div>
        </td>
        <td style="color:var(--muted);white-space:nowrap"><?= $latest_ts ? fmt_ts($latest_ts) : '—' ?></td>
      </tr>
    <?php endforeach ?>
    </tbody>
  </table>

<?php elseif ($view === 'users'): ?>
  <table>
    <thead>
      <tr><th>Användare</th><th>Totalt</th><th>Låtar lyssnade på</th></tr>
    </thead>
    <tbody>
    <?php
      // Build per-user track list
      $user_tracks = [];
      foreach ($plays as $track => $umap) {
          foreach ($umap as $u => $n) {
              $user_tracks[$u][$track] = $n;
          }
      }
      foreach ($user_tracks as &$ut) arsort($ut);
      arsort($user_totals);
    ?>
    <?php foreach ($user_totals as $u => $total): ?>
      <tr>
        <td><strong><?= htmlspecialchars($all_users[$u]['display'] ?? $u) ?></strong><br>
            <span style="color:var(--muted);font-size:0.78rem"><?= htmlspecialchars($u) ?></span><?php
            $ugrps = $all_users[$u]['groups'] ?? [];
            if ($ugrps): ?><br><span style="color:var(--muted);font-size:0.75rem"><?= htmlspecialchars(implode(', ', $ugrps)) ?></span><?php endif ?>
        </td>
        <td><span class="badge"><?= $total ?></span></td>
        <td>
          <div class="user-pills">
          <?php foreach ($user_tracks[$u] ?? [] as $t => $n): ?>
            <span class="pill"><strong><?= htmlspecialchars(track_label($t)) ?></strong> &times;<?= $n ?></span>
          <?php endforeach ?>
          </div>
        </td>
      </tr>
    <?php endforeach ?>
    <?php
      // Visa registrerade users som aldrig spelat
      foreach ($all_users as $u => $udata) {
          if (isset($user_totals[$u])) continue;
          $display = $udata['display'];
          $ugrps   = $udata['groups'] ?? [];
    ?>
      <tr>
        <td><?= htmlspecialchars($display) ?><br>
            <span style="color:var(--muted);font-size:0.78rem"><?= htmlspecialchars($u) ?></span><?php
            if ($ugrps): ?><br><span style="color:var(--muted);font-size:0.75rem"><?= htmlspecialchars(implode(', ', $ugrps)) ?></span><?php endif ?>
        </td>
        <td><span class="badge badge-muted">0</span></td>
        <td style="color:var(--muted)">Ingen spelning loggad</td>
      </tr>
    <?php } ?>
    </tbody>
  </table>
<?php endif ?>
</div>
</body>
</html>
