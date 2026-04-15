from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from service_auth.schemas import UserRead
from service_destinations.at_rest_config import destination_config_for_internal_use
from service_destinations.models import DestinationConfig
from service_destinations.schemas import DestinationCreate, DestinationUpdate
from service_destinations.service import create_destination, get_destination, update_destination
from shared_python.errors import NotFoundError


def _user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@patch("service_destinations.service.get_destination_model")
@patch("service_destinations.service.ensure_owned_project", side_effect=NotFoundError("missing"))
def test_get_destination_requires_project(_ensure, _get) -> None:
    with pytest.raises(NotFoundError):
        get_destination(MagicMock(), uuid.uuid4(), uuid.uuid4(), _user())


@patch("service_destinations.service.ensure_owned_project")
@patch("service_destinations.service.get_destination_model")
def test_get_destination_hides_bi_connections(get_model, ensure_owned) -> None:
    ensure_owned.return_value = None
    dest = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="bi",
        destination_type="power_bi",
        status="active",
        config_json={"tenant_id": "t", "client_secret": "x"},
        created_by_user_id=None,
    )
    get_model.return_value = dest
    with pytest.raises(NotFoundError):
        get_destination(MagicMock(), dest.project_id, dest.id, _user())


@patch("service_destinations.service.ensure_owned_project")
@patch("service_destinations.service.get_destination_model")
def test_get_destination_redacts(get_model, ensure_owned) -> None:
    ensure_owned.return_value = None
    dest = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="n",
        destination_type="postgres",
        status="active",
        config_json={
            "host": "h",
            "database": "d",
            "username": "u",
            "password": "secret",
            "port": 5432,
        },
        created_by_user_id=None,
    )
    dest.created_at = datetime.now(UTC)
    dest.updated_at = datetime.now(UTC)
    get_model.return_value = dest
    out = get_destination(MagicMock(), dest.project_id, dest.id, _user())
    assert out.config_json["password"] == "***"


@patch("service_destinations.service.ensure_owned_project")
def test_create_destination(ensure_owned) -> None:
    ensure_owned.return_value = None
    db = MagicMock()

    def refresh(obj: DestinationConfig) -> None:
        obj.created_at = datetime.now(UTC)
        obj.updated_at = datetime.now(UTC)

    db.refresh.side_effect = refresh

    payload = DestinationCreate(
        name="PG",
        destination_type="postgres",
        status="active",
        config_json={
            "host": "localhost",
            "port": 5432,
            "database": "db",
            "username": "u",
            "password": "pw",
        },
    )
    out = create_destination(db, uuid.uuid4(), payload, _user())
    assert out.config_json["password"] == "***"
    db.add.assert_called_once()
    db.commit.assert_called_once()


@patch("service_destinations.service.ensure_owned_project")
@patch("service_destinations.service.get_destination_model")
def test_update_preserves_password_placeholder(get_model, ensure_owned) -> None:
    ensure_owned.return_value = None
    dest = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="n",
        destination_type="postgres",
        status="active",
        config_json={
            "host": "h",
            "port": 5432,
            "database": "d",
            "username": "u",
            "password": "real-secret",
        },
        created_by_user_id=None,
    )
    dest.created_at = datetime.now(UTC)
    dest.updated_at = datetime.now(UTC)
    get_model.return_value = dest
    db = MagicMock()

    def refresh(obj: DestinationConfig) -> None:
        pass

    db.refresh.side_effect = refresh

    update_destination(
        db,
        dest.project_id,
        dest.id,
        DestinationUpdate(config_json={"host": "new.example.com", "password": "***"}),
        _user(),
    )
    plain = destination_config_for_internal_use("postgres", dest.config_json)
    assert plain["password"] == "real-secret"
    assert dest.config_json["host"] == "new.example.com"
