#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .venv/bin/activate ]]; then
  echo "Local Python environment not found. Run 'make setup' first."
  exit 1
fi

cp -n .env.example .env || true
cp -n apps/web/.env.example apps/web/.env || true
cp -n apps/api-gateway/.env.example apps/api-gateway/.env || true

set -a
source .env
set +a

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if ! docker compose up -d --wait postgres 2>/dev/null; then
    docker compose up -d postgres
    sleep 3
  fi
elif command -v docker >/dev/null 2>&1; then
  echo "warning: Docker daemon not reachable; start Docker (or run Postgres locally) before migrations/API will work." >&2
fi

source .venv/bin/activate
CURRENT_PYTHONPATH="$ROOT_DIR/apps/api-gateway/src:$ROOT_DIR/packages/shared-python/src"
for service_src in "$ROOT_DIR"/services/*/src; do
  CURRENT_PYTHONPATH="${CURRENT_PYTHONPATH}:$service_src"
done
export PYTHONPATH="${CURRENT_PYTHONPATH}${PYTHONPATH:+:$PYTHONPATH}"

_pg_check_host="${POSTGRES_HOST:-127.0.0.1}"
_pg_check_port="${POSTGRES_PORT:-5432}"
if ! "$ROOT_DIR/.venv/bin/python" -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('${_pg_check_host}', int('${_pg_check_port}'))); s.close()" 2>/dev/null; then
  echo "error: Postgres not reachable at ${_pg_check_host}:${_pg_check_port} (from root .env). Start Docker and run: docker compose up -d postgres" >&2
  exit 1
fi

(
  cd apps/api-gateway
  "$ROOT_DIR/.venv/bin/alembic" -c alembic.ini upgrade head
)

"$ROOT_DIR/.venv/bin/python" -m uvicorn api_gateway.main:app --reload --host 0.0.0.0 --port "${BACKEND_PORT:-8000}" &
GATEWAY_PID=$!

# The background runtime: without these, workflow runs queue forever and
# schedules never fire -- the exact "healthy but nothing moves" trap P0 warned
# about. dev.sh starts them so a fresh clone has a working queue by default.
# Set PW_DEV_NO_WORKERS=1 to run only the gateway + web (e.g. to test the
# stalled banners deliberately).
WORKER_PID=""
if [[ "${PW_DEV_NO_WORKERS:-0}" != "1" ]]; then
  "$ROOT_DIR/scripts/worker.sh" &
  WORKER_PID=$!
fi

trap 'kill ${GATEWAY_PID} ${WORKER_PID} 2>/dev/null || true' EXIT

npm run dev --workspace @platform/web -- --hostname 0.0.0.0 --port "${FRONTEND_PORT:-3000}"
