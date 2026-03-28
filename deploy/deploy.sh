#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$SCRIPT_DIR/..}"
SERVICE_NAME="${SERVICE_NAME:-treasurer}"
PYTHON_BIN="${PYTHON_BIN:-$APP_DIR/.venv/bin/python}"
PIP_BIN="${PIP_BIN:-$APP_DIR/.venv/bin/pip}"

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "Expected a git checkout at: $APP_DIR" >&2
  exit 1
fi

cd "$APP_DIR"

echo "Pulling latest code..."
git pull --ff-only

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

echo "Installing Python dependencies..."
"$PIP_BIN" install -r requirements.txt

if [[ -f /etc/treasurer/treasurer.env ]]; then
  # shellcheck disable=SC1091
  source /etc/treasurer/treasurer.env
fi

if [[ -n "${TREASURER_DATABASE_URL:-}" ]]; then
  echo "Refreshing database schema..."
  "$PYTHON_BIN" -m flask --app app init-db
fi

echo "Restarting service..."
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl --no-pager --full status "$SERVICE_NAME"
