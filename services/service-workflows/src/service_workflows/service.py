"""Workflow management: create, read, update, delete, and inspect runs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from service_workflows.cron import apply_schedule
from service_workflows.versioning import record_workflow_version
from service_workflows.graph import GraphEdge, GraphNode, topological_levels, validate_graph
from service_workflows.models import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
)
from service_workflows.rundiff import diff_node_runs
from service_workflows.timeline import build_timeline
from service_workflows.schemas import (
    WorkflowCreate,
    WorkflowDetail,
    WorkflowEdgeInput,
    WorkflowEdgeRead,
    WorkflowListResponse,
    WorkflowNodeInput,
    WorkflowNodeRead,
    WorkflowNodeRunRead,
    WorkflowRead,
    NodeDiffRead,
    RunDiffResponse,
    RunTimelineRead,
    WorkflowRunDetail,
    WorkflowRunListResponse,
    WorkflowRunRead,
    WorkflowUpdate,
    WorkflowValidationResponse,
)
from shared_python.errors import BadRequestError, NotFoundError

MAX_RUN_HISTORY = 200


def get_workflow_for_project(db: Session, project_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
    workflow = db.scalar(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.project_id == project_id)
    )
    if workflow is None:
        raise NotFoundError("Workflow not found.")
    return workflow


def _graph_of(db: Session, workflow_id: uuid.UUID) -> tuple[list[WorkflowNode], list[WorkflowEdge]]:
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


def _validate_and_order(
    nodes: list[WorkflowNode], edges: list[WorkflowEdge]
) -> tuple[dict[str, Any], list[list[str]]]:
    graph_nodes = [GraphNode(key=row.node_key, node_type=row.node_type) for row in nodes]
    graph_edges = [
        GraphEdge(from_key=row.from_node_key, to_key=row.to_node_key, condition=row.condition)
        for row in edges
    ]
    validation = validate_graph(graph_nodes, graph_edges)
    order = topological_levels(graph_nodes, graph_edges) if validation.valid else []
    return validation.to_dict(), order


def _replace_graph(
    db: Session,
    *,
    workflow: Workflow,
    nodes: list[WorkflowNodeInput],
    edges: list[WorkflowEdgeInput],
) -> None:
    """Swap the whole graph atomically, rejecting it if the result is unrunnable.

    Validating before writing means a workflow can never be left in a state the
    executor would refuse.
    """
    graph_nodes = [GraphNode(key=item.node_key, node_type=item.node_type) for item in nodes]
    graph_edges = [
        GraphEdge(from_key=item.from_node_key, to_key=item.to_node_key, condition=item.condition)
        for item in edges
    ]
    validation = validate_graph(graph_nodes, graph_edges)
    if not validation.valid:
        raise BadRequestError(
            "This graph cannot run: " + "; ".join(issue.message for issue in validation.errors)
        )

    for existing in db.scalars(
        select(WorkflowNode).where(WorkflowNode.workflow_id == workflow.id)
    ).all():
        db.delete(existing)
    for existing_edge in db.scalars(
        select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow.id)
    ).all():
        db.delete(existing_edge)
    db.flush()

    for item in nodes:
        db.add(
            WorkflowNode(
                workflow_id=workflow.id,
                project_id=workflow.project_id,
                node_key=item.node_key,
                name=item.name,
                node_type=item.node_type,
                config_json=dict(item.config),
                continue_on_failure=item.continue_on_failure,
                position_x=item.position_x,
                position_y=item.position_y,
            )
        )
    for item in edges:
        db.add(
            WorkflowEdge(
                workflow_id=workflow.id,
                from_node_key=item.from_node_key,
                to_node_key=item.to_node_key,
                condition=item.condition,
            )
        )
    db.flush()


def list_workflows(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> WorkflowListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(
        select(Workflow)
        .where(Workflow.project_id == project_id)
        .order_by(Workflow.created_at.desc())
    ).all()
    return WorkflowListResponse(
        items=[WorkflowRead.model_validate(row, from_attributes=True) for row in rows]
    )


def get_workflow_detail(
    db: Session, project_id: uuid.UUID, workflow_id: uuid.UUID, current_user: UserRead
) -> WorkflowDetail:
    ensure_owned_project(db, project_id, current_user.id)
    workflow = get_workflow_for_project(db, project_id, workflow_id)
    nodes, edges = _graph_of(db, workflow.id)
    validation, order = _validate_and_order(nodes, edges)

    base = WorkflowRead.model_validate(workflow, from_attributes=True)
    return WorkflowDetail(
        **base.model_dump(),
        nodes=[WorkflowNodeRead.model_validate(row, from_attributes=True) for row in nodes],
        edges=[WorkflowEdgeRead.model_validate(row, from_attributes=True) for row in edges],
        validation=validation,
        execution_order=order,
    )


def create_workflow(
    db: Session, project_id: uuid.UUID, payload: WorkflowCreate, current_user: UserRead
) -> WorkflowDetail:
    ensure_owned_project(db, project_id, current_user.id)

    workflow = Workflow(
        project_id=project_id,
        name=payload.name.strip(),
        description=payload.description,
        trigger_type=payload.trigger_type,
        cron_expression=payload.cron_expression,
        timezone=payload.timezone,
        default_parameters=dict(payload.default_parameters) or None,
        created_by_user_id=current_user.id,
    )
    apply_schedule(workflow)
    db.add(workflow)
    db.flush()

    if payload.nodes:
        _replace_graph(db, workflow=workflow, nodes=payload.nodes, edges=payload.edges)

    record_workflow_version(
        db,
        project_id=project_id,
        workflow_id=workflow.id,
        name=workflow.name,
        actor_user_id=current_user.id,
    )
    db.commit()
    db.refresh(workflow)
    return get_workflow_detail(db, project_id, workflow.id, current_user)


def update_workflow(
    db: Session,
    project_id: uuid.UUID,
    workflow_id: uuid.UUID,
    payload: WorkflowUpdate,
    current_user: UserRead,
) -> WorkflowDetail:
    ensure_owned_project(db, project_id, current_user.id)
    workflow = get_workflow_for_project(db, project_id, workflow_id)

    if payload.name is not None:
        workflow.name = payload.name.strip()
    if payload.description is not None:
        workflow.description = payload.description
    if payload.enabled is not None:
        workflow.enabled = payload.enabled
    if payload.trigger_type is not None:
        workflow.trigger_type = payload.trigger_type
    if payload.cron_expression is not None:
        workflow.cron_expression = payload.cron_expression
    if payload.timezone is not None:
        workflow.timezone = payload.timezone
    if payload.default_parameters is not None:
        workflow.default_parameters = dict(payload.default_parameters) or None

    if workflow.trigger_type == "cron" and not (workflow.cron_expression or "").strip():
        raise BadRequestError("cron_expression is required when trigger_type is 'cron'.")

    # Trigger, timezone, or enabled may all have moved; recompute from scratch.
    apply_schedule(workflow)

    if payload.nodes is not None or payload.edges is not None:
        current_nodes, current_edges = _graph_of(db, workflow.id)
        nodes = (
            payload.nodes
            if payload.nodes is not None
            else [
                WorkflowNodeInput(
                    node_key=row.node_key,
                    name=row.name,
                    node_type=row.node_type,
                    config=dict(row.config_json or {}),
                    continue_on_failure=row.continue_on_failure,
                    position_x=row.position_x,
                    position_y=row.position_y,
                )
                for row in current_nodes
            ]
        )
        edges = (
            payload.edges
            if payload.edges is not None
            else [
                WorkflowEdgeInput(
                    from_node_key=row.from_node_key,
                    to_node_key=row.to_node_key,
                    condition=row.condition,
                )
                for row in current_edges
            ]
        )
        _replace_graph(db, workflow=workflow, nodes=nodes, edges=edges)

    # Flush first so the snapshot reads the edit, not what was there before it.
    db.flush()
    record_workflow_version(
        db,
        project_id=project_id,
        workflow_id=workflow.id,
        name=workflow.name,
        actor_user_id=current_user.id,
    )
    db.commit()
    return get_workflow_detail(db, project_id, workflow.id, current_user)


def delete_workflow(
    db: Session, project_id: uuid.UUID, workflow_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    workflow = get_workflow_for_project(db, project_id, workflow_id)
    db.delete(workflow)
    db.commit()


def validate_workflow(
    db: Session, project_id: uuid.UUID, workflow_id: uuid.UUID, current_user: UserRead
) -> WorkflowValidationResponse:
    ensure_owned_project(db, project_id, current_user.id)
    workflow = get_workflow_for_project(db, project_id, workflow_id)
    nodes, edges = _graph_of(db, workflow.id)
    validation, order = _validate_and_order(nodes, edges)
    return WorkflowValidationResponse(
        valid=bool(validation["valid"]),
        errors=list(validation["errors"]),
        warnings=list(validation["warnings"]),
        execution_order=order,
    )


def list_runs(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead,
    *,
    workflow_id: uuid.UUID | None = None,
    limit: int = 50,
) -> WorkflowRunListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    statement = select(WorkflowRun).where(WorkflowRun.project_id == project_id)
    if workflow_id is not None:
        statement = statement.where(WorkflowRun.workflow_id == workflow_id)
    rows = db.scalars(
        statement.order_by(WorkflowRun.created_at.desc()).limit(min(limit, MAX_RUN_HISTORY))
    ).all()
    return WorkflowRunListResponse(
        items=[WorkflowRunRead.model_validate(row, from_attributes=True) for row in rows]
    )


def get_run_detail(
    db: Session, project_id: uuid.UUID, run_id: uuid.UUID, current_user: UserRead
) -> WorkflowRunDetail:
    ensure_owned_project(db, project_id, current_user.id)
    run = db.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.project_id == project_id)
    )
    if run is None:
        raise NotFoundError("Workflow run not found.")

    node_runs = db.scalars(
        select(WorkflowNodeRun)
        .where(WorkflowNodeRun.workflow_run_id == run.id)
        .order_by(WorkflowNodeRun.sequence)
    ).all()

    base = WorkflowRunRead.model_validate(run, from_attributes=True)
    timeline = build_timeline(
        run_started_at=run.started_at,
        run_finished_at=run.finished_at,
        node_runs=[_node_run_dict(row) for row in node_runs],
    )
    return WorkflowRunDetail(
        **base.model_dump(),
        node_runs=[
            WorkflowNodeRunRead.model_validate(row, from_attributes=True) for row in node_runs
        ],
        timeline=RunTimelineRead(**timeline.to_dict()),
    )


def _node_run_dict(row: WorkflowNodeRun) -> dict[str, Any]:
    return {
        "node_key": row.node_key,
        "node_name": row.node_name,
        "node_type": row.node_type,
        "status": row.status,
        "sequence": row.sequence,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "duration_ms": row.duration_ms,
        "output_json": row.output_json,
    }


def diff_workflow_runs(
    db: Session,
    project_id: uuid.UUID,
    left_run_id: uuid.UUID,
    right_run_id: uuid.UUID,
    current_user: UserRead,
) -> RunDiffResponse:
    """Explain what changed between two runs.

    Both runs must belong to the same workflow: comparing a nightly extraction
    against an unrelated report would line up nothing and mean less.
    """
    ensure_owned_project(db, project_id, current_user.id)
    if left_run_id == right_run_id:
        raise BadRequestError("A run cannot be compared against itself.")

    runs = {
        run.id: run
        for run in db.scalars(
            select(WorkflowRun).where(
                WorkflowRun.id.in_([left_run_id, right_run_id]),
                WorkflowRun.project_id == project_id,
            )
        ).all()
    }
    left, right = runs.get(left_run_id), runs.get(right_run_id)
    if left is None or right is None:
        raise NotFoundError("Workflow run not found.")
    if left.workflow_id != right.workflow_id:
        raise BadRequestError("Both runs must belong to the same workflow.")

    node_runs = db.scalars(
        select(WorkflowNodeRun)
        .where(WorkflowNodeRun.workflow_run_id.in_([left.id, right.id]))
        .order_by(WorkflowNodeRun.sequence)
    ).all()

    by_run: dict[uuid.UUID, list[dict[str, Any]]] = {left.id: [], right.id: []}
    for row in node_runs:
        by_run[row.workflow_run_id].append(_node_run_dict(row))

    diff = diff_node_runs(by_run[left.id], by_run[right.id])
    return RunDiffResponse(
        left_run_id=left.id,
        right_run_id=right.id,
        left=WorkflowRunRead.model_validate(left, from_attributes=True),
        right=WorkflowRunRead.model_validate(right, from_attributes=True),
        nodes=[NodeDiffRead(**node) for node in diff.to_dict()["nodes"]],
        summary=diff.summary,
        identical=diff.identical,
    )


def total_workflows(db: Session) -> int:
    return db.scalar(select(func.count(Workflow.id))) or 0
