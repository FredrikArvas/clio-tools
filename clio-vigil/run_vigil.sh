#!/bin/bash
# run_vigil.sh — Kör vigil-pipelinen i loop tills kön är tom.
# Timern (OnUnitInactiveSec=30min) startar om efter 30 min när detta skript exiterar.

VENV=/home/clioadmin/19.0/clio-tools/.venv/bin/python
DB=/home/clioadmin/19.0/clio-tools/clio-vigil/data/vigil.db
cd /home/clioadmin/19.0/clio-tools/clio-vigil

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

while true; do
    # Pass 1: summera och indexera befintlig transkriberad backlog
    log "=== Pass 1: summera/indexera backlog ==="
    $VENV main.py --summarize --index --classify-uap --domain ufo --max 50

    # Pass 2: samla in och ladda ned ljud
    log "=== Pass 2: collect + download ==="
    $VENV main.py --run --download --domain ufo --max 10

    # Pass 3: transkribera (GPU whisper), summera, indexera och klassificera
    log "=== Pass 3: transcribe + summarize + index ==="
    $VENV main.py --transcribe --summarize --index --classify-uap --domain ufo --max 10

    # Kolla kön
    QUEUED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM vigil_items WHERE state='queued';" 2>/dev/null || echo 0)
    log "Kö efter körning: $QUEUED st"

    if [ "$QUEUED" -eq 0 ]; then
        log "Kön är tom — avslutar. Timern startar om om 30 min."
        break
    fi

    log "$QUEUED kvar i kö — kör direkt igen utan paus."
done