#!/usr/bin/env bash
set -euo pipefail

WEBROOT="/home/user/web/ssganador.lat/public_html"

rsync -av --delete ./pwa/ "$WEBROOT/"
chown -R user:user "$WEBROOT"

# sanity checks (para no romper prod)
grep -q "api.ssganador.lat" "$WEBROOT/config.js"
echo "PWA deployed OK"
