#!/usr/bin/env bash
# Deploy Lodge Office from a git checkout on the server (see docs/Runbook-Hetzner.md).
#
# Usage (from anywhere):
#   bash /opt/treasurer/scripts/deploy.sh
# Or after: cd /opt/treasurer
#   bash scripts/deploy.sh
#
# Optional environment:
#   DEPLOY_SKIP_BACKUP=1   — skip the pre-deploy DB backup (not recommended)
#   DEPLOY_NO_CACHE=1      — rebuild the app image with --no-cache (slower; use if you suspect a stale image)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example to .env and set SECRET_KEY and SITE_ADDRESS." >&2
  exit 1
fi

# Shell scripts often pick up harmless drift (chmod +x, CRLF). Reset them to HEAD before pull.
echo "==> Resetting scripts/*.sh to match last commit (avoids blocked git pull)"
git restore \
  scripts/backup_db.sh \
  scripts/deploy.sh \
  scripts/healthcheck.sh \
  scripts/restore_db.sh \
  scripts/rollback.sh \
  2>/dev/null || git checkout HEAD -- \
  scripts/backup_db.sh \
  scripts/deploy.sh \
  scripts/healthcheck.sh \
  scripts/restore_db.sh \
  scripts/rollback.sh \
  2>/dev/null || true

if ! git diff-index --quiet HEAD -- 2>/dev/null; then
  echo "Deploy aborted: this folder has uncommitted changes to tracked files." >&2
  echo "Fix or discard them first, then try again. Example: git status" >&2
  git status -s >&2
  exit 1
fi

if [[ "${DEPLOY_SKIP_BACKUP:-}" != "1" ]]; then
  echo "==> Backing up database (pre-deploy)"
  bash "$REPO_ROOT/scripts/backup_db.sh"
else
  echo "==> Skipping database backup (DEPLOY_SKIP_BACKUP=1)"
fi

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Building and restarting stack"
if [[ "${DEPLOY_NO_CACHE:-}" == "1" ]]; then
  docker compose build --no-cache app
  docker compose up -d
else
  docker compose up -d --build
fi

echo "==> Health check"
bash "$REPO_ROOT/scripts/healthcheck.sh"

echo "Deploy finished."
