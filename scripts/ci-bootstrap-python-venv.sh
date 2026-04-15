#!/usr/bin/env bash
# Create .venv and install Python packages the same way as scripts/setup.sh (without Docker or Rush).
# Used by GitHub Actions and for local "CI parity" runs: `make ci-verify`.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
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
