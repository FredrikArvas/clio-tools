<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * json_store.php — läs-ändra-skriv av en JSON-fil under exklusivt lås.
 *
 * Anropas av: login_throttle.php (försöksräknare), rate_limit.php (hastighetsgränser),
 * api/save_profile.php och api/save_playlist.php (användarens profil/spellistor).
 *
 * Säkerhetsantaganden:
 * - Allt sker medan filen är låst med flock(LOCK_EX). Utan låset kan två parallella anrop läsa
 *   samma värde och den ena ändringen går förlorad (t.ex. två misslyckade inloggningar som
 *   räknas som en).
 * - Filen skrivs om på plats (truncate + write), aldrig via rename, eftersom låset hör till
 *   inoden. En läsare utan lås (load_*.php) kan därför i teorin se en halvskriven fil; det är
 *   en medveten avvägning mot att behöva låsa varje läsning. load_*.php loggar och svarar tomt.
 * - Vägen till filen bestäms alltid av anroparen, aldrig av användarinmatning.
 */

/**
 * Anropar $mutator(array $data): ?array med filens nuvarande innehåll och skriver tillbaka det
 * den returnerar (null = skriv ingenting). Returnerar false om något gick fel (loggas).
 *
 * $on_invalid styr vad som händer när filen har innehåll som inte är en JSON-array/objekt:
 * 'reset' = börja om från [] (räknare), 'abort' = skriv inget och returnera false, så att en
 * trasig användarfil inte skrivs över utan att någon tittat på den.
 */
function json_file_update(string $path, callable $mutator, string $on_invalid = 'reset', int $json_flags = 0): bool {
    $handle = fopen($path, 'c+');
    if ($handle === false || !flock($handle, LOCK_EX)) {
        error_log('clio_music: kunde inte låsa ' . basename($path));
        if ($handle) fclose($handle);
        return false;
    }
    try {
        return json_file_update_locked($handle, $path, $mutator, $on_invalid, $json_flags);
    } finally {
        flock($handle, LOCK_UN);
        fclose($handle);
    }
}

/** Själva läs-ändra-skriv-steget; filen är redan öppen och låst. */
function json_file_update_locked($handle, string $path, callable $mutator, string $on_invalid, int $json_flags): bool {
    $raw  = (string)stream_get_contents($handle);
    $data = trim($raw) === '' ? [] : json_decode($raw, true);
    if (!is_array($data)) {
        if ($on_invalid === 'abort') {
            error_log('clio_music: ' . basename($path) . ' innehåller ogiltig JSON och skrivs inte över');
            return false;
        }
        $data = [];
    }
    $updated = $mutator($data);
    if ($updated === null) return true;
    $json = json_encode($updated, $json_flags);
    if ($json === false) {
        error_log('clio_music: kunde inte koda JSON för ' . basename($path));
        return false;
    }
    ftruncate($handle, 0);
    rewind($handle);
    if (fwrite($handle, $json) !== strlen($json)) {
        error_log('clio_music: kunde inte skriva ' . basename($path));
        return false;
    }
    return true;
}

/**
 * Läser en JSON-fil utan lås. Saknad fil ger []; trasig fil loggas (utan att sökvägen når
 * klienten) och ger []. Okända nycklar behålls: äldre sparade filer ska alltid gå att läsa.
 */
function json_file_read(string $path): array {
    if (!is_file($path)) return [];
    $raw = file_get_contents($path);
    if ($raw === false) {
        error_log('clio_music: kunde inte läsa ' . basename($path));
        return [];
    }
    if (trim($raw) === '') return [];
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        error_log('clio_music: ' . basename($path) . ' innehåller ogiltig JSON');
        return [];
    }
    return $data;
}
