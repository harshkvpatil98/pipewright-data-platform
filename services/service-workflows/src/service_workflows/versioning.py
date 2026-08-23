"""Workflow snapshots, so history and rollback mean something.

Governance owns versions but has no idea what a workflow is: it can store a
JSON document and diff two of them, and that is all. These two functions are
what let it hand a person their workflow back rather than a blob of JSON --
one reads the live graph into a document, the other writes a document back
over the live graph.

Registered on import, which is why the gateway imports this module even though
nothing calls it directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_workflows.cron import apply_schedule
from service_workflows.models import Workflow, WorkflowEdge, WorkflowNode

RESOURCE_TYPE = "workflow"


def snapshot_workflow(
    db: Session, project_id: uuid.UUID, workflow_id: uuid.UUID
) -> dict[str, Any] | None:
    """The whole workflow as one document: settings, nodes, and edges."""
    workflow = db.scalar(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.project_id == project_id)
    )
    if workflow is None:
        return None

    nodes = db.scalars(
        select(WorkflowNode)
        .where(WorkflowNode.workflow_id == workflow_id)
        .order_by(WorkflowNode.node_key)
    ).all()
    edges = db.scalars(
        select(WorkflowEdge)
        .where(WorkflowEdge.workflow_id == workflow_id)
        .order_by(WorkflowEdge.from_node_key, WorkflowEdge.to_node_key)
    ).all()

    return {
        "name": workflow.name,
        "description": workflow.description,
        "enabled": workflow.enabled,
        "trigger_type": workflow.trigger_type,
        "cron_expression": workflow.cron_expression,
        "timezone": workflow.timezone,
        "default_parameters": workflow.default_parameters,
        "nodes": [
            {
                "node_key": node.node_key,
                "name": node.name,
                "node_type": node.node_type,
                "config": dict(node.config_json or {}),
                "continue_on_failure": node.continue_on_failure,
                "position_x": node.position_x,
                "position_y": node.position_y,
            }
            for node in nodes
        ],
        "edges": [
            {
                "from_node_key": edge.from_node_key,
                "to_node_key": edge.to_node_key,
                "condition": edge.condition,
            }
            for edge in edges
        ],
    }


def apply_workflow_snapshot(
    db: Session,
    project_id: uuid.UUID,
    workflow_id: uuid.UUID,
    snapshot: dict[str, Any],
    _actor_user_id: uuid.UUID | None = None,
) -> None:
    """Write a snapshot back over the live workflow.

    Run state -- last run, execution count, the queue -- is deliberately left
    alone. Rolling back a definition must not rewrite the history of what
    actually ran.
    """
    workflow = db.scalar(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.project_id == project_id)
    )
    if workflow is None:
        return

    workflow.name = str(snapshot.get("name") or workflow.name)
    workflow.description = snapshot.get("description")
    workflow.enabled = bool(snapshot.get("enabled", workflow.enabled))
    workflow.trigger_type = str(snapshot.get("trigger_type") or "manual")
    workflow.cron_expression = snapshot.get("cron_expression")
    workflow.timezone = snapshot.get("timezone")
    workflow.default_parameters = snapshot.get("default_parameters")
    apply_schedule(workflow)

    for node in db.scalars(
        select(WorkflowNode).where(WorkflowNode.workflow_id == workflow_id)
    ).all():
        db.delete(node)
    for edge in db.scalars(
        select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow_id)
    ).all():
        db.delete(edge)
    db.flush()

    for entry in snapshot.get("nodes") or []:
        db.add(
            WorkflowNode(
                workflow_id=workflow_id,
                project_id=project_id,
                node_key=str(entry.get("node_key")),
                name=str(entry.get("name") or entry.get("node_key")),
                node_type=str(entry.get("node_type") or "notify"),
                config_json=dict(entry.get("config") or {}),
                continue_on_failure=bool(entry.get("continue_on_failure", False)),
                position_x=float(entry.get("position_x") or 0.0),
                position_y=float(entry.get("position_y") or 0.0),
            )
        )
    for entry in snapshot.get("edges") or []:
        db.add(
            WorkflowEdge(
                workflow_id=workflow_id,
                from_node_key=str(entry.get("from_node_key")),
                to_node_key=str(entry.get("to_node_key")),
                condition=str(entry.get("condition") or "on_success"),
            )
        )
    db.flush()


def record_workflow_version(
    db: Session,
    *,
    project_id: uuid.UUID,
    workflow_id: uuid.UUID,
    name: str,
    actor_user_id: uuid.UUID | None,
) -> None:
    """Snapshot a workflow after it was saved.

    Best effort: a version that failed to record is a gap in history, which is
    bad; a save that failed because history could not be written is worse.
    """
    try:
        from service_governance.versions import record_version

        snapshot = snapshot_workflow(db, project_id, workflow_id)
        if snapshot is None:
            return
        record_version(
            db,
            project_id=project_id,
            resource_type=RESOURCE_TYPE,
            resource_id=workflow_id,
            name=name,
            snapshot=snapshot,
            actor_user_id=actor_user_id,
        )
    except Exception:  # noqa: BLE001 - see docstring
        from shared_python.logging import get_logger

        get_logger(__name__).exception("workflow_version_record_failed id=%s", workflow_id)


def create_empty_workflow(
    db: Session,
    project_id: uuid.UUID,
    name: str,
    actor_user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A shell for a promotion to write into."""
    workflow = Workflow(
        project_id=project_id,
        name=name[:160],
        trigger_type="manual",
        enabled=False,  # Promoted work stays off until somebody turns it on.
        created_by_user_id=actor_user_id,
    )
    db.add(workflow)
    db.flush()
    return workflow.id


def register() -> None:
    """Teach governance how to read, write, create, and promote a workflow."""
    try:
        from service_governance.promotion import (
            find_by_name,
            register_creator,
            register_reference_resolver,
        )
        from service_governance.versions import register_restorer, register_snapshotter

        register_snapshotter(RESOURCE_TYPE, snapshot_workflow)
        register_restorer(RESOURCE_TYPE, apply_workflow_snapshot)
        register_creator(RESOURCE_TYPE, create_empty_workflow)

        # Promotion re-points ids at the same-named thing in the target project.
        from service_datasets.models import Dataset
        from service_destinations.models import DestinationConfig
        from service_extraction.models import ExtractionJob
        from service_transformations.models import TransformationPipeline

        for key, model in (
            ("dataset_id", Dataset),
            ("baseline_dataset_id", Dataset),
            ("right_dataset_id", Dataset),
            ("other_dataset_id", Dataset),
            ("pipeline_id", TransformationPipeline),
            ("extraction_job_id", ExtractionJob),
            ("destination_id", DestinationConfig),
        ):
            register_reference_resolver(key, find_by_name(model))
    except ImportError:  # pragma: no cover - governance is optional at import time
        pass


register()
