"""Execute a workflow run: walk the graph in dependency order and record results."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_workflows.graph import (
    GraphEdge,
    GraphNode,
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
    graph_nodes = [GraphNode(key=row.node_key, node_type=row.node_type) for row in node_rows]
    graph_edges = [
        GraphEdge(from_key=row.from_node_key, to_key=row.to_node_key, condition=row.condition)
        for row in edge_rows
    ]

    validation = validate_graph(graph_nodes, graph_edges)
    if not validation.valid:
        summary = "; ".join(issue.message for issue in validation.errors)
        return _finish(db, run, status="failed", error=f"Workflow is not runnable: {summary}")

    by_key = {row.node_key: row for row in node_rows}
    levels = topological_levels(graph_nodes, graph_edges)

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

            started = datetime.now(UTC)
            raw_config = dict(node.config_json or {})
            try:
                node_config = resolve_config(raw_config, macro_context)
            except ApplicationError as exc:
                # An unresolvable macro is this node's failure, not the run's.
                node_config = None
                result = NodeResult(success=False, message=str(exc.detail))

            if node_config is not None:
                result = execute_node(node.node_type, node_config, context)
            finished = datetime.now(UTC)

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
