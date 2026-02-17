#!/usr/bin/env bash
set -euo pipefail

SRC="/home/deploy/loteriatv/pwa/"
DST="/home/user/web/ssganador.lat/public_html/"

sudo rsync -av --delete "$SRC" "$DST"
sudo chown -R user:user "$DST"

echo "✅ PWA desplegada en $DST"
