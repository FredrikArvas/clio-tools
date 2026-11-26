#!/bin/bash
# Installerar clio-uap-harvest service och timer till systemd.
# Körs som root eller med sudo på EliteDeskGPU.

set -euo pipefail

SYSTEMD=/etc/systemd/system
DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$DIR/clio-uap-harvest.service" "$SYSTEMD/"
cp "$DIR/clio-uap-harvest.timer"   "$SYSTEMD/"

systemctl daemon-reload
systemctl enable --now clio-uap-harvest.timer

echo "Installerat. Status:"
systemctl status clio-uap-harvest.timer --no-pager
