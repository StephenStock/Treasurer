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

current_branch="$(git rev-parse --abbrev-ref HEAD)"
current_commit="$(git rev-parse --short HEAD)"
echo "Current checkout: ${current_branch}@${current_commit}"

echo "Pulling latest code..."
git pull --ff-only

new_commit="$(git rev-parse --short HEAD)"
if [[ "$new_commit" != "$current_commit" ]]; then
  echo "Updated checkout: ${current_branch}@${new_commit}"
else
  echo "Checkout unchanged: ${current_branch}@${new_commit}"
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

echo "Installing Python dependencies..."
PIP_LOG="$(mktemp)"
if ! "$PIP_BIN" install -q --disable-pip-version-check -r requirements.txt >"$PIP_LOG" 2>&1; then
  echo "Dependency installation failed."
  cat "$PIP_LOG"
  rm -f "$PIP_LOG"
  exit 1
fi
rm -f "$PIP_LOG"

if [[ -f /etc/treasurer/treasurer.env ]]; then
  # shellcheck disable=SC1091
  set -a
  source /etc/treasurer/treasurer.env
  set +a
fi

if [[ -z "${TREASURER_DATABASE_URL:-}" ]]; then
  echo "TREASURER_DATABASE_URL is not set." >&2
  exit 1
fi

export TREASURER_DATABASE_URL

echo "Checking database schema..."
if "$PYTHON_BIN" -c "import os, sys, psycopg; conn = psycopg.connect(os.environ['TREASURER_DATABASE_URL']); exists = conn.execute(\"SELECT to_regclass('public.users')\").fetchone()[0]; sys.exit(0 if exists else 1)"; then
  echo "Database schema already exists, skipping init-db."
else
  echo "Initializing database schema..."
  "$PYTHON_BIN" -m flask --app app init-db
fi

echo "Restarting service..."
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl --no-pager --full status "$SERVICE_NAME"
