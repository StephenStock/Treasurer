#!/usr/bin/env bash
# Probe /healthz on the app container (no curl required on the host).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! docker compose exec -T app true 2>/dev/null; then
  echo "The app container is not running (it may be crash-looping)." >&2
  echo "Last lines from the app log (look for Traceback / Error / Permission denied):" >&2
  docker compose logs app --tail 80 >&2
  exit 1
fi

docker compose exec -T app python -c "
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/healthz') as r:
    body = r.read()
    assert r.getcode() == 200, r.getcode()
    assert body.strip() == b'ok', body
"

echo "Health check OK (app /healthz -> 200)"
