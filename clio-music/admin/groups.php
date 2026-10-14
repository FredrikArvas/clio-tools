<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * admin/groups.php — vy och formulärhantering för användar- och spårgrupper (bara admin).
 *
 * Anropas av: webbläsaren (länk från admin/index.php). All läsning/validering/skrivning av
 * data ligger i admin/groups_store.php; den här filen tolkar bara formuläret, anropar
 * lagret och ritar sidan.
 *
 * Säkerhetsantaganden:
 * - Icke-admin får 403 före allt annat. Varje POST kräver CSRF-token (csrf_require) innan något
 *   läses ur formuläret.
 * - Inget i formuläret litas på: användare, grupper och filer valideras mot kända mängder i
 *   groups_store.php. Fel ger 400 och ingenting skrivs.
 * - Varje sparning och varje avvisad sparning loggas i auditloggen (utan hashar).
 * - All utskrift går genom escape_html() (ENT_QUOTES), även i attribut.
 */
require_once dirname(__DIR__) . '/auth.php';
require_once dirname(__DIR__) . '/config.php';
require_once dirname(__DIR__) . '/csrf.php';
require_once dirname(__DIR__) . '/access.php';
require_once __DIR__ . '/groups_store.php';
require_login();

$user = current_user();
if (empty($user['admin'])) {
    http_response_code(403);
    echo '<h2>Åtkomst nekad</h2>';
    exit;
}

$users_file  = dirname(__DIR__) . '/data/users.csv';
$tracks_file = dirname(__DIR__) . '/data/track_groups.csv';

const INVALID_GROUP_MESSAGE = 'Ogiltigt gruppnamn. Använd 1–40 bokstäver, siffror, mellanslag, understreck eller bindestreck.';

// ── Hjälpfunktioner för formulär och svar ─────────────────────────────────────

function escape_html(string $text): string {
    return htmlspecialchars($text, ENT_QUOTES, 'UTF-8');
}

function outcome(string $message, int $status = 200): array {
    return ['message' => $message, 'status' => $status];
}

/** Det nya gruppnamn admin skrivit i rutan (trimmat), eller '' om fältet saknas/inte är text. */
function posted_new_group_name(): string {
    $name = $_POST['new_group_name'] ?? '';
    return is_string($name) ? trim($name) : '';
}

/** Loggar en avvisad ändring och returnerar svaret till admin (400 = fel i formuläret). */
function reject_change(string $scope, string $reason, int $status = 400): array {
    audit_log('admin_groups_rejected', ['scope' => $scope, 'reason' => $reason]);
    return outcome($reason, $status);
}

// ── POST-hanterare: var och en returnerar outcome() ──────────────────────────

/** "Lägg till grupp" skriver inget: gruppen finns först när någon kryssats i och användarna sparats. */
function handle_add_group(): array {
    $name = posted_new_group_name();
    if ($name === '') return outcome('Ange ett gruppnamn.', 400);
    if (!is_valid_group_name($name)) return reject_change('users', INVALID_GROUP_MESSAGE);
    return outcome('Gruppen "' . $name . '" är redo att tilldelas. Kryssa i den nedan och spara.');
}

function handle_save_users(string $users_file, array $track_map): array {
    $users    = read_admin_users($users_file);
    $new_name = posted_new_group_name();
    if ($new_name !== '' && !is_valid_group_name($new_name)) return reject_change('users', INVALID_GROUP_MESSAGE);
    $known = collect_known_groups($users, $track_map, $new_name);
    [$new_groups, $error] = validate_user_group_selection($users, $known, $_POST['ug'] ?? []);
    if ($error !== '') return reject_change('users', $error);
    $error = save_user_groups($users_file, $new_groups);
    if ($error !== '') return reject_change('users', $error, 500);
    audit_log('admin_groups_saved', ['scope' => 'users', 'changes' => describe_user_group_changes($users, $new_groups)]);
    return outcome('Användargrupper sparade.');
}

function handle_save_tracks(string $tracks_file, array $music_files, array $users, array $track_map): array {
    $known = collect_known_groups($users, $track_map);
    [$assignments, $error] = validate_track_assignments($_POST['tg'] ?? [], $music_files, $known);
    if ($error !== '') return reject_change('tracks', $error);
    $changes = describe_track_group_changes($assignments, $track_map);
    $error   = save_track_groups($tracks_file, $assignments, $track_map);
    if ($error !== '') return reject_change('tracks', $error, 500);
    audit_log('admin_groups_saved', ['scope' => 'tracks', 'changes' => $changes]);
    return outcome('Låtgrupper sparade.');
}

// ── Begäran ───────────────────────────────────────────────────────────────────
$tab     = ($_GET['tab'] ?? 'users') === 'tracks' ? 'tracks' : 'users';
$outcome = outcome('');
$typed_group_name = '';   // visas kvar i rutan "Ny grupp" tills den sparats

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    csrf_require();
    $users_before = read_admin_users($users_file);
    $track_map    = load_track_groups();
    if (isset($_POST['save_users'])) {
        $tab     = 'users';
        $outcome = handle_save_users($users_file, $track_map);
    } elseif (isset($_POST['save_tracks'])) {
        $tab     = 'tracks';
        $outcome = handle_save_tracks($tracks_file, list_music_files($music_dir), $users_before, $track_map);
    } elseif (isset($_POST['add_group'])) {
        $tab     = 'users';
        $outcome = handle_add_group();
    } else {
        $outcome = reject_change('unknown', 'Okänd åtgärd.');
    }
    http_response_code($outcome['status']);
    $is_saved_ok = $outcome['status'] === 200 && isset($_POST['save_users']);
    $typed_group_name = $is_saved_ok ? '' : posted_new_group_name();
}

// ── Data till vyn (läses efter eventuell sparning) ────────────────────────────
$all_users = read_admin_users($users_file);
$track_map = load_track_groups();
$pending_group = is_valid_group_name($typed_group_name) ? $typed_group_name : '';
$groups        = collect_known_groups($all_users, $track_map, $pending_group);
$track_groups_without_all = array_values(array_diff($groups, [ALL_USERS_GROUP]));
$tracks        = list_music_files($music_dir);
$flash         = $outcome['message'];
$flash_is_error = $outcome['status'] >= 400;
?><!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Grupper — <?= escape_html($site_title) ?></title>
<link rel="icon" href="../favicon.ico">
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
.logout-form { display:inline; margin:0; }
.logout-form button { background:none; border:none; padding:0; color:var(--accent); font:inherit; cursor:pointer; }

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
  <h1>&#128101; Grupper — <?= escape_html($site_title) ?></h1>
  <div class="header-links">
    <a href="index.php">← Dashboard</a>
    <a href="../index.php">Spelaren</a>
    <?= logout_button('../logout.php') ?>
  </div>
</div>

<?php if ($flash !== ''): ?>
<div class="flash <?= $flash_is_error ? 'err' : '' ?>"><?= escape_html($flash) ?></div>
<?php endif ?>

<div class="tabs">
  <a class="tab <?= $tab === 'users'  ? 'active' : '' ?>" href="?tab=users">Användare</a>
  <a class="tab <?= $tab === 'tracks' ? 'active' : '' ?>" href="?tab=tracks">Låtar</a>
</div>

<div class="content">

<?php if ($tab === 'users'): ?>
<!-- ── Användar-grupptillhörighet ──────────────────────────────────────────── -->
<form method="post" action="?tab=users">
  <?= csrf_field() ?>

  <div class="new-group-row">
    <input type="text" name="new_group_name" placeholder="Ny grupp…"
           value="<?= escape_html($typed_group_name) ?>" maxlength="40">
    <button type="submit" name="add_group" class="btn-add">+ Lägg till grupp</button>
  </div>

  <table>
    <thead>
      <tr>
        <th>Användare</th>
        <?php foreach ($groups as $group): ?>
        <th><?= escape_html($group) ?></th>
        <?php endforeach ?>
      </tr>
    </thead>
    <tbody>
    <?php foreach ($all_users as $username => $user_data): ?>
      <tr>
        <td>
          <strong><?= escape_html($user_data['display']) ?></strong><br>
          <span style="color:var(--muted);font-size:0.78rem"><?= escape_html((string)$username) ?></span>
        </td>
        <?php foreach ($groups as $group): ?>
        <td>
          <label class="cb-label">
            <input type="checkbox" name="ug[<?= escape_html((string)$username) ?>][<?= escape_html($group) ?>]"
              value="1" <?= in_array($group, $user_data['groups'], true) ? 'checked' : '' ?>>
            <?= escape_html($group) ?>
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
  <?= csrf_field() ?>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Låt</th>
        <th>Grupp</th>
      </tr>
    </thead>
    <tbody>
    <?php foreach ($tracks as $index => $filename): ?>
      <?php $assigned = track_group($filename, $track_map); ?>
      <tr>
        <td class="track-num"><?= $index + 1 ?></td>
        <td class="track-name"><?= escape_html(preg_replace('/\.(mp3|m4a)$/i', '', str_replace(['_', '-'], ' ', $filename))) ?></td>
        <td>
          <div class="radio-wrap">
            <label class="rb-label">
              <input type="radio" name="tg[<?= escape_html($filename) ?>]"
                value="" <?= $assigned === '' ? 'checked' : '' ?>>
              Alla
            </label>
            <?php foreach ($track_groups_without_all as $group): ?>
            <label class="rb-label">
              <input type="radio" name="tg[<?= escape_html($filename) ?>]"
                value="<?= escape_html($group) ?>" <?= $assigned === $group ? 'checked' : '' ?>>
              <?= escape_html($group) ?>
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
