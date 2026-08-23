#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

cp -n .env.example .env || true
cp -n apps/web/.env.example apps/web/.env || true
cp -n apps/api-gateway/.env.example apps/api-gateway/.env || true

npm install

# Rush is optional here: npm workspaces (above) install everything the app and CI
# need. Rush has no committed lockfile in common/config/rush, so `rush install`
# cannot succeed on a fresh clone -- don't let it abort setup.
if ! ./scripts/rush.sh install; then
  echo "warning: 'rush install' failed; continuing (npm workspaces already installed JS deps)." >&2
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "error: Python 3.11+ required, found $(python3 -V 2>&1). Install a newer Python and re-run." >&2
  exit 1
fi

python3 -m venv .venv
source .venv/bin/activate
CURRENT_PYTHONPATH="$ROOT_DIR/apps/api-gateway/src:$ROOT_DIR/packages/shared-python/src"
for service_src in "$ROOT_DIR"/services/*/src; do
  CURRENT_PYTHONPATH="${CURRENT_PYTHONPATH}:$service_src"
done
export PYTHONPATH="${CURRENT_PYTHONPATH}${PYTHONPATH:+:$PYTHONPATH}"

pip install --upgrade pip
# Order matters: these packages depend on each other by name and are not published
# to PyPI, so each one must already be installed before a dependent is built.
pip install -e packages/shared-python
pip install -e services/service-auth
pip install -e services/service-projects
pip install -e services/service-access
pip install -e services/service-sources
pip install -e services/service-datasets
pip install -e services/service-pipeline-runs
pip install -e services/service-ingestion
pip install -e services/service-comparisons
pip install -e services/service-notifications
pip install -e services/service-destinations
pip install -e services/service-transformations
pip install -e services/service-schedules
pip install -e services/service-quality
pip install -e services/service-extraction
pip install -e services/service-writeback
pip install -e services/service-enterprise
pip install -e services/service-governance
pip install -e services/service-connectors
pip install -e services/service-observability
pip install -e services/service-reporting
pip install -e services/service-workflows
pip install -e services/service-lineage
pip install -e services/service-intelligence
pip install -e 'apps/api-gateway[dev]'

# APP_SECRET_ENCRYPTION_KEY ships empty in .env.example; saved destination / BI /
# webhook secrets are encrypted with it, so generate one on first setup.
if grep -q '^APP_SECRET_ENCRYPTION_KEY=$' apps/api-gateway/.env; then
  GENERATED_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  python - "$GENERATED_KEY" <<'PY'
import pathlib
import sys

env_path = pathlib.Path("apps/api-gateway/.env")
env_path.write_text(
    env_path.read_text().replace(
        "APP_SECRET_ENCRYPTION_KEY=\n", f"APP_SECRET_ENCRYPTION_KEY={sys.argv[1]}\n", 1
    )
)
PY
  echo "Generated APP_SECRET_ENCRYPTION_KEY in apps/api-gateway/.env"
fi

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
