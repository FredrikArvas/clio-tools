<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>

/**
 * api/load_profiles.php — användarens sparade inställningar som JSON-objekt.
 *
 * Anropas av: player.js vid start. Gäster och användare utan profil får ett tomt svar.
 * Äldre profiler med okända nycklar läses som de är (vitlistan gäller bara vid sparning).
 * En trasig profilfil loggas (json_file_read) och ger tomt svar utan att visa sökvägar för klienten.
 */
require_once __DIR__ . '/_bootstrap.php';
require_once dirname(__DIR__) . '/json_store.php';

['user' => $user] = api_bootstrap(['method' => 'GET', 'allow_guest' => true]);
if (is_guest($user)) api_respond([]);

api_respond(json_file_read(dirname(__DIR__) . '/data/profiles/' . basename($user['username']) . '.json'));
