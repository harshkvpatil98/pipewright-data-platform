"""Execute a workflow run: walk the graph in dependency order and record results."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_workflows.graph import (
    MISSING_SETTING,
    GraphEdge,
    GraphNode,
    runnable,
    should_run,
    topological_levels,
    validate_graph,
)
from service_workflows.models import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
)
from service_workflows.macros import MacroContext, resolve_config
from service_workflows.nodes import NodeContext, NodeResult, execute_node
from shared_python.errors import ApplicationError
from shared_python.logging import get_logger

logger = get_logger(__name__)

TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "partial", "cancelled"})

#: The longest wait between two tries of a task, however long its backoff grew.
MAX_RETRY_WAIT_SECONDS = 900

#: How a retry waits. A module attribute so tests can count the waits instead
#: of sitting through them.
_sleep = time.sleep


def retry_wait_seconds(first_wait: int, retry: int) -> int:
    """The wait before retry number `retry` (1 for the first): doubling, capped."""
    return min(MAX_RETRY_WAIT_SECONDS, max(1, first_wait) * 2 ** (retry - 1))


def settings_hash(node: WorkflowNode) -> str:
    """A fingerprint of what decides a task's result: its type and settings.

    Its name, its place on the canvas and its retry policy do not change what
    it makes, so changing them does not stop a run being picked up.
    """
    canonical = json.dumps({"type": node.node_type, "config": node.config_json or {}}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _reusable_results(db: Session, run: WorkflowRun) -> dict[str, WorkflowNodeRun]:
    """What already succeeded in the run this one resumes, by task."""
    if run.resumed_from_run_id is None:
        return {}
    rows = db.scalars(
        select(WorkflowNodeRun).where(
            WorkflowNodeRun.workflow_run_id == run.resumed_from_run_id,
            WorkflowNodeRun.status == "succeeded",
        )
    ).all()
    return {row.node_key: row for row in rows}


def _keep_the_lease(db: Session, run: WorkflowRun, settings: Any, waiting: int) -> None:
    """A retry's wait is part of the run: extend the worker's lease over it."""
    if run.claim_expires_at is None:
        return
    lease = int(getattr(settings, "workflow_lease_seconds", None) or 180)
    run.claim_expires_at = datetime.now(UTC) + timedelta(seconds=waiting + lease)
    db.commit()


def _load_graph(db: Session, workflow_id: uuid.UUID) -> tuple[list[WorkflowNode], list[WorkflowEdge]]:
    nodes = list(
        db.scalars(
            select(WorkflowNode)
            .where(WorkflowNode.workflow_id == workflow_id)
            .order_by(WorkflowNode.node_key)
        ).all()
    )
    edges = list(
        db.scalars(select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow_id)).all()
    )
    return nodes, edges


def _actor_for_run(db: Session, run: WorkflowRun, workflow: Workflow) -> UserRead | None:
    """Resolve who a run acts as.

    A worker executes outside any request, so the run carries its triggering user
    and falls back to the workflow's creator. Without an actor the run cannot
    perform ownership-checked work and is failed rather than silently escalated.
    """
    for candidate in (run.triggered_by_user_id, workflow.created_by_user_id):
        if candidate is None:
            continue
        user = db.get(User, candidate)
        if user is not None:
            return UserRead.model_validate(user, from_attributes=True)
    return None


def execute_workflow_run(
    db: Session,
    *,
    run: WorkflowRun,
    storage_backend: Any,
    settings: Any,
) -> WorkflowRun:
    """Run every node the graph says should run, in dependency order.

    The run is committed as it progresses so a caller polling the API sees nodes
    complete one by one rather than nothing until the end.
    """
    workflow = db.get(Workflow, run.workflow_id)
    if workflow is None:
        return _finish(db, run, status="failed", error="The workflow no longer exists.")

    actor = _actor_for_run(db, run, workflow)
    if actor is None:
        return _finish(
            db,
            run,
            status="failed",
            error="This run has no user to act as; set a triggering user or workflow owner.",
        )

    node_rows, edge_rows = _load_graph(db, workflow.id)
    graph_nodes = [
        GraphNode(key=row.node_key, node_type=row.node_type, name=row.name, config=row.config_json or {})
        for row in node_rows
    ]
    graph_edges = [
        GraphEdge(from_key=row.from_node_key, to_key=row.to_node_key, condition=row.condition)
        for row in edge_rows
    ]

    validation = validate_graph(graph_nodes, graph_edges)
    if not runnable(validation):
        issues = [*validation.errors, *(w for w in validation.warnings if w.code == MISSING_SETTING)]
        summary = " ".join(issue.message for issue in issues)
        return _finish(db, run, status="failed", error=f"This workflow cannot run yet. {summary}")

    by_key = {row.node_key: row for row in node_rows}
    levels = topological_levels(graph_nodes, graph_edges)
    reusable = _reusable_results(db, run)

    run.status = "running"
    run.started_at = datetime.now(UTC)
    run.nodes_total = len(node_rows)
    db.commit()

    statuses: dict[str, str] = {}
    outputs: dict[str, dict[str, Any]] = {}
    parameters = dict(run.parameters_json or {})
    context = NodeContext(
        db=db,
        project_id=run.project_id,
        current_user=actor,
        storage_backend=storage_backend,
        settings=settings,
        outputs=outputs,
        parameters=parameters,
    )

    # Macros resolve against the run's slot, not the moment it executes, so a
    # backfill for March produces March's values.
    macro_context = MacroContext.for_run(
        logical_date=run.logical_date,
        workflow_name=workflow.name,
        parameters=parameters,
        now=run.started_at,
    )

    sequence = 0
    hard_failure = False
    reused: set[str] = set()

    for level in levels:
        for node_key in level:
            node = by_key[node_key]
            sequence += 1

            allowed, reason = should_run(node_key, graph_edges, statuses)
            if not allowed:
                statuses[node_key] = "skipped"
                _record(
                    db,
                    run=run,
                    node=node,
                    sequence=sequence,
                    status="skipped",
                    skip_reason=reason,
                )
                run.nodes_skipped += 1
                db.commit()
                continue

            earlier = reusable.get(node_key)
            fingerprint = settings_hash(node)
            upstream = [edge.from_key for edge in graph_edges if edge.to_key == node_key]
            if (
                earlier is not None
                and earlier.settings_hash == fingerprint
                and all(key in reused for key in upstream)
            ):
                # Resumed run: this task already did its work with these
                # settings on the same input, so its result stands, and what
                # it made feeds the tasks after it. A task changed since, or
                # one after a task that ran again, runs again.
                reused.add(node_key)
                statuses[node_key] = "succeeded"
                outputs[node_key] = dict(earlier.output_json or {})
                run.nodes_succeeded += 1
                _record(
                    db, run=run, node=node, sequence=sequence, status="succeeded",
                    started_at=earlier.started_at, finished_at=earlier.finished_at,
                    output=earlier.output_json,
                    message="Not run again: it succeeded in the run this one picks up from.",
                    pipeline_run_id=earlier.pipeline_run_id, attempts=earlier.attempts,
                    settings_hash=fingerprint,
                )
                db.commit()
                continue

            started = datetime.now(UTC)
            raw_config = dict(node.config_json or {})
            attempts = 0
            while True:
                attempts += 1
                try:
                    node_config = resolve_config(raw_config, macro_context)
                except ApplicationError as exc:
                    # An unresolvable macro is this node's failure, not the
                    # run's, and trying again would not change it.
                    result = NodeResult(success=False, message=str(exc.detail))
                    break
                result = execute_node(node.node_type, node_config, context)
                if result.success or attempts > node.retries:
                    break
                waiting = retry_wait_seconds(node.retry_delay_seconds, attempts)
                logger.info(
                    "workflow_task_retry run_id=%s task=%s attempt=%s wait=%ss",
                    run.id, node_key, attempts, waiting,
                )
                _keep_the_lease(db, run, settings, waiting)
                _sleep(waiting)
            finished = datetime.now(UTC)
            if node.retries and attempts > 1:
                tries = f"attempt {attempts} of {node.retries + 1}"
                result.message = (
                    f"{result.message} (succeeded on {tries})"
                    if result.success
                    else f"{result.message} (failed {attempts} times)"
                )

            status = "succeeded" if result.success else "failed"
            statuses[node_key] = status
            if result.success:
                outputs[node_key] = result.output
                run.nodes_succeeded += 1
                # A metric history only exists if something writes to it every
                # run. Doing it here, once, covers every node type that
                # produces a dataset rather than each handler remembering to.
                _capture_metrics(db, run=run, output=result.output)
                _record_usage(db, run=run, node=node, output=result.output, started=started, finished=finished)
            else:
                run.nodes_failed += 1
                if not node.continue_on_failure:
                    hard_failure = True

            _record(
                db,
                run=run,
                node=node,
                sequence=sequence,
                status=status,
                started_at=started,
                finished_at=finished,
                output=result.output,
                message=result.message,
                pipeline_run_id=result.pipeline_run_id,
                attempts=attempts,
                settings_hash=fingerprint,
            )
            db.commit()

    if hard_failure:
        final_status = "failed"
    elif run.nodes_skipped > 0 or run.nodes_failed > 0:
        # Nothing blocking failed, but the run did not do everything it could.
        final_status = "partial"
    else:
        final_status = "succeeded"

    return _finish(db, run, status=final_status, workflow=workflow)


def _record_usage(
    db: Session,
    *,
    run: WorkflowRun,
    node: Any,
    output: dict[str, Any],
    started: datetime,
    finished: datetime,
) -> None:
    """Attribute what this node cost to the workflow that ran it.

    "The bill went up" is unanswerable without knowing which workflow does the
    most work. Best effort, like metric capture: an accounting gap is a worse
    report, and a failed run is worse than that.
    """
    try:
        from service_enterprise.usage import record

        rows = 0
        for key in ("row_count", "rows_extracted", "rows_written", "total_rows"):
            value = output.get(key) if isinstance(output, dict) else None
            if isinstance(value, int):
                rows = max(rows, value)

        record(
            db,
            project_id=run.project_id,
            subject_type="workflow",
            subject_id=run.workflow_id,
            subject_name=getattr(node, "name", None),
            rows_processed=rows,
            compute_ms=(finished - started).total_seconds() * 1000,
        )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("usage_record_failed run_id=%s", run.id)


def _capture_metrics(db: Session, *, run: WorkflowRun, output: dict[str, Any]) -> None:
    """Record this run's numbers for the dataset a node just produced.

    Best effort by design: a missing measurement must never fail a run that
    otherwise did its job, and the profile it reads may legitimately not be
    there yet.
    """
    dataset_id = output.get("dataset_id") if isinstance(output, dict) else None
    if not dataset_id:
        return

    try:
        from service_datasets.models import Dataset
        from service_observability.service import record_dataset_metrics

        dataset = db.get(Dataset, uuid.UUID(str(dataset_id)))
        if dataset is None or not isinstance(dataset.profile_json, dict):
            return
        record_dataset_metrics(
            db,
            project_id=run.project_id,
            dataset_id=dataset.id,
            profile=dataset.profile_json,
            workflow_run_id=run.id,
            logical_date=run.logical_date,
        )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("workflow_metric_capture_failed run_id=%s", run.id)


def _record(
    db: Session,
    *,
    run: WorkflowRun,
    node: WorkflowNode,
    sequence: int,
    status: str,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    output: dict[str, Any] | None = None,
    message: str | None = None,
    skip_reason: str | None = None,
    pipeline_run_id: uuid.UUID | None = None,
    attempts: int = 1,
    settings_hash: str | None = None,
) -> None:
    duration = None
    if started_at and finished_at:
        duration = int((finished_at - started_at).total_seconds() * 1000)

    db.add(
        WorkflowNodeRun(
            workflow_run_id=run.id,
            project_id=run.project_id,
            node_key=node.node_key,
            node_name=node.name,
            node_type=node.node_type,
            status=status,
            sequence=sequence,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration,
            output_json=output or None,
            message=message[:2000] if message else None,
            skip_reason=skip_reason[:500] if skip_reason else None,
            pipeline_run_id=pipeline_run_id,
            attempts=attempts,
            settings_hash=settings_hash,
        )
    )


def _finish(
    db: Session,
    run: WorkflowRun,
    *,
    status: str,
    error: str | None = None,
    workflow: Workflow | None = None,
) -> WorkflowRun:
    run.status = status
    run.finished_at = datetime.now(UTC)
    run.error_message = error[:2000] if error else None
    # Release the lease so a stalled worker cannot reclaim a finished run.
    run.claim_owner_id = None
    run.claim_expires_at = None

    target = workflow or db.get(Workflow, run.workflow_id)
    if target is not None:
        target.last_run_at = run.finished_at
        target.last_run_status = status
        target.execution_count = int(target.execution_count or 0) + 1

    db.commit()
    db.refresh(run)
    _notify_run_outcome(db, run, target, status, error)
    return run


def _notify_run_outcome(
    db: Session,
    run: WorkflowRun,
    workflow: Workflow | None,
    status: str,
    error: str | None,
) -> None:
    """In-app notification when a run does not fully succeed. Best effort: a
    notification failure must never turn a finished run back into an error."""
    if status not in ("failed", "partial"):
        return
    recipient = run.triggered_by_user_id or (workflow.created_by_user_id if workflow else None)
    if recipient is None:
        return
    try:
        from service_notifications.outcomes import notify_workflow_run_outcome

        notify_workflow_run_outcome(
            db,
            user_id=recipient,
            project_id=run.project_id,
            workflow_name=workflow.name if workflow else "workflow",
            status=status,
            error=error,
        )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("workflow_run_notify_failed run_id=%s", run.id)
