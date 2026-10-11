<?php
/**
 * rate_limit.php — enkel hastighetsgräns (fast tidsfönster) utan databas.
 *
 * Anropas av: api/log_play.php. Byggd på json_store.php (flock-skyddat läs-ändra-skriv), samma
 * mekanism som login_throttle.php.
 *
 * Användning:
 *   $retry_after = rate_limit_hit('log_play_guest', client_ip(), 10, 60);
 *   if ($retry_after > 0) { header('Retry-After: ' . $retry_after); api_error(429, 'too many requests'); }
 *
 * Säkerhetsantaganden:
 * - Nyckeln (t.ex. IP) hashas till filnamn, så inmatning når aldrig filsystemet som sökväg.
 * - Anropet räknas även om efterföljande validering avvisar begäran: den som spammar felaktiga
 *   anrop ska också stoppas.
 * - Går räknaren inte att skriva (disk, rättigheter) loggas felet och begäran släpps igenom
 *   ("fail open"): en trasig räknare ska inte stänga ute alla lyssnare.
 */

require_once __DIR__ . '/json_store.php';

// Kan förinställas (define före require) av tester, så att de inte rör data/.
if (!defined('RATE_LIMIT_DIR')) define('RATE_LIMIT_DIR', __DIR__ . '/data/rate_limits');
const RATE_LIMIT_STALE_SECONDS = 86400;   // räknarfiler äldre än så städas bort

/** Sekunder att vänta innan nästa försök; 0 = tillåtet (och räknat). */
function rate_limit_hit(string $bucket, string $key, int $max_hits, int $window_seconds): int {
    if (!is_dir(RATE_LIMIT_DIR) && !mkdir(RATE_LIMIT_DIR, 0770, true) && !is_dir(RATE_LIMIT_DIR)) {
        error_log('clio_music: kan inte skapa ' . RATE_LIMIT_DIR . ' — hastighetsgränsen fungerar inte');
        return 0;
    }
    if (random_int(1, 100) === 1) rate_limit_purge_stale();
    $retry_after = 0;
    $now         = time();
    $is_saved = json_file_update(
        rate_limit_file($bucket, $key),
        function (array $state) use ($now, $max_hits, $window_seconds, &$retry_after): array {
            $window_start = (int)($state['window_start'] ?? 0);
            $hits         = (int)($state['hits'] ?? 0);
            if ($now - $window_start >= $window_seconds) [$window_start, $hits] = [$now, 0];
            $hits++;
            if ($hits > $max_hits) $retry_after = max(1, $window_start + $window_seconds - $now);
            return ['window_start' => $window_start, 'hits' => $hits];
        }
    );
    return $is_saved ? $retry_after : 0;
}

function rate_limit_file(string $bucket, string $key): string {
    return RATE_LIMIT_DIR . '/' . hash('sha256', $bucket . ':' . $key) . '.json';
}

/** Tar bort gamla räknarfiler så katalogen inte växer för alltid. */
function rate_limit_purge_stale(): void {
    foreach (glob(RATE_LIMIT_DIR . '/*.json') ?: [] as $path) {
        if (time() - (int)filemtime($path) > RATE_LIMIT_STALE_SECONDS && !unlink($path)) {
            error_log('clio_music: kunde inte städa ' . basename($path));
        }
    }
}
