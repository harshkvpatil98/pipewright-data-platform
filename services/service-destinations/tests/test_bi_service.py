from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from service_auth.schemas import UserRead
from service_destinations.bi_schemas import BiIntegrationCreate, BiIntegrationUpdate
from service_destinations.bi_service import (
    check_bi_connection,
    create_bi_connection,
    discover_bi_metadata,
    get_bi_connection,
    list_bi_connections,
    update_bi_connection,
)
from service_destinations.at_rest_config import destination_config_for_internal_use, persist_destination_config_at_rest
from service_destinations.models import DestinationConfig
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


@patch("service_destinations.bi_service.ensure_owned_project", side_effect=NotFoundError("no"))
def test_list_bi_requires_project(_ensure) -> None:
    with pytest.raises(NotFoundError):
        list_bi_connections(MagicMock(), uuid.uuid4(), _user())


@patch("service_destinations.bi_service.ensure_owned_project")
def test_create_bi_persists_power_bi(ensure_owned) -> None:
    ensure_owned.return_value = None
    db = MagicMock()

    def refresh(obj: DestinationConfig) -> None:
        obj.created_at = datetime.now(UTC)
        obj.updated_at = datetime.now(UTC)

    db.refresh.side_effect = refresh

    payload = BiIntegrationCreate(
        name="My PBI",
        integration_type="power_bi",
        config_json={"tenant_id": "t", "client_id": "c", "client_secret": "s"},
    )
    out = create_bi_connection(db, uuid.uuid4(), payload, _user())
    assert out.integration_type == "power_bi"
    assert out.config_json["client_secret"] == "***"
    db.add.assert_called_once()
    db.commit.assert_called_once()


@patch("service_destinations.bi_service.ensure_owned_project")
@patch("service_destinations.bi_service.get_bi_connection_model")
def test_get_bi_redacts(get_model, ensure_owned) -> None:
    ensure_owned.return_value = None
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="n",
        destination_type="power_bi",
        status="active",
        config_json={"tenant_id": "t", "client_id": "c", "client_secret": "secret"},
        created_by_user_id=None,
    )
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    get_model.return_value = row
    out = get_bi_connection(MagicMock(), row.project_id, row.id, _user())
    assert out.config_json["client_secret"] == "***"


@patch("service_destinations.bi_service.check_power_bi_connection")
@patch("service_destinations.bi_service.ensure_owned_project")
@patch("service_destinations.bi_service.get_bi_connection_model")
def test_test_bi_success(get_model, ensure_owned, check_pbi) -> None:
    ensure_owned.return_value = None
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="n",
        destination_type="power_bi",
        status="active",
        config_json={"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        created_by_user_id=None,
    )
    get_model.return_value = row
    check_pbi.return_value = (True, "ok", 10.0, [])
    res = check_bi_connection(MagicMock(), row.project_id, row.id, _user())
    assert res.success is True


@patch("service_destinations.bi_service.check_power_bi_connection")
@patch("service_destinations.bi_service.ensure_owned_project")
@patch("service_destinations.bi_service.get_bi_connection_model")
def test_test_bi_failure(get_model, ensure_owned, check_pbi) -> None:
    ensure_owned.return_value = None
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="n",
        destination_type="power_bi",
        status="active",
        config_json={"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        created_by_user_id=None,
    )
    get_model.return_value = row
    check_pbi.return_value = (False, "bad", 5.0, [])
    res = check_bi_connection(MagicMock(), row.project_id, row.id, _user())
    assert res.success is False


@patch("service_destinations.bi_service.discover_power_bi_workspaces")
@patch("service_destinations.bi_service.ensure_owned_project")
@patch("service_destinations.bi_service.get_bi_connection_model")
def test_discover_power_bi(get_model, ensure_owned, discover) -> None:
    ensure_owned.return_value = None
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="n",
        destination_type="power_bi",
        status="active",
        config_json={"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        created_by_user_id=None,
    )
    get_model.return_value = row
    discover.return_value = [{"id": "1", "name": "W"}]
    meta = discover_bi_metadata(MagicMock(), row.project_id, row.id, _user())
    assert meta.metadata_kind == "power_bi_workspaces"
    assert len(meta.items) == 1


@patch("service_destinations.bi_service.discover_tableau_projects")
@patch("service_destinations.bi_service.ensure_owned_project")
@patch("service_destinations.bi_service.get_bi_connection_model")
def test_discover_tableau(get_model, ensure_owned, discover) -> None:
    ensure_owned.return_value = None
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="n",
        destination_type="tableau",
        status="active",
        config_json={
            "server_url": "https://x.example.com",
            "auth_mode": "password",
            "username": "u",
            "password": "p",
        },
        created_by_user_id=None,
    )
    get_model.return_value = row
    discover.return_value = [{"id": "p1", "name": "Project"}]
    meta = discover_bi_metadata(MagicMock(), row.project_id, row.id, _user())
    assert meta.metadata_kind == "tableau_projects"


@patch("service_destinations.bi_service.ensure_owned_project")
@patch("service_destinations.bi_service.get_bi_connection_model")
def test_update_preserves_power_bi_secret(get_model, ensure_owned) -> None:
    ensure_owned.return_value = None
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="n",
        destination_type="power_bi",
        status="active",
        config_json={"tenant_id": "t", "client_id": "c", "client_secret": "real"},
        created_by_user_id=None,
    )
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    get_model.return_value = row
    db = MagicMock()
    db.refresh.side_effect = lambda o: None

    update_bi_connection(
        db,
        row.project_id,
        row.id,
        BiIntegrationUpdate(config_json={"tenant_id": "t2", "client_id": "c", "client_secret": "***"}),
        _user(),
    )
    plain = destination_config_for_internal_use("power_bi", row.config_json)
    assert plain["client_secret"] == "real"
    assert row.config_json["tenant_id"] == "t2"


@patch("service_destinations.bi_service.check_power_bi_connection")
@patch("service_destinations.bi_service.ensure_owned_project")
@patch("service_destinations.bi_service.get_bi_connection_model")
def test_test_bi_decrypts_stored_secret(get_model, ensure_owned, check_pbi) -> None:
    ensure_owned.return_value = None
    enc = persist_destination_config_at_rest(
        "power_bi",
        {"tenant_id": "t", "client_id": "c", "client_secret": "secret-value"},
    )
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="n",
        destination_type="power_bi",
        status="active",
        config_json=enc,
        created_by_user_id=None,
    )
    get_model.return_value = row
    check_pbi.return_value = (True, "ok", 10.0, [])
    check_bi_connection(MagicMock(), row.project_id, row.id, _user())
    check_pbi.assert_called_once()
    passed = check_pbi.call_args[0][0]
    assert passed["client_secret"] == "secret-value"
