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
