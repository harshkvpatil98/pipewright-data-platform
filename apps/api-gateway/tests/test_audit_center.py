"""The Audit Center: admin-only, filterable, and retention-enforcing.

The one thing this must never do is show a non-admin other people's actions
across projects, so that is asserted first. Then the filters that make a large
stream usable, and the retention sweep that actually prunes rather than just
displaying a policy.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model mapping
from api_gateway.audit_center import (
    export_csv,
    list_audit_entries,
    sweep_audit_entries,
    total_audit_entries,
)
from service_auth.schemas import UserRead
from service_governance.models import AuditEntry
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import ForbiddenError

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
SETTINGS = SimpleNamespace(audit_retention_days=0)


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


def _read(role: str) -> UserRead:
    return UserRead(id=uuid.uuid4(), username=role, role=role,
                    is_active=True, created_at=NOW, updated_at=NOW)


def _entry(db, *, actor="alice", method="POST", path="/api/v1/projects", action="create project",
           outcome="success", project=None, created=NOW) -> None:
    db.add(
        AuditEntry(
            project_id=project.id if project else None,
            actor_username=actor,
            method=method,
            path=path,
            action=action,
            resource_type="project",
            status_code=201 if outcome == "success" else 403,
            outcome=outcome,
            created_at=created,
        )
    )


@pytest.fixture()
def world(db: Session) -> dict:
    project = Project(name="Ops", slug="ops", status="active")
    db.add(project)
    db.flush()
    _entry(db, actor="alice", outcome="success", project=project)
    _entry(db, actor="bob", outcome="failure", method="DELETE", path="/api/v1/projects/x",
           action="delete project", project=project)
    _entry(db, actor="admin", method="POST", path="/api/v1/auth/users", action="create user",
           outcome="success", project=None)  # a global admin action, no project
    db.commit()
    return {"project": project}


def test_a_non_admin_cannot_read_the_audit_centre(db: Session, world: dict) -> None:
    with pytest.raises(ForbiddenError):
        list_audit_entries(db, current_user=_read("viewer"), settings=SETTINGS)


def test_an_admin_sees_every_project_and_global_actions(db: Session, world: dict) -> None:
    result = list_audit_entries(db, current_user=_read("admin"), settings=SETTINGS)
    assert len(result.items) == 3
    # The global (no-project) admin action is included, with a null project.
    assert any(row.project_id is None and row.action == "create user" for row in result.items)
    # Project rows carry the project name.
    assert any(row.project_name == "Ops" for row in result.items)


def test_filters_narrow_the_stream(db: Session, world: dict) -> None:
    admin = _read("admin")
    assert len(list_audit_entries(db, current_user=admin, settings=SETTINGS, outcome="failure").items) == 1
    assert len(list_audit_entries(db, current_user=admin, settings=SETTINGS, actor="bob").items) == 1
    assert len(list_audit_entries(db, current_user=admin, settings=SETTINGS, method="delete").items) == 1
    assert len(list_audit_entries(db, current_user=admin, settings=SETTINGS, query="user").items) == 1


def test_export_is_csv_with_a_header(db: Session, world: dict) -> None:
    csv_text = export_csv(db, current_user=_read("admin"), settings=SETTINGS)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("created_at,actor,project,method")
    assert len(lines) == 4  # header + 3 rows


def test_export_is_admin_only(db: Session, world: dict) -> None:
    with pytest.raises(ForbiddenError):
        export_csv(db, current_user=_read("viewer"), settings=SETTINGS)


def test_retention_sweep_prunes_old_entries(db: Session, world: dict) -> None:
    _entry(db, actor="ancient", created=NOW - timedelta(days=400))
    db.commit()
    assert total_audit_entries(db) == 4

    # 0 days keeps everything.
    assert sweep_audit_entries(db, retention_days=0, now=NOW) == 0
    # 365-day window prunes the 400-day-old entry, keeps the rest.
    assert sweep_audit_entries(db, retention_days=365, now=NOW) == 1
    assert total_audit_entries(db) == 3
