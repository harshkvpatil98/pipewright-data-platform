#!/usr/bin/env bash
# Supervised background runtime: the workflow worker and the schedule ticker.
#
# These are the two processes that make work actually move. Running them under
# one script keeps "start the workers" a single command in dev, and each is
# restarted if it dies so a transient crash does not silently leave the queue
# unattended -- the exact failure the heartbeat panel exists to surface.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .venv/bin/activate ]]; then
  echo "Local Python environment not found. Run 'make setup' first." >&2
  exit 1
fi

set -a
[[ -f .env ]] && source .env
set +a

source .venv/bin/activate
CURRENT_PYTHONPATH="$ROOT_DIR/apps/api-gateway/src:$ROOT_DIR/packages/shared-python/src"
for service_src in "$ROOT_DIR"/services/*/src; do
  CURRENT_PYTHONPATH="${CURRENT_PYTHONPATH}:$service_src"
done
export PYTHONPATH="${CURRENT_PYTHONPATH}${PYTHONPATH:+:$PYTHONPATH}"

WORKFLOW_INTERVAL="${WORKFLOW_WORKER_INTERVAL:-5}"
TICKER_INTERVAL="${SCHEDULE_TICKER_INTERVAL:-30}"

pids=()
cleanup() {
  trap - TERM INT
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup TERM INT EXIT

# Keep a named process alive: if it exits, log and restart after a short pause.
supervise() {
  local name="$1"; shift
  while true; do
    echo "[worker.sh] starting ${name}" >&2
    "$@" || echo "[worker.sh] ${name} exited ($?), restarting in 3s" >&2
    sleep 3
  done
}

supervise "workflow-worker" \
  "$ROOT_DIR/.venv/bin/python" -m api_gateway.scripts.workflow_worker --interval "$WORKFLOW_INTERVAL" &
pids+=($!)

supervise "schedule-ticker" \
  "$ROOT_DIR/.venv/bin/python" -m api_gateway.scripts.run_due_schedules --loop --interval "$TICKER_INTERVAL" &
pids+=($!)

wait -n
