#!/bin/sh
set -eu

python - <<'PY'
import os
import socket
import time
from urllib.parse import urlparse


def wait_for(url_env: str, default_port: int, label: str) -> None:
    raw = os.environ.get(url_env, "").strip()
    if not raw:
        return
    parsed = urlparse(raw)
    host = parsed.hostname
    port = parsed.port or default_port
    if not host:
        return
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"{label} ready at {host}:{port}")
                return
        except OSError:
            time.sleep(1)
    raise SystemExit(f"Timeout waiting for {label} at {host}:{port}")


wait_for("DATABASE_URL", 5432, "database")
wait_for("REDIS_URL", 6379, "redis")
PY

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  /usr/local/bin/python manage.py migrate --noinput
fi

if [ "${COLLECTSTATIC:-0}" = "1" ]; then
  /usr/local/bin/python manage.py collectstatic --noinput
fi

if [ -d /opt/media-seed ] && [ -d /app/media ] && [ -z "$(find /app/media -mindepth 1 -print -quit 2>/dev/null)" ]; then
  cp -R /opt/media-seed/. /app/media/
  echo "seeded media volume from image bundle"
fi

if [ "${WARM_SCRAPERS_ON_BOOT:-0}" = "1" ]; then
  if ! /usr/local/bin/python manage.py warm_scraper_data --max-age-minutes "${SCRAPER_BOOTSTRAP_MAX_AGE_MINUTES:-90}"; then
    echo "warm_scraper_data failed; continuing startup"
  fi
fi

exec "$@"
