"""The REST connector refuses addresses the platform must not call."""

from __future__ import annotations

import pytest

from service_connectors.adapters.rest import RestConnector


@pytest.fixture(autouse=True)
def loopback_closed(monkeypatch):
    monkeypatch.delenv("OUTBOUND_ALLOW_LOOPBACK", raising=False)


@pytest.mark.parametrize("base_url", ["http://169.254.169.254", "http://127.0.0.1:8100"])
def test_the_metadata_service_and_this_machine_are_refused(base_url) -> None:
    result = RestConnector().test({"base_url": base_url, "path": "/latest/meta-data/"})
    assert result.success is False
    assert "points to" in result.message


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("//issues.json", "/issues.json"), ("issues.json", "/issues.json"), ("", "/"), ("https://x.test/a", "https://x.test/a")],
)
def test_a_path_typed_after_the_default_slash_still_reads_the_path(typed, expected) -> None:
    from service_connectors.adapters.rest import _path

    assert _path(typed) == expected
