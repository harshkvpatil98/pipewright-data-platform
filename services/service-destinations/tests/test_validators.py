from __future__ import annotations

import pytest

from service_destinations.validators import (
    redact_config,
    validate_config_for_type,
    validate_postgres_config,
)
from shared_python.errors import BadRequestError


def test_postgres_config_requires_fields() -> None:
    with pytest.raises(BadRequestError):
        validate_postgres_config({})


def test_postgres_config_port_range() -> None:
    with pytest.raises(BadRequestError):
        validate_postgres_config(
            {
                "host": "h",
                "port": 99999,
                "database": "d",
                "username": "u",
                "password": "p",
            }
        )


def test_postgres_config_ok() -> None:
    out = validate_postgres_config(
        {
            "host": "db.example.com",
            "port": "5432",
            "database": "app",
            "username": "u",
            "password": "secret",
            "schema": "public",
            "ssl_mode": "require",
        }
    )
    assert out["port"] == 5432
    assert out["schema"] == "public"


def test_redact_masks_password() -> None:
    r = redact_config({"host": "h", "password": "x", "nested": {"secret_access_key": "y"}})
    assert r["password"] == "***"
    assert r["nested"]["secret_access_key"] == "***"
    assert r["host"] == "h"


def test_s3_config_requires_bucket() -> None:
    with pytest.raises(BadRequestError):
        validate_config_for_type(
            "s3",
            {"access_key_id": "a", "secret_access_key": "s"},
        )
