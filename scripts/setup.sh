#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

cp -n .env.example .env || true
cp -n apps/web/.env.example apps/web/.env || true
cp -n apps/api-gateway/.env.example apps/api-gateway/.env || true

npm install
./scripts/rush.sh install

python3 -m venv .venv
source .venv/bin/activate
CURRENT_PYTHONPATH="$ROOT_DIR/apps/api-gateway/src:$ROOT_DIR/packages/shared-python/src"
for service_src in "$ROOT_DIR"/services/*/src; do
  CURRENT_PYTHONPATH="${CURRENT_PYTHONPATH}:$service_src"
done
export PYTHONPATH="${CURRENT_PYTHONPATH}${PYTHONPATH:+:$PYTHONPATH}"

pip install --upgrade pip
pip install -e packages/shared-python
pip install -e services/service-projects
pip install -e services/service-sources
pip install -e services/service-datasets
pip install -e services/service-auth
pip install -e services/service-pipeline-runs
pip install -e services/service-comparisons
pip install -e services/service-ingestion
pip install -e services/service-transformations
pip install -e services/service-destinations
pip install -e services/service-schedules
pip install -e services/service-notifications
pip install -e 'apps/api-gateway[dev]'

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if ! docker compose up -d --wait postgres 2>/dev/null; then
    docker compose up -d postgres
    sleep 5
  fi
  (
    cd apps/api-gateway
    "$ROOT_DIR/.venv/bin/alembic" -c alembic.ini upgrade head
  )
fi

echo "Setup complete. Run 'make dev' for local development or 'make docker-up' for containers."
