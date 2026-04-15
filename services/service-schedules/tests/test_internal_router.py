from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_schedules.internal_router import build_internal_router
from service_schedules.schemas import RunDueSchedulesSummary
from shared_python.errors import register_exception_handlers


class _Settings:
    scheduler_internal_token = "test-secret-token"


def _client() -> TestClient:
    def get_db():
        return object()

    def get_storage():
        return object()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_internal_router(get_db, get_storage, _Settings()))
    return TestClient(app)


def test_run_due_without_token_returns_403() -> None:
    r = _client().post("/internal/schedules/run-due-once")
    assert r.status_code == 403


@patch("service_schedules.internal_router.run_due_schedules_once")
def test_run_due_with_token(mock_run) -> None:
    mock_run.return_value = RunDueSchedulesSummary(
        checked_count=1,
        due_count=0,
        triggered_count=0,
        success_count=0,
        failure_count=0,
        affected_schedule_ids=[],
    )
    r = _client().post(
        "/internal/schedules/run-due-once",
        headers={"X-Internal-Token": "test-secret-token"},
    )
    assert r.status_code == 200
    assert r.json()["checked_count"] == 1
