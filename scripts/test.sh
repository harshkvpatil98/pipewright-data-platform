#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .venv/bin/activate ]]; then
  echo "error: Python venv missing at .venv/. Run setup first: make setup (or ./scripts/setup.sh)" >&2
  exit 1
fi

source .venv/bin/activate

pytest --import-mode=importlib \
  apps/api-gateway/tests \
  packages/shared-python/tests \
  services/service-auth/tests \
  services/service-projects/tests \
  services/service-sources/tests \
  services/service-datasets/tests \
  services/service-pipeline-runs/tests \
  services/service-comparisons/tests \
  services/service-destinations/tests \
  services/service-ingestion/tests \
  services/service-transformations/tests \
  services/service-schedules/tests \
  services/service-notifications/tests

npm run test --workspace @platform/web
