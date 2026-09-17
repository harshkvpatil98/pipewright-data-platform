#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .venv/bin/activate ]]; then
  echo "error: Python venv missing at .venv/. Run setup first: make setup (or ./scripts/setup.sh)" >&2
  exit 1
fi

echo "== Python: ruff (gateway + services + shared-python + dev orchestrator) =="
source .venv/bin/activate
ruff check apps/api-gateway/src services packages/shared-python/src \
  tools/dev-orchestrator/src tools/dev-orchestrator/tests

echo "== Python: pytest (repo test bundle) =="
bash ./scripts/test.sh

echo "== Web: ESLint (@platform/web) =="
npm run lint --workspace @platform/web

echo "== Web: TypeScript (tsc --noEmit) =="
npm run typecheck --workspace @platform/web

echo "== Web: production build =="
npm run build --workspace @platform/web

echo "Release verification finished successfully."
