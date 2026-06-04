#!/usr/bin/env bash
# run_tests.sh — Kör Odoo-enhetstester inuti Odoo 19-containern
# Användning:
#   ./scripts/run_tests.sh                      # alla moduler
#   ./scripts/run_tests.sh clio_cockpit         # en modul
#   ./scripts/run_tests.sh clio_cockpit,clio_job  # flera moduler

set -e

CONTAINER="odoo19-odoo-1"
DB="aiab19_migrated"
MODULES="${1:-$(ls /home/clioadmin/19.0/clio-tools/odoo-addons/ | grep -v CLAUDE | tr n ,)}"

echo "═══════════════════════════════════════════════"
echo "  Odoo Enhetstester"
echo "  Databas : $DB"
echo "  Moduler : $MODULES"
echo "═══════════════════════════════════════════════"

docker exec "$CONTAINER" odoo \
    --db_host=db \
    --db_user=odoo \
    --db_password=odoo \
    --test-enable \
    --stop-after-init \
    -u "$MODULES" \
    -d "$DB" \
    2>&1 | grep -E "^(ERROR|WARNING|INFO|CRITICAL|Ran|OK|FAIL|ERROR:)" || true

echo ""
echo "Klart. Kontrollera logg ovan för FAIL/ERROR."
