#!/usr/bin/env bash
# Deploy Treasurer from a git checkout on the server (see docs/Runbook-Hetzner.md).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example to .env and set SECRET_KEY and SITE_ADDRESS." >&2
  exit 1
fi

echo "==> Backing up database (pre-deploy)"
bash "$REPO_ROOT/scripts/backup_db.sh"

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Building and restarting stack"
docker compose up -d --build

echo "==> Health check"
bash "$REPO_ROOT/scripts/healthcheck.sh"

echo "Deploy finished."
