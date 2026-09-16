"""Every connector in the catalogue passes the SDK's own contract checks."""

from __future__ import annotations

import pytest

from service_connectors import adapters  # noqa: F401
from service_connectors.conformance import check_spec
from service_connectors.protocol import ConfigField, ConnectorSpec, TestResult
from service_connectors.registry import get, known_types


@pytest.mark.parametrize("connector_type", known_types())
def test_every_connector_conforms(connector_type: str):
    report = check_spec(get(connector_type))
    assert report.ok, f"{connector_type}: {report.failures}"


def test_conformance_catches_a_capability_with_no_method():
    """The failure this exists to prevent: a declaration nothing backs."""

    class Liar:
        spec = ConnectorSpec(
            type="liar",
            label="Liar",
            category="api",
            description="Claims to write and cannot.",
            config_fields=(ConfigField("url", "URL"),),
            capabilities=frozenset({"test", "write"}),
        )

        def test(self, _config):
            return TestResult(success=True, message="fine")

    # Deliberately not registered: `check_spec` takes the connector itself, and
    # putting a knowingly-broken one into the global registry would leak it
    # into every test that runs after this file.
    report = check_spec(Liar())
    assert not report.ok
    assert any("write" in failure for failure in report.failures)


def test_conformance_catches_a_spec_with_no_description():
    class Terse:
        spec = ConnectorSpec(
            type="terse", label="Terse", category="api", description="short"
        )

        def test(self, _config):
            return TestResult(success=True, message="fine")

    report = check_spec(Terse())
    assert "has a description" in report.failures


def test_a_connector_requiring_nothing_skips_the_empty_config_check():
    class Open:
        spec = ConnectorSpec(
            type="open",
            label="Open",
            category="api",
            description="Needs no configuration at all.",
            capabilities=frozenset({"test"}),
        )

        def test(self, _config):
            return TestResult(success=True, message="fine")

    report = check_spec(Open())
    assert report.ok
    assert any("nothing is required" in skipped for skipped in report.skipped)


def test_a_connector_without_its_driver_says_so_rather_than_claiming_to_work():
    """`supports()` must never promise something only a failed run reveals."""
    snowflake = get("snowflake")
    assert snowflake.spec.available is False
    assert snowflake.spec.driver_package == "snowflake-sqlalchemy"
    assert snowflake.spec.supports("read") is False

    result = snowflake.test({})
    assert result.success is False
    assert "snowflake-sqlalchemy" in result.message
    assert "Install it" in result.message


def test_the_connectors_that_do_work_are_marked_available():
    for connector_type in ("postgresql", "rest_api", "local_files"):
        assert get(connector_type).spec.available is True
