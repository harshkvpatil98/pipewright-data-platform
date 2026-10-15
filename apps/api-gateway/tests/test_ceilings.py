"""The limits System status states are the ones enforced (adoption-readiness A7, X9)."""

from __future__ import annotations

from api_gateway.config import settings
from api_gateway.status import ceilings


def _by_name(items) -> dict[str, object]:
    return {item.name: item for item in items}


def test_the_stated_limits_follow_the_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_size_bytes", 200 * 1024 * 1024)
    monkeypatch.setattr(settings, "project_runs_at_once", 5)
    stated = _by_name(ceilings(settings))
    assert stated["Largest file you can upload"].value == "200 MB"
    assert stated["Largest file you can upload"].setting == "MAX_UPLOAD_SIZE_BYTES"
    assert stated["Runs of one project at the same time"].value == "5"


def test_every_limit_says_something() -> None:
    for item in ceilings(settings):
        assert item.name and item.value
        assert "—" not in item.name + item.value + item.detail


def test_the_background_hand_over_points_are_the_ones_used() -> None:
    from service_destinations.deliver import IN_REQUEST_ROWS

    stated = _by_name(ceilings(settings))
    assert stated["Rows a delivery writes while you wait"].value == f"{IN_REQUEST_ROWS:,}"
    assert "25 MB" in stated["Largest file you can upload"].detail
