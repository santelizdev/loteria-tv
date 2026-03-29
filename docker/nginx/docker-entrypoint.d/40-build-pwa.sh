#!/bin/sh
set -eu

APP_VERSION="${PWA_APP_VERSION:-$(date -u +%Y%m%d%H%M%S)}"
TARGET_DIR="/usr/share/nginx/html"

rm -rf "${TARGET_DIR:?}/"*
mkdir -p "$TARGET_DIR"
cp -R /opt/pwa-src/. "$TARGET_DIR/"

find "$TARGET_DIR" -type f \( -name '*.html' -o -name '*.js' -o -name '*.json' -o -name '*.css' \) \
  -exec sed -i "s|__APP_VERSION__|$APP_VERSION|g" {} +
