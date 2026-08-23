"""Promoting a workflow between environments.

The part worth testing is not the copy -- it is what the copy cannot carry. A
workflow's config names datasets by id, and those ids belong to the project it
came from. Copying them verbatim gives you a production workflow quietly
reading development data, which is exactly the failure promotion exists to
prevent.
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
from service_datasets.models import Dataset
from service_governance.promotion import remap_references
from service_governance.schemas import PromoteRequest
from service_governance.service import promote
from service_projects.models import Project
from service_workflows.models import Workflow, WorkflowNode
from service_workflows.schemas import WorkflowCreate, WorkflowNodeInput
from service_workflows.service import create_workflow
from shared_python.db import Base
from shared_python.errors import BadRequestError


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
def world(db: Session) -> dict:
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()

    dev = Project(
        name="Ops dev", slug="ops-dev", owner_user_id=owner.id, status="active",
        environment="development",
    )
    prod = Project(
        name="Ops prod", slug="ops-prod", owner_user_id=owner.id, status="active",
        environment="production",
    )
    db.add_all([dev, prod])
    db.flush()

    dev_orders = Dataset(
        project_id=dev.id, name="orders", status="ready", ingestion_status="succeeded"
    )
    prod_orders = Dataset(
        project_id=prod.id, name="orders", status="ready", ingestion_status="succeeded"
    )
    # Present in development only, so promotion has something it cannot match.
    dev_scratch = Dataset(
        project_id=dev.id, name="scratch", status="ready", ingestion_status="succeeded"
    )
    db.add_all([dev_orders, prod_orders, dev_scratch])
    db.commit()

    now = datetime.now(UTC)
    actor = UserRead(
        id=owner.id, username="owner", role="admin", is_active=True,
        created_at=now, updated_at=now,
    )
    return {
        "owner": owner, "actor": actor, "dev": dev, "prod": prod,
        "dev_orders": dev_orders, "prod_orders": prod_orders, "dev_scratch": dev_scratch,
    }


def _workflow(db: Session, world: dict, dataset_id: uuid.UUID):
    return create_workflow(
        db,
        world["dev"].id,
        WorkflowCreate(
            name="Nightly",
            nodes=[
                WorkflowNodeInput(
                    node_key="gate",
                    name="Quality gate",
                    node_type="quality_gate",
                    config={"dataset_id": str(dataset_id)},
                    continue_on_failure=False,
                    position_x=0.0,
                    position_y=0.0,
                )
            ],
            edges=[],
        ),
        world["actor"],
    )


def test_a_reference_is_repointed_at_the_same_name_in_the_target(db: Session, world: dict):
    result = remap_references(
        db,
        {"dataset_id": str(world["dev_orders"].id)},
        source_project_id=world["dev"].id,
        target_project_id=world["prod"].id,
    )
    assert result.snapshot["dataset_id"] == str(world["prod_orders"].id)
    assert result.unresolved == []


def test_a_reference_with_no_match_is_reported_not_guessed(db: Session, world: dict):
    result = remap_references(
        db,
        {"dataset_id": str(world["dev_scratch"].id)},
        source_project_id=world["dev"].id,
        target_project_id=world["prod"].id,
    )
    assert result.snapshot["dataset_id"] is None
    assert [item.key for item in result.unresolved] == ["dataset_id"]


def test_references_nested_inside_lists_are_found(db: Session, world: dict):
    result = remap_references(
        db,
        {"nodes": [{"config": {"dataset_id": str(world["dev_orders"].id)}}]},
        source_project_id=world["dev"].id,
        target_project_id=world["prod"].id,
    )
    assert result.snapshot["nodes"][0]["config"]["dataset_id"] == str(world["prod_orders"].id)


def test_values_that_are_not_references_are_left_alone(db: Session, world: dict):
    original = {"name": "Nightly", "message": "hello", "count": 3, "flag": True}
    result = remap_references(
        db,
        dict(original),
        source_project_id=world["dev"].id,
        target_project_id=world["prod"].id,
    )
    assert result.snapshot == original


def test_promoting_creates_a_workflow_in_the_target_project(db: Session, world: dict):
    workflow = _workflow(db, world, world["dev_orders"].id)
    response = promote(
        db,
        world["dev"].id,
        PromoteRequest(
            target_project_id=world["prod"].id,
            resource_type="workflow",
            resource_id=workflow.id,
        ),
        world["actor"],
    )

    promoted = db.get(Workflow, response.new_resource_id)
    assert promoted is not None
    assert promoted.project_id == world["prod"].id
    assert promoted.name == "Nightly"
    assert response.unresolved == []
    assert "Every reference matched" in response.summary


def test_a_promoted_workflow_points_at_the_targets_own_data(db: Session, world: dict):
    workflow = _workflow(db, world, world["dev_orders"].id)
    response = promote(
        db,
        world["dev"].id,
        PromoteRequest(
            target_project_id=world["prod"].id,
            resource_type="workflow",
            resource_id=workflow.id,
        ),
        world["actor"],
    )

    node = db.scalar(
        select(WorkflowNode).where(WorkflowNode.workflow_id == response.new_resource_id)
    )
    assert node is not None
    assert node.config_json["dataset_id"] == str(world["prod_orders"].id)


def test_a_promoted_workflow_arrives_switched_off(db: Session, world: dict):
    """Nobody wants a schedule to start firing the moment it lands in production."""
    workflow = _workflow(db, world, world["dev_orders"].id)
    response = promote(
        db,
        world["dev"].id,
        PromoteRequest(
            target_project_id=world["prod"].id,
            resource_type="workflow",
            resource_id=workflow.id,
        ),
        world["actor"],
    )
    assert db.get(Workflow, response.new_resource_id).enabled is False


def test_an_unmatched_reference_is_surfaced_in_the_summary(db: Session, world: dict):
    workflow = _workflow(db, world, world["dev_scratch"].id)
    response = promote(
        db,
        world["dev"].id,
        PromoteRequest(
            target_project_id=world["prod"].id,
            resource_type="workflow",
            resource_id=workflow.id,
        ),
        world["actor"],
    )
    assert len(response.unresolved) == 1
    assert "Fill them in before running it" in response.summary


def test_promoting_a_project_into_itself_is_refused(db: Session, world: dict):
    workflow = _workflow(db, world, world["dev_orders"].id)
    with pytest.raises(BadRequestError):
        promote(
            db,
            world["dev"].id,
            PromoteRequest(
                target_project_id=world["dev"].id,
                resource_type="workflow",
                resource_id=workflow.id,
            ),
            world["actor"],
        )


def test_promotion_records_a_version_in_the_target(db: Session, world: dict):
    from service_governance.models import ResourceVersion

    workflow = _workflow(db, world, world["dev_orders"].id)
    response = promote(
        db,
        world["dev"].id,
        PromoteRequest(
            target_project_id=world["prod"].id,
            resource_type="workflow",
            resource_id=workflow.id,
        ),
        world["actor"],
    )

    version = db.scalar(
        select(ResourceVersion).where(ResourceVersion.resource_id == response.new_resource_id)
    )
    assert version is not None
    assert version.project_id == world["prod"].id
