"""Policy simulation: "would this person see the salary column?"

The pure masking logic is covered in test_security.py. This covers the new
"view as user" seam: that a specific person's effective project role is resolved
for them (owner is admin, a member is their membership role, a stranger falls to
viewer), and that the answer differs accordingly.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model onto one Base
import service_access  # noqa: F401  -- registers the membership resolver
from service_access.models import ProjectMembership
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_enterprise.models import SecurityPolicy
from service_enterprise.service import preview_policies_as_user
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import NotFoundError

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
FRAME = pd.DataFrame(
    {"name": ["a", "b", "c"], "region": ["north", "south", "east"], "salary": [50000, 60000, 70000]}
)


class _Storage:
    def read_bytes(self, _path: str) -> bytes:
        return FRAME.to_csv(index=False).encode()


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


def _read(user: User) -> UserRead:
    return UserRead(id=user.id, username=user.username, role="admin", is_active=True,
                    created_at=NOW, updated_at=NOW)


@pytest.fixture()
def world(db: Session) -> dict:
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    member = User(username="dana", password_hash="x", role="viewer", is_active=True)
    db.add_all([owner, member])
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.flush()
    db.add(ProjectMembership(project_id=project.id, user_id=member.id, role="viewer"))
    dataset = Dataset(
        project_id=project.id, name="payroll", status="ready", ingestion_status="succeeded",
        file_path="datasets/payroll.csv", file_type="csv",
    )
    db.add(dataset)
    db.flush()
    # Viewers cannot see the salary column.
    db.add(
        SecurityPolicy(
            project_id=project.id, dataset_id=dataset.id, name="Hide salary from viewers",
            role="viewer", column_rules_json=[{"column": "salary", "action": "deny"}],
        )
    )
    db.commit()
    return {"owner": owner, "member": member, "project": project, "dataset": dataset}


def test_view_as_a_viewer_member_hides_the_restricted_column(db: Session, world: dict) -> None:
    result = preview_policies_as_user(
        db, world["project"].id, world["dataset"].id, world["member"].id,
        _read(world["owner"]), _Storage(),
    )
    assert result.viewed_as_username == "dana"
    assert result.role == "viewer"
    assert "salary" in result.columns_removed
    assert all("salary" not in row for row in result.sample_rows)


def test_view_as_the_owner_resolves_admin_and_shows_everything(db: Session, world: dict) -> None:
    result = preview_policies_as_user(
        db, world["project"].id, world["dataset"].id, world["owner"].id,
        _read(world["owner"]), _Storage(),
    )
    assert result.viewed_as_username == "owner"
    assert result.role == "admin"
    assert "salary" not in result.columns_removed
    assert any("salary" in row for row in result.sample_rows)


def test_view_as_an_unknown_user_is_not_found(db: Session, world: dict) -> None:
    with pytest.raises(NotFoundError):
        preview_policies_as_user(
            db, world["project"].id, world["dataset"].id, uuid.uuid4(),
            _read(world["owner"]), _Storage(),
        )
