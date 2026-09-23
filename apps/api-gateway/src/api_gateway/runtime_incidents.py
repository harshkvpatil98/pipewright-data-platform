"""Open an incident when the queue stalls, and close it when work moves again.

This is the escalation the runtime panel earns: a red heartbeat tells someone
looking *now*, but nobody watches a status page at 3am. When queued work has
sat past the threshold with no worker draining it, that is an incident -- it
notifies the owner and lives in the list until it is fixed, then resolves
itself the moment work starts moving again so the list never fills with
problems that already went away.

It lives in the gateway because deciding "is the queue stalled?" needs the
workflow queue *and* the heartbeat table *and* the incident store together --
composing three services, which is the gateway's job and no single service's.

Crucially this runs from the schedule ticker, a process independent of the
workflow worker: a dead worker cannot report its own death, so something else
must. If both are dead the status panel still shows it; the incident covers
the common case where the worker dies but the ticker lives on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from service_observability import incidents
from service_observability.runtime import runtime_components
from service_workflows.queue import (
    oldest_queued_at,
    projects_with_queued_runs,
    running_count,
)
from shared_python.logging import get_logger

logger = get_logger(__name__)

# Longer than the banner's 15-minute stall threshold on purpose: the banner is
# a nudge for whoever is on the page, an incident is a durable, notifying record
# and should not fire on a brief hiccup.
STALL_THRESHOLD = timedelta(minutes=30)
FINGERPRINT = "runtime:stalled-queue"


def _worker_alive(db: Session, now: datetime) -> bool:
    for entry in runtime_components(db, now=now):
        if entry["component"] == "workflow-worker" and entry["healthy"]:
            return True
    return False


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def sweep_runtime_incidents(
    db: Session,
    *,
    now: datetime | None = None,
    threshold: timedelta = STALL_THRESHOLD,
) -> dict:
    """Open/recur incidents for projects whose queue is stalled; resolve those
    whose work has started moving again. Returns a small summary for logging."""
    moment = now or datetime.now(UTC)
    cutoff = moment - threshold

    oldest = _as_utc(oldest_queued_at(db))
    running = running_count(db)
    worker_alive = _worker_alive(db, moment)

    # Stalled = old work is waiting, nothing is running, and no worker is beating.
    # All three matter: a running or beating worker is draining or about to.
    globally_stalled = (
        oldest is not None and oldest <= cutoff and running == 0 and not worker_alive
    )
    targets = projects_with_queued_runs(db, older_than=cutoff) if globally_stalled else set()

    opened = 0
    for project_id in targets:
        incidents.report(
            db,
            project_id=project_id,
            fingerprint=FINGERPRINT,
            title="Background work is not being processed",
            summary=(
                "Workflow runs have been queued for over "
                f"{int(threshold.total_seconds() // 60)} minutes with no worker draining them. "
                "Start the workflow worker (scripts/worker.sh) or check System status."
            ),
            source_kind="runtime",
            severity="high",
            now=moment,
        )
        opened += 1

    # Resolve any active stalled-queue incident whose project is no longer a
    # target -- the worker came back, the queue drained, or that project's work
    # cleared. This is the "auto-resolves on drain" half.
    resolved = 0
    for incident in incidents.active_by_fingerprint(db, FINGERPRINT):
        if incident.project_id not in targets:
            incidents.auto_resolve(
                db,
                project_id=incident.project_id,
                fingerprint=FINGERPRINT,
                message="Background work is moving again.",
                now=moment,
            )
            resolved += 1

    db.commit()
    if opened or resolved:
        logger.info("runtime_incident_sweep opened=%s resolved=%s", opened, resolved)
    return {"opened": opened, "resolved": resolved, "stalled": globally_stalled}
