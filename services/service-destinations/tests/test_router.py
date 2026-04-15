from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_destinations.router import build_router
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

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user, get_storage_backend))
    return TestClient(app)


@patch("service_destinations.router.create_destination")
def test_post_destination(create_fn) -> None:
    pid = uuid.uuid4()
    did = str(uuid.uuid4())
    create_fn.return_value = {
        "id": did,
        "project_id": str(pid),
        "name": "Warehouse",
        "destination_type": "postgres",
        "status": "active",
        "config_json": {"host": "h", "password": "***"},
        "created_by_user_id": str(uuid.uuid4()),
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    response = _client().post(
        f"/projects/{pid}/destinations",
        json={
            "name": "Warehouse",
            "destination_type": "postgres",
            "config_json": {
                "host": "h",
                "port": 5432,
                "database": "d",
                "username": "u",
                "password": "p",
            },
        },
    )
    assert response.status_code == 201


@patch("service_destinations.router.list_destinations")
def test_list_destinations(list_fn) -> None:
    pid = uuid.uuid4()
    list_fn.return_value = {"items": []}
    response = _client().get(f"/projects/{pid}/destinations")
    assert response.status_code == 200


@patch("service_destinations.router.test_destination_connection")
def test_post_test(test_fn) -> None:
    pid = uuid.uuid4()
    dest_id = uuid.uuid4()
    test_fn.return_value = {
        "success": True,
        "checked_at": "2026-01-01T00:00:00Z",
        "message": "ok",
        "latency_ms": 12.0,
        "warnings": [],
    }
    response = _client().post(f"/projects/{pid}/destinations/{dest_id}/test")
    assert response.status_code == 200
    assert response.json()["success"] is True


@patch("service_destinations.router.publish_dataset_to_postgres")
def test_post_publish_postgres(publish_fn) -> None:
    pid = uuid.uuid4()
    ds = uuid.uuid4()
    publish_fn.return_value = {
        "success": True,
        "message": "ok",
        "run": {
            "id": str(uuid.uuid4()),
            "project_id": str(pid),
            "triggered_by_user_id": str(uuid.uuid4()),
            "pipeline_id": None,
            "triggered_by_username": None,
            "run_type": "dataset_publish_postgres",
            "status": "succeeded",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:00Z",
            "summary_json": {},
            "logs_json": {},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        "target_table": "t",
        "target_schema": None,
        "write_mode": "replace",
        "row_count_written": 1,
        "row_count_attempted": 1,
        "destination": {
            "id": str(uuid.uuid4()),
            "name": "pg",
            "destination_type": "postgres",
        },
        "summary_json": {},
    }
    response = _client().post(
        f"/projects/{pid}/datasets/{ds}/publish/postgres",
        json={"destination_id": str(uuid.uuid4()), "table_name": "t", "write_mode": "replace"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


@patch("service_destinations.router.publish_dataset_to_power_bi")
def test_post_publish_power_bi(publish_fn) -> None:
    pid = uuid.uuid4()
    ds = uuid.uuid4()
    wid = str(uuid.uuid4())
    publish_fn.return_value = {
        "success": True,
        "message": "Published.",
        "run": {
            "id": str(uuid.uuid4()),
            "project_id": str(pid),
            "triggered_by_user_id": str(uuid.uuid4()),
            "pipeline_id": None,
            "triggered_by_username": None,
            "run_type": "dataset_publish_power_bi",
            "status": "succeeded",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:00Z",
            "summary_json": {},
            "logs_json": {},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        "connection": {"id": str(uuid.uuid4()), "name": "pbi", "integration_type": "power_bi"},
        "workspace_id": wid,
        "target_dataset_name": "DS",
        "target_table_name": "PublishedData",
        "write_mode": "replace",
        "row_count_published": 3,
        "row_count_attempted": 3,
        "power_bi_dataset_id": "abc",
        "provider_outcome": "created",
        "summary_json": {},
    }
    response = _client().post(
        f"/projects/{pid}/datasets/{ds}/publish/power-bi",
        json={
            "connection_id": str(uuid.uuid4()),
            "workspace_id": wid,
            "target_dataset_name": "DS",
            "write_mode": "replace",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


@patch("service_destinations.router.publish_dataset_to_tableau")
def test_post_publish_tableau(publish_fn) -> None:
    pid = uuid.uuid4()
    ds = uuid.uuid4()
    proj = uuid.uuid4()
    publish_fn.return_value = {
        "success": True,
        "message": "Published.",
        "run": {
            "id": str(uuid.uuid4()),
            "project_id": str(pid),
            "triggered_by_user_id": str(uuid.uuid4()),
            "pipeline_id": None,
            "triggered_by_username": None,
            "run_type": "dataset_publish_tableau",
            "status": "succeeded",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:00Z",
            "summary_json": {},
            "logs_json": {},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        "connection": {"id": str(uuid.uuid4()), "name": "tab", "integration_type": "tableau"},
        "tableau_site_id": "site-1",
        "tableau_project_id": proj,
        "datasource_name": "DS",
        "write_mode": "create_only",
        "row_count_published": 3,
        "row_count_attempted": 3,
        "tableau_datasource_id": "tds",
        "provider_outcome": "create_only",
        "summary_json": {},
    }
    response = _client().post(
        f"/projects/{pid}/datasets/{ds}/publish/tableau",
        json={
            "connection_id": str(uuid.uuid4()),
            "tableau_project_id": str(proj),
            "datasource_name": "DS",
            "write_mode": "create_only",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
