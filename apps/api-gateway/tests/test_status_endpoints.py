import json

from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from api_gateway.main import app

client = TestClient(app)


@patch("api_gateway.routes.health.is_database_ready", return_value=True)
def test_health_ready_returns_success(_is_database_ready) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@patch("api_gateway.routes.status.collect_service_statuses")
def test_status_services_lists_modules(collect_service_statuses) -> None:
    collect_service_statuses.return_value = []
    response = client.get("/api/v1/status/services")
    assert response.status_code == 200
    assert response.json() == []


@patch("api_gateway.routes.status.platform_status")
def test_status_platform_includes_scheduler_and_timestamp(mock_platform) -> None:
    from shared_python.status import PlatformStatus, SchedulerOperationalSnapshot, ServiceStatus

    mock_platform.return_value = PlatformStatus(
        status="healthy",
        service="test",
        environment="test",
        version="0",
        services=[ServiceStatus(name="postgres", status="healthy", details={})],
        checked_at="2026-01-01T00:00:00+00:00",
        scheduler=SchedulerOperationalSnapshot(
            internal_api_configured=False,
            scheduler_runtime_id_configured=False,
            total_schedules=1,
            due_now_count=0,
            lease_active_count=0,
            stale_lease_count=0,
            note="n",
        ),
    )
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["checked_at"]
    assert body["scheduler"]["total_schedules"] == 1


@patch("api_gateway.status.collect_service_statuses")
@patch("api_gateway.status.is_database_ready", return_value=True)
@patch("api_gateway.status.count_stale_claimed_leases", return_value=0)
@patch("api_gateway.status.count_schedules_with_active_lease", return_value=1)
@patch("api_gateway.status.count_due_schedules", return_value=2)
@patch("api_gateway.status.count_all_schedules", return_value=5)
def test_status_assembly_redacts_sensitive_details(
    _count_all,
    _count_due,
    _active_lease,
    _stale_lease,
    _db_ready,
    collect_services,
) -> None:
    from shared_python.status import ServiceStatus

    collect_services.return_value = [
        ServiceStatus(name="x", status="healthy", details={"client_secret": "abc", "n": 1}),
    ]
    from api_gateway.status import platform_status
    from sqlalchemy.orm import Session

    db = MagicMock(spec=Session)
    out = platform_status(
        db=db,
        service_name="gw",
        environment="test",
        version="1",
        scheduler_internal_api_configured=True,
        scheduler_runtime_id_configured=True,
    )
    dumped = json.loads(out.model_dump_json())
    text = json.dumps(dumped)
    assert "abc" not in text
    assert "[redacted]" in text
    assert dumped["scheduler"]["internal_api_configured"] is True
    assert dumped["scheduler"]["total_schedules"] == 5
    assert dumped["scheduler"]["due_now_count"] == 2
    assert dumped["scheduler"]["lease_active_count"] == 1
    assert dumped["scheduler"]["stale_lease_count"] == 0


@patch("api_gateway.status.collect_service_statuses")
@patch("api_gateway.status.is_database_ready", return_value=True)
@patch("api_gateway.status.count_due_schedules", side_effect=RuntimeError("db down"))
@patch("api_gateway.status.count_all_schedules", side_effect=RuntimeError("db down"))
def test_scheduler_snapshot_graceful_when_counts_fail(
    _count_all,
    _count_due,
    _db_ready,
    collect_services,
) -> None:
    from shared_python.status import ServiceStatus

    collect_services.return_value = [ServiceStatus(name="x", status="healthy", details={})]
    from api_gateway.status import platform_status
    from sqlalchemy.orm import Session

    db = MagicMock(spec=Session)
    out = platform_status(
        db=db,
        service_name="gw",
        environment="test",
        version="1",
        scheduler_internal_api_configured=False,
        scheduler_runtime_id_configured=False,
    )
    assert out.scheduler.total_schedules == 0
    assert out.scheduler.due_now_count == 0
    assert "unavailable" in out.scheduler.note.lower()
