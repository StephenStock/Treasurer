#!/usr/bin/env bash
# Snapshot SQLite DB files from the running Docker volume to ./backups on the host.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$REPO_ROOT/backups"
mkdir -p "$DEST"

OUT="$DEST/treasurer-db-${STAMP}.tar"

echo "==> Creating archive: $OUT"
docker compose exec -T app tar -cf - -C /data . >"$OUT"

echo "Backup written: $OUT"
ls -la "$OUT"
