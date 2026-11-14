#!/bin/bash
# uap_nightly.sh — Nattlig UAP pipeline
# Kör: import → cluster → series
# Schema: 02:30 varje natt (se crontab)
# Loggar till: ~/logs/clio-uap/

set -euo pipefail

LOG_DIR="$HOME/logs/clio-uap"
LOG_FILE="$LOG_DIR/nightly_$(date +%Y%m%d_%H%M%S).log"
SCRIPT_DIR="$HOME/clio-tools/clio-uap"
LATEST="$LOG_DIR/latest.log"

mkdir -p "$LOG_DIR"

echo "======================================" | tee "$LOG_FILE"
echo "UAP Nightly Pipeline — $(date)"       | tee -a "$LOG_FILE"
echo "======================================" | tee -a "$LOG_FILE"

# Stage 1a: vigil auto_import (befintlig pipeline)
echo "" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Stage 1a: vigil auto_import" | tee -a "$LOG_FILE"
cd "$HOME/clio-tools/clio-vigil"
python3 auto_import.py 2>&1 | tee -a "$LOG_FILE" || echo "VARNING: auto_import avslutade med fel" | tee -a "$LOG_FILE"

# Stage 1b: NUFORC import
echo "" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Stage 1b: NUFORC import" | tee -a "$LOG_FILE"
cd "$SCRIPT_DIR"
python3 uap_import_nuforc.py 2>&1 | tee -a "$LOG_FILE" || echo "VARNING: nuforc import avslutade med fel" | tee -a "$LOG_FILE"

# Stage 2+3: cluster + series
echo "" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Stage 2+3: cluster + series detection" | tee -a "$LOG_FILE"
cd "$SCRIPT_DIR"
python3 uap_pipeline.py --stage all 2>&1 | tee -a "$LOG_FILE" || echo "VARNING: pipeline avslutade med fel" | tee -a "$LOG_FILE"

# Stage 1c: GEIPAN import (nya D/D1/D2-fall sedan sist)
echo "" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Stage 1c: GEIPAN import" | tee -a "$LOG_FILE"
cd "$SCRIPT_DIR"
python3 uap_import_geipan.py --pages 10 --delay 1.5 2>&1 | tee -a "$LOG_FILE" || echo "VARNING: geipan import avslutade med fel" | tee -a "$LOG_FILE"

# Stage 4: Wikipedia web enrichment (körs bara om inte redan igång)
echo "" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Stage 4: Wikipedia web enrichment" | tee -a "$LOG_FILE"
if pgrep -f "uap_web_enrich.py" > /dev/null; then
    echo "  Enrichment kör redan i bakgrunden — hoppar över." | tee -a "$LOG_FILE"
else
    python3 uap_web_enrich.py --max 200 --delay 1.0 2>&1 | tee -a "$LOG_FILE" \
        || echo "VARNING: web enrichment avslutade med fel" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "[$(date +%H:%M:%S)] Klar." | tee -a "$LOG_FILE"

# Håll bara 14 dagars loggar
find "$LOG_DIR" -name "nightly_*.log" -mtime +14 -delete

# Uppdatera latest.log symlink
ln -sf "$LOG_FILE" "$LATEST"
