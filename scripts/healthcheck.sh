#!/usr/bin/env bash
# Probe /healthz on the app container (no curl required on the host).
# Retries: right after `docker compose up`, gunicorn may not be listening yet.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! docker compose exec -T app true 2>/dev/null; then
  echo "The app container is not running (it may be crash-looping)." >&2
  echo "Last lines from the app log (look for Traceback / Error / Permission denied):" >&2
  docker compose logs app --tail 80 >&2
  exit 1
fi

# Single line so we can reuse for the final diagnostic run.
PY_PROBE="import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5); b=r.read(); assert r.getcode() == 200; assert b.strip() == b'ok'"

for ((attempt=1; attempt<=30; attempt++)); do
  if docker compose exec -T app python -c "$PY_PROBE" 2>/dev/null; then
    echo "Health check OK (app /healthz -> 200)"
    exit 0
  fi
  if [[ "$attempt" -eq 1 ]]; then
    echo "Waiting for app to listen on port 8000 (gunicorn may still be starting)..." >&2
  fi
  sleep 1
done

echo "Health check failed: /healthz did not return 200 after ~30s." >&2
docker compose exec -T app python -c "$PY_PROBE" >&2 || true
docker compose logs app --tail 80 >&2
exit 1
