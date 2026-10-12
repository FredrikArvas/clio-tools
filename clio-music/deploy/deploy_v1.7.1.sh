#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Arvas International AB <fredrik@arvas.se>
#
# Deploy clio_music v1.7.1 — AGPL-licens, SPDX-huvuden, footer, städad README
#
# Körs på servern från ~/staging/clio_music_v1.7.1/:
#   bash ~/staging/clio_music_v1.7.1/deploy.sh
#
# Rollback: bash ~/staging/clio_music_v1.7.1/rollback.sh

set -euo pipefail

SPRINT="v1.7.1"
WEBROOT="/var/www/clio_music"
BACKUP="$HOME/backups/clio_music.bak_$(date +%Y%m%d)_${SPRINT}"
STAGING="$HOME/staging/clio_music_${SPRINT}"

if [ -d "$BACKUP" ]; then
  echo "AVBRYTER: backup $BACKUP finns redan." >&2
  exit 1
fi

echo "==> Backup → $BACKUP"
sudo cp -a "$WEBROOT" "$BACKUP"

echo "==> Validerar PHP"
find "$STAGING" -name "*.php" | while read f; do
  php -l "$f" > /dev/null || { echo "PHP-fel: $f" >&2; exit 1; }
done

echo "==> Kopierar filer"
sudo cp "$STAGING/LICENSE"       "$WEBROOT/"
sudo cp "$STAGING"/*.php         "$WEBROOT/"
sudo cp "$STAGING"/*.js          "$WEBROOT/"
sudo cp "$STAGING"/*.css         "$WEBROOT/"
sudo cp "$STAGING/admin"/*.php   "$WEBROOT/admin/"
sudo cp "$STAGING/api"/*.php     "$WEBROOT/api/"
sudo cp "$STAGING/tests"/*       "$WEBROOT/tests/"

echo "==> Startar om nginx"
sudo systemctl restart nginx

echo "==> Säkerhetsrök"
bash "$WEBROOT/tests/security_smoke.sh"

echo "==> Deploy $SPRINT klar."
