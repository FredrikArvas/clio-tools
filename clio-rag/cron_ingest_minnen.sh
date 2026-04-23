#!/bin/bash
# cron_ingest_minnen.sh — indexerar alla *minnet-mappar
# Körs varje timme via cron: 0 * * * * /home/clioadmin/clio-tools/clio-rag/cron_ingest_minnen.sh

PYTHON=/home/clioadmin/clio-tools/venv/bin/python3
SCRIPT=/home/clioadmin/clio-tools/clio-rag/ingest_minne.py
LOG=/home/clioadmin/clio-tools/clio-rag/cron_ingest.log

cd /home/clioadmin/clio-tools/clio-rag

declare -A MINNEN=(
  [mem_ssf]="$HOME/Dropbox/projekt/Capgemini/Skidförbundet/ssfminnet"
  [mem_aiab]="$HOME/Dropbox/ftg/AIAB/aiabminnet"
  [mem_gsf]="$HOME/Dropbox/ftg/GSF/gsfminnet"
)

echo "[$(date '+%Y-%m-%d %H:%M')] Cron-ingest startar" >> "$LOG"

for COLLECTION in "${!MINNEN[@]}"; do
  SOURCE="${MINNEN[$COLLECTION]}"
  if [ -d "$SOURCE" ]; then
    COUNT=$(find "$SOURCE" -type f \( -name '*.pdf' -o -name '*.docx' -o -name '*.pptx' -o -name '*.txt' \) | wc -l)
    if [ "$COUNT" -gt 0 ]; then
      echo "  $COLLECTION: $COUNT filer" >> "$LOG"
      "$PYTHON" "$SCRIPT" --source "$SOURCE" --collection "$COLLECTION" >> "$LOG" 2>&1
    fi
  fi
done

echo "[$(date '+%Y-%m-%d %H:%M')] Klar" >> "$LOG"
