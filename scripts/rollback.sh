#!/usr/bin/env bash
# Roll back to a previous git revision and rebuild. Usage:
#   ./scripts/rollback.sh <git-revision>
# Example: ./scripts/rollback.sh HEAD~1
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REV="${1:?Usage: rollback.sh <git-revision> (e.g. HEAD~1 or a commit SHA)}"

if [[ ! -f .env ]]; then
  echo "Missing .env" >&2
  exit 1
fi

echo "==> Pre-rollback backup"
bash "$REPO_ROOT/scripts/backup_db.sh"

echo "==> Checking out $REV"
git checkout "$REV"

echo "==> Rebuild and restart"
docker compose up -d --build

echo "==> Health check"
bash "$REPO_ROOT/scripts/healthcheck.sh"

echo "Rollback complete. You are in detached HEAD or an older commit — create a branch or return to main when ready."
