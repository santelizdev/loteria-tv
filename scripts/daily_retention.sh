#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f "$ROOT_DIR/manage.py" ]]; then
  echo "manage.py not found under $ROOT_DIR" >&2
  exit 69
fi

if [[ ! -f "$ROOT_DIR/venv/bin/activate" ]]; then
  echo "virtualenv not found under $ROOT_DIR/venv" >&2
  exit 69
fi

source "$ROOT_DIR/venv/bin/activate"

python manage.py run_daily_retention "$@"
