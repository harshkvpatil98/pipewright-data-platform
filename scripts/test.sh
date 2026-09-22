#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .venv/bin/activate ]]; then
  echo "error: Python venv missing at .venv/. Run setup first: make setup (or ./scripts/setup.sh)" >&2
  exit 1
fi

source .venv/bin/activate

# The pytest paths below are listed explicitly, so a new test directory has to
# be added here deliberately or it will never run in `npm test` or
# `npm run verify`.
pytest --import-mode=importlib \
  apps/api-gateway/tests \
  packages/shared-python/tests \
  services/service-auth/tests \
  services/service-access/tests \
  services/service-enterprise/tests \
  services/service-governance/tests \
  services/service-projects/tests \
  services/service-sources/tests \
  services/service-datasets/tests \
  services/service-pipeline-runs/tests \
  services/service-comparisons/tests \
  services/service-destinations/tests \
  services/service-ingestion/tests \
  services/service-transformations/tests \
  services/service-quality/tests \
  services/service-extraction/tests \
  services/service-writeback/tests \
  services/service-workbench/tests \
  services/service-connectors/tests \
  services/service-reporting/tests \
  services/service-workflows/tests \
  services/service-lineage/tests \
  services/service-intelligence/tests \
  services/service-observability/tests \
  services/service-schedules/tests \
  services/service-notifications/tests

npm run test --workspace @platform/web
