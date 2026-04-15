from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from service_auth.schemas import UserRead
from service_destinations.schemas import DestinationCreate
from service_destinations.service import create_destination
from shared_python.errors import MisconfiguredEnvironmentError


def _user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@patch("service_destinations.service.ensure_owned_project")
def test_create_destination_requires_encryption_key(ensure_owned: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_SECRET_ENCRYPTION_KEY", raising=False)
    ensure_owned.return_value = None
    db = MagicMock()
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
    with pytest.raises(MisconfiguredEnvironmentError):
        create_destination(db, uuid.uuid4(), payload, _user())
