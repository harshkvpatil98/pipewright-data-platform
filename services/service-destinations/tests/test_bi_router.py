from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_destinations.bi_router import build_bi_router
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

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_bi_router(get_db, get_current_user))
    return TestClient(app)


@patch("service_destinations.bi_router.create_bi_connection")
def test_post_bi_connection(create_fn) -> None:
    pid = uuid.uuid4()
    cid = str(uuid.uuid4())
    create_fn.return_value = {
        "id": cid,
        "project_id": str(pid),
        "name": "PBI",
        "integration_type": "power_bi",
        "status": "active",
        "config_json": {"client_secret": "***"},
        "created_by_user_id": str(uuid.uuid4()),
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    response = _client().post(
        f"/projects/{pid}/bi-connections",
        json={
            "name": "PBI",
            "integration_type": "power_bi",
            "config_json": {
                "tenant_id": "tid",
                "client_id": "cid",
                "client_secret": "sec",
            },
        },
    )
    assert response.status_code == 201


@patch("service_destinations.bi_router.list_bi_connections")
def test_list_bi_connections(list_fn) -> None:
    pid = uuid.uuid4()
    list_fn.return_value = {"items": []}
    response = _client().get(f"/projects/{pid}/bi-connections")
    assert response.status_code == 200


@patch("service_destinations.bi_router.check_bi_connection")
def test_post_bi_test(test_fn) -> None:
    pid = uuid.uuid4()
    cid = uuid.uuid4()
    test_fn.return_value = {
        "success": True,
        "checked_at": "2026-01-01T00:00:00Z",
        "message": "ok",
        "latency_ms": 12.0,
        "warnings": [],
    }
    response = _client().post(f"/projects/{pid}/bi-connections/{cid}/test")
    assert response.status_code == 200


@patch("service_destinations.bi_router.discover_bi_metadata")
def test_get_bi_metadata(meta_fn) -> None:
    pid = uuid.uuid4()
    cid = uuid.uuid4()
    meta_fn.return_value = {
        "integration_type": "power_bi",
        "metadata_kind": "power_bi_workspaces",
        "items": [{"id": "w1", "name": "WS"}],
    }
    response = _client().get(f"/projects/{pid}/bi-connections/{cid}/metadata")
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "WS"
