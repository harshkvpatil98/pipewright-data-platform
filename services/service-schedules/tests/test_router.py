from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_schedules.router import build_router
from shared_python.errors import register_exception_handlers


def _client() -> TestClient:
    current_user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    def get_db():
        return object()

    def get_current_user():
        return current_user

    def get_storage_backend():
        return object()

    settings = object()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user, get_storage_backend, settings))
    return TestClient(app)


@patch("service_schedules.router.create_schedule")
def test_post_schedule(create_fn) -> None:
    pid = uuid.uuid4()
    sid = str(uuid.uuid4())
    create_fn.return_value = {
        "id": sid,
        "project_id": str(pid),
        "name": "s",
        "description": None,
        "schedule_type": "transformation_pipeline_run",
        "cron_expression": "0 9 * * *",
        "timezone": None,
        "enabled": True,
        "target_config_json": {"pipeline_id": str(uuid.uuid4())},
        "created_by_user_id": str(uuid.uuid4()),
        "last_triggered_at": None,
        "next_run_at": None,
        "last_run_started_at": None,
        "last_run_finished_at": None,
        "last_run_status": None,
        "last_error_message": None,
        "execution_count": 0,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    response = _client().post(
        f"/projects/{pid}/schedules",
        json={
            "name": "s",
            "schedule_type": "transformation_pipeline_run",
            "cron_expression": "0 9 * * *",
            "target_config": {"pipeline_id": str(uuid.uuid4())},
        },
    )
    assert response.status_code == 201


@patch("service_schedules.router.trigger_schedule_now")
def test_trigger_now(trigger_fn) -> None:
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    trigger_fn.return_value = {
        "success": True,
        "message": "ok",
        "schedule": {
            "id": str(sid),
            "project_id": str(pid),
            "name": "s",
            "description": None,
            "schedule_type": "transformation_pipeline_run",
            "cron_expression": "0 9 * * *",
            "timezone": None,
            "enabled": True,
            "target_config_json": {"pipeline_id": str(uuid.uuid4())},
            "created_by_user_id": str(uuid.uuid4()),
            "last_triggered_at": None,
            "next_run_at": None,
            "last_run_started_at": None,
            "last_run_finished_at": None,
            "last_run_status": None,
            "last_error_message": None,
            "execution_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        "triggered_run": None,
        "transformation": None,
        "postgres_publish": None,
    }
    response = _client().post(f"/projects/{pid}/schedules/{sid}/trigger-now")
    assert response.status_code == 200
