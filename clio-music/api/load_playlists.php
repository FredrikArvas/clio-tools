<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * api/load_playlists.php — användarens spellistor som JSON-objekt {namn: [spår-URL, ...]}.
 *
 * Anropas av: player.js vid start. Gäster och användare utan spellistor får ett tomt svar.
 * Sparade listor returneras som de är; spår som inte längre finns hoppas över av klienten.
 * En trasig fil loggas (json_file_read) och ger tomt svar utan att visa sökvägar för klienten.
 */
require_once __DIR__ . '/_bootstrap.php';
require_once dirname(__DIR__) . '/json_store.php';

['user' => $user] = api_bootstrap(['method' => 'GET', 'allow_guest' => true]);
if (is_guest($user)) api_respond([]);

api_respond(json_file_read(dirname(__DIR__) . '/data/playlists/' . basename($user['username']) . '.json'));
