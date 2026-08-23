"""The SDK contract, and the validation every connector inherits from it."""

from __future__ import annotations

import pytest

from service_connectors import adapters  # noqa: F401  - registers the catalogue
from service_connectors.protocol import (
    CAPABILITIES,
    ConfigField,
    ConnectorSpec,
    StreamRef,
)
from service_connectors.registry import (
    known_types,
    redact,
    spec_for,
    specs,
    validate_config,
)
from shared_python.errors import BadRequestError, NotFoundError


def test_a_select_field_without_options_is_a_programming_error():
    with pytest.raises(ValueError):
        ConfigField("mode", "Mode", kind="select")


def test_an_unknown_field_kind_is_rejected_at_definition_time():
    with pytest.raises(ValueError):
        ConfigField("thing", "Thing", kind="hologram")


def test_a_spec_cannot_claim_a_capability_that_does_not_exist():
    with pytest.raises(ValueError):
        ConnectorSpec(
            type="x",
            label="X",
            category="api",
            description="Long enough description.",
            capabilities=frozenset({"teleport"}),
        )


def test_a_spec_knows_which_of_its_fields_are_secret():
    spec = ConnectorSpec(
        type="x",
        label="X",
        category="api",
        description="Long enough description.",
        config_fields=(
            ConfigField("host", "Host"),
            ConfigField("password", "Password", kind="secret"),
            ConfigField("token", "Token", kind="secret", required=False),
        ),
    )
    assert spec.secret_fields == ("password", "token")
    assert spec.required_fields == ("host", "password")


def test_every_registered_connector_is_reachable_by_type():
    assert "postgresql" in known_types()
    assert "rest_api" in known_types()
    assert len(specs()) == len(known_types())


def test_an_unknown_connector_type_lists_what_is_available():
    with pytest.raises(NotFoundError) as caught:
        spec_for("teleporter")
    assert "postgresql" in str(caught.value.detail)


def test_config_validation_fills_in_declared_defaults():
    resolved = validate_config(
        "postgresql",
        {"host": "db", "database": "app", "username": "u", "password": "p"},
    )
    assert resolved["port"] == 5432
    assert resolved["sslmode"] == "require"


def test_a_missing_required_field_names_it_in_the_error():
    with pytest.raises(BadRequestError) as caught:
        validate_config("postgresql", {"host": "db"})
    detail = str(caught.value.detail)
    assert "Database" in detail and "Username" in detail


def test_an_unknown_setting_is_rejected_rather_than_ignored():
    """A typo that silently does nothing costs an afternoon."""
    with pytest.raises(BadRequestError) as caught:
        validate_config(
            "postgresql",
            {"host": "db", "database": "a", "username": "u", "password": "p", "prot": 5432},
        )
    assert "prot" in str(caught.value.detail)


def test_numbers_arrive_as_numbers_even_when_typed_into_a_form():
    resolved = validate_config(
        "postgresql",
        {"host": "db", "database": "a", "username": "u", "password": "p", "port": "6543"},
    )
    assert resolved["port"] == 6543


def test_a_value_outside_a_select_is_refused():
    with pytest.raises(BadRequestError) as caught:
        validate_config(
            "postgresql",
            {
                "host": "db",
                "database": "a",
                "username": "u",
                "password": "p",
                "sslmode": "maybe",
            },
        )
    assert "SSL mode" in str(caught.value.detail)


def test_booleans_accept_the_things_a_form_actually_sends():
    resolved = validate_config(
        "rest_api", {"base_url": "https://x", "flatten": "false"}
    )
    assert resolved["flatten"] is False


def test_whitespace_is_trimmed_off_text_fields():
    resolved = validate_config("sqlite", {"file_path": "  /tmp/db.sqlite  "})
    assert resolved["file_path"] == "/tmp/db.sqlite"


def test_redaction_uses_the_same_list_the_spec_declares():
    redacted = redact("postgresql", {"host": "db", "password": "hunter2"})
    assert redacted["host"] == "db"
    assert redacted["password"] == "********"


def test_redacting_an_empty_secret_does_not_invent_one():
    assert redact("postgresql", {"password": ""})["password"] == ""


def test_a_stream_reads_back_qualified():
    assert StreamRef(name="orders", namespace="public").qualified_name == "public.orders"
    assert StreamRef(name="orders").qualified_name == "orders"


def test_the_capability_list_is_what_specs_are_checked_against():
    for spec in specs():
        assert spec.capabilities <= set(CAPABILITIES), spec.type
