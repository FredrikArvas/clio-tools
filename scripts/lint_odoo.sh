#!/usr/bin/env bash
# lint_odoo.sh — Kör pylint-odoo inuti Odoo 19-containern
# Användning: ./scripts/lint_odoo.sh [modul_eller_fil...]
# Utan argument: kontrollerar alla moduler i odoo-addons/

set -e

CONTAINER="odoo19-odoo-1"
ADDONS_PATH="/mnt/addons/arvas"

if [ $# -eq 0 ]; then
    echo "→ Kör pylint-odoo på alla moduler..."
    docker exec "$CONTAINER" python3 -m pylint \
        --load-plugins=pylint_odoo \
        --disable=all \
        --enable=odoolint \
        --odoo-addons-paths="$ADDONS_PATH" \
        "$ADDONS_PATH"
else
    echo "→ Kör pylint-odoo på: $*"
    docker exec "$CONTAINER" python3 -m pylint \
        --load-plugins=pylint_odoo \
        --disable=all \
        --enable=odoolint \
        --odoo-addons-paths="$ADDONS_PATH" \
        "$@"
fi
