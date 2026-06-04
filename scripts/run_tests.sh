#!/usr/bin/env bash
# run_tests.sh — Skapar en fresh testdatabas, installerar modulen, kör tester.
# Credentials läses från odoo.conf i containern — inga lösenord i skriptet.
#
# Användning:
#   ./scripts/run_tests.sh clio_event_log            # testar en modul
#   ./scripts/run_tests.sh clio_event_log,clio_job   # testar flera
#   ./scripts/run_tests.sh clio_aiab                 # testar hela AIAB-stacken
#
# Obs: Skapar och droppar databasen clio_smoke_test automatiskt.

set -e

CONTAINER="odoo19-odoo-1"
PGCONTAINER="odoo19-db-1"
TEST_DB="clio_smoke_test"
MODULES="${1:-clio_aiab}"

echo "═══════════════════════════════════════════════"
echo "  Odoo 19 Smoketester"
echo "  Testdatabas : $TEST_DB"
echo "  Moduler     : $MODULES"
echo "═══════════════════════════════════════════════"

# 1. Skapa tom databas
echo ""
echo "→ Skapar testdatabas $TEST_DB..."
docker exec "$PGCONTAINER" psql -U odoo -c "DROP DATABASE IF EXISTS $TEST_DB;" postgres
docker exec "$PGCONTAINER" psql -U odoo -c "CREATE DATABASE $TEST_DB;" postgres

# 2. Initiera Odoo-schema
echo "→ Installerar Odoo bas + moduler ($MODULES)..."
docker exec "$CONTAINER" odoo \
    --http-port=8950 \
    --test-enable \
    --test-tags post_install \
    --stop-after-init \
    -i "$MODULES" \
    -d "$TEST_DB" \
    2>&1 | grep -E "(ERROR|CRITICAL|Starting Test|Ran [0-9]+|FAIL|stats:|post-tests)" || true

echo ""
echo "→ Droppar testdatabas..."
docker exec "$PGCONTAINER" psql -U odoo -c "DROP DATABASE IF EXISTS $TEST_DB;" postgres

echo ""
echo "Klart."
