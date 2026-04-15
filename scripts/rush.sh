#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export RUSH_GLOBAL_FOLDER="${RUSH_GLOBAL_FOLDER:-$ROOT_DIR/.rush-global}"

cd "$ROOT_DIR"
npx @microsoft/rush "$@"
