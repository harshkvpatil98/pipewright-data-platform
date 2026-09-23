"""Cross-project operator views, and the access rule that scopes them.

The one thing these must never do is widen access: /runs and /datasets aggregate
across projects, so a bug here leaks another tenant's work. These pin that the
views show a user their owned and shared projects and nothing else, plus the
status filter and name search that make them usable at forty projects.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model mapping
import service_access  # noqa: F401  -- registers the membership resolver
from api_gateway.operator_views import list_recent_runs, search_datasets
from service_access.models import ProjectMembership
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_pipeline_runs.models import PipelineRun
from service_projects.models import Project
from shared_python.db import Base

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)


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


def _user(db: Session, name: str) -> User:
    row = User(username=name, password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.flush()
    return row


def _read(user: User) -> UserRead:
    return UserRead(
        id=user.id, username=user.username, role="admin", is_active=True,
        created_at=NOW, updated_at=NOW,
    )


def _project(db: Session, owner: User, name: str) -> Project:
    row = Project(name=name, slug=name.lower(), owner_user_id=owner.id, status="active")
    db.add(row)
    db.flush()
    return row


def _run(db: Session, project: Project, user: User, *, status: str, run_type: str = "transformation_run") -> None:
    db.add(
        PipelineRun(
            project_id=project.id,
            triggered_by_user_id=user.id,
            run_type=run_type,
            status=status,
        )
    )


def _dataset(db: Session, project: Project, name: str) -> None:
    db.add(Dataset(project_id=project.id, name=name, status="ready", ingestion_status="succeeded"))


@pytest.fixture()
def world(db: Session) -> dict:
    alice = _user(db, "alice")
    bob = _user(db, "bob")
    a_proj = _project(db, alice, "Alice-Proj")
    b_proj = _project(db, bob, "Bob-Proj")
    shared = _project(db, bob, "Shared-Proj")
    # Bob shares one of his projects with Alice.
    db.add(ProjectMembership(project_id=shared.id, user_id=alice.id, role="admin"))

    _run(db, a_proj, alice, status="succeeded")
    _run(db, a_proj, alice, status="failed")
    _run(db, b_proj, bob, status="succeeded")  # Alice must never see this
    _run(db, shared, bob, status="running")

    _dataset(db, a_proj, "orders")
    _dataset(db, b_proj, "secret_customers")  # Alice must never see this
    _dataset(db, shared, "orders_shared")
    db.commit()
    return {"alice": alice, "bob": bob, "a_proj": a_proj, "b_proj": b_proj, "shared": shared}


def test_runs_show_owned_and_shared_projects_only(db: Session, world: dict) -> None:
    result = list_recent_runs(db, current_user=_read(world["alice"]))
    names = {row.project_name for row in result.items}
    assert names == {"Alice-Proj", "Shared-Proj"}
    assert "Bob-Proj" not in names  # the private project stays private
    assert len(result.items) == 3  # 2 owned + 1 shared


def test_runs_can_filter_by_status(db: Session, world: dict) -> None:
    result = list_recent_runs(db, current_user=_read(world["alice"]), status="failed")
    assert len(result.items) == 1
    assert result.items[0].status == "failed"
    assert result.items[0].project_name == "Alice-Proj"


def test_datasets_are_scoped_and_searchable(db: Session, world: dict) -> None:
    everything = search_datasets(db, current_user=_read(world["alice"]))
    names = {row.name for row in everything.items}
    assert names == {"orders", "orders_shared"}
    assert "secret_customers" not in names

    filtered = search_datasets(db, current_user=_read(world["alice"]), query="shared")
    assert [row.name for row in filtered.items] == ["orders_shared"]


def test_a_user_with_no_projects_sees_nothing(db: Session) -> None:
    stranger = _user(db, "stranger")
    db.commit()
    assert list_recent_runs(db, current_user=_read(stranger)).items == []
    assert search_datasets(db, current_user=_read(stranger)).items == []
