"""Deleting a destination, and deleting a BI connection.

Both are rows in `destination_configs`, separated by their type. That is the
detail worth a test: the BI endpoint looks its row up through
`get_bi_connection_model`, which filters on the BI types, so a request naming
an ordinary Postgres destination cannot remove it through the BI route.

Neither could be removed at all before, so a destination pointing at a
warehouse that was decommissioned months ago stayed in every publish picker,
with its stored credentials, indefinitely.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_destinations.bi_service import delete_bi_connection
from service_destinations.models import DestinationConfig
from service_destinations.service import delete_destination
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import NotFoundError


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, _record):  # noqa: ANN001
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _read(user: User) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user.id, username=user.username, role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def world(db: Session) -> dict:
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    stranger = User(username="stranger", password_hash="x", role="admin", is_active=True)
    db.add_all([owner, stranger])
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.flush()
    warehouse = DestinationConfig(
        project_id=project.id,
        name="Analytics warehouse",
        destination_type="postgres",
        status="active",
        config_json={"host": "db.internal"},
    )
    power_bi = DestinationConfig(
        project_id=project.id,
        name="Exec Power BI",
        destination_type="power_bi",
        status="active",
        config_json={"workspace_id": "abc"},
    )
    db.add_all([warehouse, power_bi])
    db.commit()
    return {
        "owner": owner,
        "stranger": stranger,
        "project": project,
        "warehouse": warehouse,
        "power_bi": power_bi,
    }


def test_a_destination_can_be_deleted(db: Session, world: dict):
    delete_destination(
        db, world["project"].id, world["warehouse"].id, _read(world["owner"])
    )
    assert db.get(DestinationConfig, world["warehouse"].id) is None


def test_a_stranger_cannot_delete_a_destination(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_destination(
            db, world["project"].id, world["warehouse"].id, _read(world["stranger"])
        )
    assert db.get(DestinationConfig, world["warehouse"].id) is not None


def test_a_destination_from_another_project_is_not_reachable(db: Session, world: dict):
    other = Project(name="Other", slug="other", owner_user_id=world["owner"].id, status="active")
    db.add(other)
    db.commit()

    with pytest.raises(NotFoundError):
        delete_destination(db, other.id, world["warehouse"].id, _read(world["owner"]))
    assert db.get(DestinationConfig, world["warehouse"].id) is not None


def test_a_bi_connection_can_be_deleted(db: Session, world: dict):
    delete_bi_connection(
        db, world["project"].id, world["power_bi"].id, _read(world["owner"])
    )
    assert db.get(DestinationConfig, world["power_bi"].id) is None


def test_the_bi_route_cannot_delete_an_ordinary_destination(db: Session, world: dict):
    """Both live in one table, and only the type keeps them apart.

    Deleting by id alone would let a request aimed at the BI endpoint remove a
    warehouse connection that the BI screens never showed.
    """
    with pytest.raises(NotFoundError):
        delete_bi_connection(
            db, world["project"].id, world["warehouse"].id, _read(world["owner"])
        )
    assert db.get(DestinationConfig, world["warehouse"].id) is not None


def test_deleting_a_destination_that_does_not_exist_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_destination(db, world["project"].id, uuid.uuid4(), _read(world["owner"]))
