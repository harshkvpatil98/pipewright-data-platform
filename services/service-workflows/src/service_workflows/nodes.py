"""Node handlers: the bridge from a graph node to the service that does the work.

Each handler receives the node's configuration plus a `NodeContext` carrying the
outputs of every upstream node that has already finished, and returns a
`NodeResult`. Handlers never raise for expected failures -- a failed node is a
normal outcome the executor routes on, not an exception.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from shared_python.errors import ApplicationError, BadRequestError
from shared_python.logging import get_logger

logger = get_logger(__name__)


@dataclass
class NodeContext:
    """Everything a handler needs that is not its own configuration."""

    db: Session
    project_id: uuid.UUID
    current_user: UserRead
    storage_backend: Any
    settings: Any
    # node_key -> that node's output, for resolving `dataset_from`.
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeResult:
    success: bool
    message: str
    output: dict[str, Any] = field(default_factory=dict)
    pipeline_run_id: uuid.UUID | None = None


def _require_uuid(config: dict[str, Any], key: str) -> uuid.UUID:
    raw = config.get(key)
    if not raw:
        raise BadRequestError(f"This node is missing '{key}'.")
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError) as exc:
        raise BadRequestError(f"'{key}' must be a valid id.") from exc


def resolve_dataset(config: dict[str, Any], context: NodeContext) -> uuid.UUID:
    """Find the dataset a node should act on.

    `dataset_from` points at an upstream node and uses whatever dataset that node
    produced, which is what lets a chain operate on fresh data each run rather
    than a hard-coded id. `dataset_id` pins a specific dataset instead.
    """
    upstream_key = config.get("dataset_from")
    if upstream_key:
        output = context.outputs.get(str(upstream_key))
        if not output:
            raise BadRequestError(
                f"This node reads from '{upstream_key}', which produced no output."
            )
        dataset_id = output.get("dataset_id")
        if not dataset_id:
            raise BadRequestError(f"Upstream node '{upstream_key}' did not produce a dataset.")
        return uuid.UUID(str(dataset_id))

    return _require_uuid(config, "dataset_id")


# --------------------------------------------------------------------- handlers


def run_extraction_node(config: dict[str, Any], context: NodeContext) -> NodeResult:
    from service_extraction.extract import run_extraction_job

    job_id = _require_uuid(config, "extraction_job_id")
    result = run_extraction_job(
        context.db,
        project_id=context.project_id,
        job_id=job_id,
        current_user=context.current_user,
        storage_backend=context.storage_backend,
        settings=context.settings,
    )
    return NodeResult(
        success=True,
        message=(
            f"Extracted {result.rows_extracted} row(s); "
            f"{result.rows_added} added, {result.rows_updated} updated."
        ),
        output={
            "dataset_id": str(result.dataset_id),
            "rows_extracted": result.rows_extracted,
            "total_rows": result.total_rows,
            "load_mode": result.load_mode,
        },
        pipeline_run_id=result.run_id,
    )


def run_transformation_node(config: dict[str, Any], context: NodeContext) -> NodeResult:
    from service_transformations.run import run_saved_transformation_pipeline

    pipeline_id = _require_uuid(config, "pipeline_id")
    result = run_saved_transformation_pipeline(
        context.db,
        project_id=context.project_id,
        pipeline_id=pipeline_id,
        current_user=context.current_user,
        storage_backend=context.storage_backend,
        settings=context.settings,
        # The workflow reports the overall outcome; per-step notifications would
        # be noise on every run.
        notify_on_complete=False,
    )
    return NodeResult(
        success=True,
        message=f"Pipeline produced dataset '{result.dataset.name}'.",
        output={
            "dataset_id": str(result.dataset.id),
            "row_count": result.dataset.row_count,
            "column_count": result.dataset.column_count,
        },
        pipeline_run_id=result.run.id,
    )


def run_quality_gate_node(config: dict[str, Any], context: NodeContext) -> NodeResult:
    """Evaluate quality rules and fail the node when error-severity rules fail.

    This is what makes a gate a gate: downstream nodes joined by `on_success`
    will not run, so bad data cannot reach a publish.
    """
    from service_quality.schemas import DataQualityEvaluationRequest
    from service_quality.service import evaluate_dataset

    dataset_id = resolve_dataset(config, context)
    rule_ids = config.get("rule_ids") or None
    quarantine = bool(config.get("quarantine", False))

    evaluation = evaluate_dataset(
        context.db,
        context.project_id,
        dataset_id,
        DataQualityEvaluationRequest(
            quarantine=quarantine,
            rule_ids=[uuid.UUID(str(value)) for value in rule_ids] if rule_ids else None,
        ),
        context.current_user,
        context.storage_backend,
        context.settings,
    )

    output = {
        # A quarantining gate passes the clean rows downstream, not the original.
        "dataset_id": str(evaluation.quarantine_dataset_id or dataset_id),
        "evaluated_dataset_id": str(dataset_id),
        "quality_status": evaluation.status,
        "rules_evaluated": evaluation.rules_evaluated,
        "rules_failed": evaluation.rules_failed,
        "rows_passing": evaluation.rows_passing,
        "rows_quarantined": evaluation.rows_quarantined,
        "quarantine_dataset_id": str(evaluation.quarantine_dataset_id)
        if evaluation.quarantine_dataset_id
        else None,
    }

    if evaluation.error_failures > 0:
        failing = [
            result.name
            for result in evaluation.results
            if result.status == "failed" and result.severity == "error"
        ]
        _raise_incident(
            context,
            # Fingerprinted on the dataset and the rules that failed, so the
            # same nightly failure groups but a different rule does not.
            fingerprint_parts=(dataset_id, ",".join(sorted(failing))),
            source_kind="quality",
            title=f"Quality gate failing on {len(failing)} rule(s)",
            summary=(
                f"{', '.join(failing[:3])}"
                + (f" and {len(failing) - 3} more" if len(failing) > 3 else "")
                + f" failed across {evaluation.rows_in} row(s)."
            ),
            severity="high",
            dataset_id=dataset_id,
            context_data={"failing_rules": failing, "rows_in": evaluation.rows_in},
        )
        return NodeResult(
            success=False,
            message=(
                f"Quality gate failed: {evaluation.error_failures} error-severity rule(s) "
                f"did not pass across {evaluation.rows_in} row(s)."
            ),
            output=output,
        )

    suffix = (
        f" ({evaluation.warning_failures} warning(s))" if evaluation.warning_failures else ""
    )
    return NodeResult(
        success=True,
        message=f"Quality gate passed: {evaluation.rules_evaluated} rule(s) checked{suffix}.",
        output=output,
    )


def _raise_incident(
    context: NodeContext,
    *,
    fingerprint_parts: tuple[Any, ...],
    source_kind: str,
    title: str,
    summary: str,
    severity: str,
    dataset_id: uuid.UUID | None = None,
    context_data: dict[str, Any] | None = None,
) -> None:
    """Open or update an incident for a gate that just failed.

    Never raises: an incident is a notification, and failing a run because the
    notification could not be written would be worse than the missing record.
    """
    try:
        from service_observability.incidents import fingerprint_for, report

        report(
            context.db,
            project_id=context.project_id,
            fingerprint=fingerprint_for(source_kind, *fingerprint_parts),
            title=title,
            summary=summary,
            source_kind=source_kind,
            severity=severity,
            dataset_id=dataset_id,
            context=context_data,
        )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("incident_report_failed source_kind=%s", source_kind)


def run_drift_gate_node(config: dict[str, Any], context: NodeContext) -> NodeResult:
    """Stop a run when the source schema changed underneath it.

    Drift was already detected and recorded before this existed; what was
    missing was consequence. A column disappearing upstream would be written to
    a table nobody looked at while the pipeline carried on publishing a dataset
    that had quietly lost a field.

    The gate compares against an explicit baseline when given one, and
    otherwise against the drift already recorded for this dataset -- which is
    what an extraction node one step earlier will have produced.
    """
    from service_quality.drift import SEVERITY_ORDER, detect_schema_drift
    from service_quality.drift_service import record_drift_event
    from service_quality.models import SchemaDriftEvent
    from service_datasets.service import get_dataset_model_for_project

    dataset_id = resolve_dataset(config, context)
    block_on = str(config.get("block_on") or "breaking").lower()
    if block_on not in SEVERITY_ORDER or block_on == "none":
        raise BadRequestError(
            "'block_on' must be one of: breaking, risky, compatible."
        )
    threshold = SEVERITY_ORDER[block_on]

    baseline_raw = config.get("baseline_dataset_id")
    severity = "none"
    summary = "No schema change detected."
    details: dict[str, Any] = {}

    if baseline_raw:
        baseline_id = _require_uuid(config, "baseline_dataset_id")
        current = get_dataset_model_for_project(context.db, context.project_id, dataset_id)
        baseline = get_dataset_model_for_project(context.db, context.project_id, baseline_id)
        report = detect_schema_drift(baseline.schema_json, current.schema_json)
        severity, summary = report.severity, report.summary
        details = report.to_dict()
        if report.has_drift:
            record_drift_event(
                context.db,
                project_id=context.project_id,
                dataset_id=current.id,
                previous_dataset_id=baseline.id,
                report=report,
            )
    else:
        # The most recent unacknowledged drift for this dataset, which is what
        # an upstream extraction records when the source schema moves.
        event = context.db.scalar(
            select(SchemaDriftEvent)
            .where(
                SchemaDriftEvent.project_id == context.project_id,
                SchemaDriftEvent.dataset_id == dataset_id,
                SchemaDriftEvent.acknowledged.is_(False),
            )
            .order_by(SchemaDriftEvent.created_at.desc())
            .limit(1)
        )
        if event is not None:
            severity, summary = event.severity, event.summary
            details = {
                "added_columns": event.added_columns or [],
                "removed_columns": event.removed_columns or [],
                "type_changes": event.type_changes or [],
                "drift_event_id": str(event.id),
            }

    output = {
        "dataset_id": str(dataset_id),
        "drift_severity": severity,
        "block_on": block_on,
        **details,
    }

    if SEVERITY_ORDER.get(severity, 0) >= threshold:
        _raise_incident(
            context,
            fingerprint_parts=(dataset_id,),
            source_kind="drift",
            title="Schema drift blocked a workflow run",
            summary=summary,
            severity="critical" if severity == "breaking" else "high",
            dataset_id=dataset_id,
            context_data=output,
        )
        return NodeResult(
            success=False,
            message=f"Drift gate failed ({severity}): {summary}",
            output=output,
        )

    passed = (
        "No schema change detected."
        if severity == "none"
        else f"Schema changed ({severity}), which is below the '{block_on}' threshold."
    )
    return NodeResult(success=True, message=passed, output=output)


def run_publish_node(config: dict[str, Any], context: NodeContext) -> NodeResult:
    from service_destinations.publish_schemas import DatasetPublishPostgresRequest
    from service_destinations.publish_service import publish_dataset_to_postgres

    dataset_id = resolve_dataset(config, context)
    request = DatasetPublishPostgresRequest(
        destination_id=_require_uuid(config, "destination_id"),
        table_name=str(config.get("table_name") or ""),
        write_mode=config.get("write_mode", "replace"),
    )

    published = publish_dataset_to_postgres(
        context.db,
        project_id=context.project_id,
        dataset_id=dataset_id,
        payload=request,
        current_user=context.current_user,
        storage_backend=context.storage_backend,
        notify_on_complete=False,
    )
    return NodeResult(
        success=published.success,
        message=published.message,
        output={"dataset_id": str(dataset_id), "table_name": request.table_name},
    )


def run_reverse_etl_node(config: dict[str, Any], context: NodeContext) -> NodeResult:
    """Push a dataset back out to wherever people actually work.

    The last mile of an ETL platform: cleaned data is worth nothing sitting in a
    dataset nobody opens. This writes it to any connector that declares the
    `write` capability -- an S3 bucket, a folder, a SaaS API -- so the numbers
    land in the tool the team already has open.

    The connector's own config lives on the node rather than in a saved
    connection, because a reverse-ETL target is usually specific to the workflow
    that writes it.
    """
    from service_connectors.protocol import ConnectorError, StreamRef
    from service_connectors.registry import get as get_connector, validate_config
    from service_transformations.dataset_access import build_step_context

    connector_type = str(config.get("connector_type") or "").strip()
    if not connector_type:
        raise BadRequestError("This node is missing 'connector_type'.")

    connector = get_connector(connector_type)
    if not connector.spec.supports("write"):
        raise BadRequestError(
            f"{connector.spec.label} can be read but not written to. "
            f"Writable connectors: see the connector catalogue."
        )

    mode = str(config.get("mode") or "replace")
    target = str(config.get("target") or "").strip()
    if not target:
        raise BadRequestError("This node is missing 'target': where to write.")

    dataset_id = resolve_dataset(config, context)
    step_context = build_step_context(
        context.db, project_id=context.project_id, storage_backend=context.storage_backend
    )
    frame = step_context.load_dataset(str(dataset_id))

    connector_config = validate_config(connector_type, dict(config.get("config") or {}))
    try:
        result = connector.write(  # type: ignore[attr-defined]
            connector_config, StreamRef(name=target, kind="file"), frame, mode=mode
        )
    except ConnectorError as exc:
        return NodeResult(success=False, message=exc.message)

    return NodeResult(
        success=True,
        message=result.message,
        output={
            "dataset_id": str(dataset_id),
            "rows_written": result.rows_written,
            "target": target,
            "connector_type": connector_type,
            "mode": result.mode,
        },
    )


def run_notify_node(config: dict[str, Any], context: NodeContext) -> NodeResult:
    from service_notifications.service import create_user_notification

    message = str(config.get("message") or "Workflow reached a notify step.")
    level = str(config.get("level") or "info")
    create_user_notification(
        context.db,
        user_id=context.current_user.id,
        project_id=context.project_id,
        type="workflow",
        level=level,
        title=str(config.get("title") or "Workflow notification"),
        message=message,
    )
    return NodeResult(success=True, message="Notification sent.", output={})


NodeHandler = Callable[[dict[str, Any], NodeContext], NodeResult]

NODE_HANDLERS: dict[str, NodeHandler] = {
    "extraction": run_extraction_node,
    "transformation": run_transformation_node,
    "quality_gate": run_quality_gate_node,
    "drift_gate": run_drift_gate_node,
    "publish": run_publish_node,
    "reverse_etl": run_reverse_etl_node,
    "notify": run_notify_node,
}


def execute_node(node_type: str, config: dict[str, Any], context: NodeContext) -> NodeResult:
    """Run one node, converting expected failures into a failed result."""
    handler = NODE_HANDLERS.get(node_type)
    if handler is None:
        return NodeResult(success=False, message=f"Unsupported node type '{node_type}'.")

    try:
        return handler(config or {}, context)
    except ApplicationError as exc:
        # A misconfigured or failing step is an outcome the graph routes on.
        return NodeResult(success=False, message=str(exc.detail))
    except Exception as exc:  # noqa: BLE001 - one bad node must not kill the run
        logger.exception("workflow_node_unexpected_error node_type=%s", node_type)
        return NodeResult(success=False, message=f"Unexpected error: {exc.__class__.__name__}")
