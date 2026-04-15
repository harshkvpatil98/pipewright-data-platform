#!/usr/bin/env bash
# Pragmatic release-candidate / acceptance checks: repo layout, optional live API probes.
# Does not replace `make verify` (full lint, tests, web build). Use both before tagging.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

API_ROOT="${SMOKE_API_ROOT:-http://localhost:8000}"
API_V1="${API_ROOT}/api/v1"

echo "== Release-candidate smoke / acceptance (repo: ${ROOT_DIR}) =="
echo ""

echo "-- Local prerequisites (informational) --"
if [[ -d .venv ]]; then
  echo "ok: Python venv present (.venv)"
else
  echo "warn: .venv missing — run make setup (or ./scripts/setup.sh) before make verify"
fi

if [[ -d apps/web/node_modules ]]; then
  echo "ok: web dependencies present (apps/web/node_modules)"
else
  echo "warn: web node_modules may be missing — run npm install / Rush install from repo root"
fi

if [[ -f apps/api-gateway/.env ]]; then
  echo "ok: apps/api-gateway/.env exists"
else
  echo "warn: apps/api-gateway/.env missing — copy from .env.example (see docs/demo-guide.md)"
fi

if [[ -f apps/web/.env ]]; then
  echo "ok: apps/web/.env exists"
else
  echo "warn: apps/web/.env missing — copy from apps/web/.env.example"
fi

echo ""
echo "-- Database migrations (run on a configured gateway env) --"
echo "  alembic -c apps/api-gateway/alembic.ini upgrade head"
echo ""

echo "-- Documentation (reviewer / operator) --"
echo "  Handoff:     README.md (Release candidate handoff)"
echo "  Checklist:   docs/release-checklist.md"
echo "  Demo path:   docs/demo-guide.md"
echo "  Deploy:      docs/deployment-guide.md"
echo ""

if [[ "${SMOKE_SKIP_NETWORK:-}" == "1" ]]; then
  echo "SMOKE_SKIP_NETWORK=1 set — skipping HTTP checks."
  echo "Smoke script finished (offline mode)."
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "warn: curl not installed — skipping HTTP checks."
  exit 0
fi

echo "-- API probes (gateway must be running: make dev) --"
FAIL=0
if curl -sfS "${API_V1}/health/live" -o /tmp/smoke-live.json 2>/dev/null; then
  echo "ok: GET ${API_V1}/health/live"
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import json; d=json.load(open('/tmp/smoke-live.json')); print(' gateway version:', d.get('version','?'), '| env:', d.get('environment','?'))" 2>/dev/null || true
  fi
else
  echo "fail: ${API_V1}/health/live not reachable (start stack: make dev)"
  FAIL=1
fi

if curl -sfS "${API_V1}/status" -o /tmp/smoke-status.json 2>/dev/null; then
  echo "ok: GET ${API_V1}/status"
else
  echo "fail: ${API_V1}/status not reachable"
  FAIL=1
fi

echo ""
echo "-- Full verification (before RC tag) --"
echo "  make verify   # ruff, pytest bundle, eslint, tsc, next build"
echo ""

if [[ "$FAIL" -ne 0 ]]; then
  echo "Smoke finished with API failures — fix connectivity or set SMOKE_SKIP_NETWORK=1 for offline checks only."
  exit 1
fi

echo "Smoke checks passed."
exit 0
