<?php
$music_dir   = __DIR__ . '/music';
$music_url   = 'music';
$site_title  = 'Clio Music';
define('APP_VERSION', '1.5.2');
$lyrics_url = 'lyrics';
define('GUEST_GROUP',  'Gäst');

// Tillåtna gruppnamn (admin/groups_store.php). Vitlista, inte svartlista: bara bokstaver, siffror,
// mellanslag, understreck och bindestreck. Därmed kan varken CSV-avgränsare (; |), radbrytningar
// eller citattecken nå data/users.csv eller data/track_groups.csv.
// D-flaggan behövs: utan den släpper "$" igenom ett avslutande radbrytningstecken.
const GROUP_NAME_PATTERN = '/^[\p{L}\p{N} _\-]{1,40}$/uD';
