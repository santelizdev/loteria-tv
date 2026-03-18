#!/usr/bin/env bash
set -euo pipefail

SRC="/home/deploy/loteriatv/pwa/"
DST="/home/user/web/ssganador.lat/public_html/"
APP_VERSION="$(git -C /home/deploy/loteriatv rev-parse --short=12 HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)"

sudo rsync -av --delete "$SRC" "$DST"
sudo sed -i "s/__APP_VERSION__/$APP_VERSION/g" "${DST}index.html"
sudo sed -i "s/__APP_VERSION__/$APP_VERSION/g" "${DST}config.js"
sudo sed -i "s/__APP_VERSION__/$APP_VERSION/g" "${DST}service-worker.js"
sudo chown -R user:user "$DST"

sudo grep -q "api.ssganador.lat" "${DST}config.js"
! sudo grep -q "__APP_VERSION__" "${DST}index.html"
! sudo grep -q "__APP_VERSION__" "${DST}config.js"
! sudo grep -q "__APP_VERSION__" "${DST}service-worker.js"

echo "✅ PWA desplegada en $DST"
