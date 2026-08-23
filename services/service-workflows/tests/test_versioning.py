"""Workflow history against real workflows.

The governance tests use a stub resource because they are about versioning
itself. These are about the part that has to be true for versioning to be worth
anything: that a real workflow can be snapshotted, edited, and put back exactly
as it was.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_governance.models import ResourceVersion
from service_governance.schemas import RestoreRequest
from service_governance.service import restore_resource_version
from service_projects.models import Project
from service_workflows.models import WorkflowEdge, WorkflowNode
from service_workflows.schemas import (
    WorkflowCreate,
    WorkflowEdgeInput,
    WorkflowNodeInput,
    WorkflowUpdate,
)
from service_workflows.service import create_workflow, update_workflow
from service_workflows.versioning import snapshot_workflow
from shared_python.db import Base


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def owner(db: Session) -> User:
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def actor(owner: User) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=owner.id, username="owner", role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def project(db: Session, owner: User) -> Project:
    row = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(row)
    db.commit()
    return row


def _node(key: str, name: str, node_type: str = "notify") -> WorkflowNodeInput:
    return WorkflowNodeInput(
        node_key=key,
        name=name,
        node_type=node_type,
        config={"title": name, "message": name},
        continue_on_failure=False,
        position_x=0.0,
        position_y=0.0,
    )


@pytest.fixture()
def workflow(db: Session, project: Project, actor: UserRead):
    return create_workflow(
        db,
        project.id,
        WorkflowCreate(
            name="Nightly",
            description="First version",
            nodes=[_node("extract", "Extract"), _node("publish", "Publish")],
            edges=[
                WorkflowEdgeInput(
                    from_node_key="extract", to_node_key="publish", condition="on_success"
                )
            ],
        ),
        actor,
    )


def _versions(db: Session, workflow_id: uuid.UUID) -> list[ResourceVersion]:
    return list(
        db.scalars(
            select(ResourceVersion)
            .where(ResourceVersion.resource_id == workflow_id)
            .order_by(ResourceVersion.version)
        ).all()
    )


def test_creating_a_workflow_records_the_first_version(db: Session, workflow, project):
    versions = _versions(db, workflow.id)
    assert [version.version for version in versions] == [1]
    assert versions[0].change_summary == "Created."
    assert versions[0].snapshot_json["name"] == "Nightly"
    assert len(versions[0].snapshot_json["nodes"]) == 2


def test_editing_records_a_second_version_that_says_what_changed(
    db: Session, workflow, project, actor
):
    update_workflow(
        db, project.id, workflow.id, WorkflowUpdate(name="Nightly ETL"), actor
    )
    versions = _versions(db, workflow.id)
    assert [version.version for version in versions] == [1, 2]
    assert "name" in versions[1].change_summary


def test_a_save_that_changes_nothing_adds_no_version(db: Session, workflow, project, actor):
    update_workflow(db, project.id, workflow.id, WorkflowUpdate(name="Nightly"), actor)
    assert len(_versions(db, workflow.id)) == 1


def test_the_snapshot_captures_nodes_and_edges(db: Session, workflow, project):
    snapshot = snapshot_workflow(db, project.id, workflow.id)
    assert snapshot is not None
    assert [node["node_key"] for node in snapshot["nodes"]] == ["extract", "publish"]
    assert snapshot["edges"] == [
        {"from_node_key": "extract", "to_node_key": "publish", "condition": "on_success"}
    ]


def test_restoring_puts_the_graph_back(db: Session, workflow, project, actor):
    """The thing people actually want: undo a bad edit."""
    update_workflow(
        db,
        project.id,
        workflow.id,
        WorkflowUpdate(name="Broken", nodes=[_node("only", "Only")], edges=[]),
        actor,
    )
    assert db.scalars(
        select(WorkflowNode).where(WorkflowNode.workflow_id == workflow.id)
    ).all().__len__() == 1

    restore_resource_version(
        db, project.id, "workflow", workflow.id, RestoreRequest(version=1), actor
    )

    nodes = db.scalars(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow.id)).all()
    edges = db.scalars(select(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow.id)).all()
    assert sorted(node.node_key for node in nodes) == ["extract", "publish"]
    assert len(edges) == 1


def test_restoring_keeps_the_intervening_versions(db: Session, workflow, project, actor):
    update_workflow(db, project.id, workflow.id, WorkflowUpdate(name="Broken"), actor)
    restore_resource_version(
        db, project.id, "workflow", workflow.id, RestoreRequest(version=1), actor
    )
    versions = _versions(db, workflow.id)
    assert [version.version for version in versions] == [1, 2, 3]
    assert versions[2].restored_from_version == 1


def test_restoring_does_not_rewrite_what_actually_ran(db: Session, workflow, project, actor):
    """A definition rollback must not touch run history."""
    from service_workflows.models import Workflow

    live = db.get(Workflow, workflow.id)
    live.execution_count = 7
    live.last_run_status = "succeeded"
    db.commit()

    update_workflow(db, project.id, workflow.id, WorkflowUpdate(name="Broken"), actor)
    restore_resource_version(
        db, project.id, "workflow", workflow.id, RestoreRequest(version=1), actor
    )

    db.refresh(live)
    assert live.execution_count == 7
    assert live.last_run_status == "succeeded"
    assert live.name == "Nightly"


def test_restoring_reinstates_the_schedule(db: Session, workflow, project, actor):
    from service_workflows.models import Workflow

    update_workflow(
        db,
        project.id,
        workflow.id,
        WorkflowUpdate(trigger_type="cron", cron_expression="0 2 * * *", timezone="UTC"),
        actor,
    )
    live = db.get(Workflow, workflow.id)
    assert live.next_run_at is not None

    restore_resource_version(
        db, project.id, "workflow", workflow.id, RestoreRequest(version=1), actor
    )
    db.refresh(live)
    assert live.trigger_type == "manual"
    # A manual workflow has nothing scheduled, so the next run must be cleared.
    assert live.next_run_at is None
