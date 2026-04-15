from __future__ import annotations

import pytest

from service_destinations.validators import (
    merge_config_preserving_secrets,
    redact_config,
    validate_power_bi_config,
    validate_tableau_config,
)
from shared_python.errors import BadRequestError


def test_power_bi_requires_secrets() -> None:
    with pytest.raises(BadRequestError):
        validate_power_bi_config({"tenant_id": "t", "client_id": "c"})


def test_power_bi_ok_minimal() -> None:
    out = validate_power_bi_config(
        {"tenant_id": "tid", "client_id": "cid", "client_secret": "sec"},
    )
    assert out["tenant_id"] == "tid"
    assert out["client_secret"] == "sec"


def test_power_bi_optional_workspace_uuid() -> None:
    out = validate_power_bi_config(
        {
            "tenant_id": "tid",
            "client_id": "cid",
            "client_secret": "sec",
            "workspace_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        },
    )
    assert "workspace_id" in out


def test_power_bi_invalid_workspace() -> None:
    with pytest.raises(BadRequestError):
        validate_power_bi_config(
            {"tenant_id": "t", "client_id": "c", "client_secret": "s", "workspace_id": "not-a-uuid"},
        )


def test_tableau_password_mode() -> None:
    out = validate_tableau_config(
        {
            "server_url": "https://tableau.example.com",
            "auth_mode": "password",
            "username": "u",
            "password": "p",
        },
    )
    assert out["server_url"] == "https://tableau.example.com"
    assert out["username"] == "u"


def test_tableau_pat_mode() -> None:
    out = validate_tableau_config(
        {
            "server_url": "https://tableau.example.com",
            "auth_mode": "personal_access_token",
            "personal_access_token_name": "n",
            "personal_access_token_secret": "s",
        },
    )
    assert out["personal_access_token_name"] == "n"


def test_tableau_requires_https() -> None:
    with pytest.raises(BadRequestError):
        validate_tableau_config(
            {
                "server_url": "http://insecure.example.com",
                "username": "u",
                "password": "p",
            },
        )


def test_redact_bi_secrets() -> None:
    r = redact_config({"client_secret": "x", "personal_access_token_secret": "y"})
    assert r["client_secret"] == "***"
    assert r["personal_access_token_secret"] == "***"


def test_merge_power_bi_secret_placeholder() -> None:
    merged = merge_config_preserving_secrets(
        {"tenant_id": "t", "client_id": "c", "client_secret": "stored"},
        {"client_secret": "***"},
        destination_type="power_bi",
    )
    assert merged["client_secret"] == "stored"
