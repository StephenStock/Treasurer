#!/usr/bin/env bash
# Restore /data in the app container from a tar produced by backup_db.sh.
# Usage: ./scripts/restore_db.sh path/to/treasurer-db-*.tar
# Stops the app briefly while restoring (Caddy can keep running).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ARCHIVE="${1:?Usage: restore_db.sh <backup.tar>}"

if [[ ! -f "$ARCHIVE" ]]; then
  echo "File not found: $ARCHIVE" >&2
  exit 1
fi

if command -v realpath >/dev/null 2>&1; then
  ARCHIVE_PATH="$(realpath "$ARCHIVE")"
else
  ARCHIVE_PATH="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"
fi

echo "==> Pre-restore backup"
bash "$REPO_ROOT/scripts/backup_db.sh"

echo "==> Stopping app container"
docker compose stop app

echo "==> Restoring into volume via temporary container"
docker compose run --rm -v "${ARCHIVE_PATH}:/restore.tar:ro" app \
  sh -c 'rm -f /data/*.db /data/*.db-journal /data/*.db-wal /data/*.db-shm 2>/dev/null; tar -xf /restore.tar -C /data'

echo "==> Starting app"
docker compose start app

echo "==> Health check"
sleep 2
bash "$REPO_ROOT/scripts/healthcheck.sh"

echo "Restore complete."
