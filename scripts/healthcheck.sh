#!/usr/bin/env bash
# Probe /healthz on the app container (no curl required on the host).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

docker compose exec -T app python -c "
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/healthz') as r:
    body = r.read()
    assert r.getcode() == 200, r.getcode()
    assert body.strip() == b'ok', body
"

echo "Health check OK (app /healthz -> 200)"
