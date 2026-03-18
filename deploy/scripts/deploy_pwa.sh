#!/usr/bin/env bash
set -euo pipefail

WEBROOT="/home/user/web/ssganador.lat/public_html"
APP_VERSION="$(git rev-parse --short=12 HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)"

rsync -av --delete ./pwa/ "$WEBROOT/"

sed -i "s/__APP_VERSION__/$APP_VERSION/g" "$WEBROOT/index.html"
sed -i "s/__APP_VERSION__/$APP_VERSION/g" "$WEBROOT/config.js"
sed -i "s/__APP_VERSION__/$APP_VERSION/g" "$WEBROOT/service-worker.js"

chown -R user:user "$WEBROOT"

# sanity checks (para no romper prod)
grep -q "api.ssganador.lat" "$WEBROOT/config.js"
! grep -q "__APP_VERSION__" "$WEBROOT/index.html"
! grep -q "__APP_VERSION__" "$WEBROOT/config.js"
! grep -q "__APP_VERSION__" "$WEBROOT/service-worker.js"
echo "PWA deployed OK"
