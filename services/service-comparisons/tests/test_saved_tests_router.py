from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_comparisons.router import build_router
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


@patch("service_comparisons.router.create_saved_statistical_test")
def test_post_saved_test(create_fn) -> None:
    pid = uuid.uuid4()
    lid = uuid.uuid4()
    rid = uuid.uuid4()
    create_fn.return_value = {
        "id": str(uuid.uuid4()),
        "project_id": str(pid),
        "name": "t",
        "description": None,
        "test_type": "welch_t_test",
        "column_name": "x",
        "options_json": None,
        "left_dataset_id": str(lid),
        "right_dataset_id": str(rid),
        "left_dataset_name": "L",
        "right_dataset_name": "R",
        "created_by_user_id": str(uuid.uuid4()),
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    response = _client().post(
        f"/projects/{pid}/tests/saved",
        json={
            "name": "t",
            "left_dataset_id": str(lid),
            "right_dataset_id": str(rid),
            "test_type": "welch_t_test",
            "column_name": "x",
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == "t"


@patch("service_comparisons.router.list_saved_statistical_tests")
def test_list_saved_tests(list_fn) -> None:
    pid = uuid.uuid4()
    list_fn.return_value = {"items": []}
    response = _client().get(f"/projects/{pid}/tests/saved")
    assert response.status_code == 200
    assert response.json() == {"items": []}


@patch("service_comparisons.router.get_saved_statistical_test_detail")
def test_get_saved_detail(get_fn) -> None:
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    get_fn.return_value = {
        "saved_test": {
            "id": str(sid),
            "project_id": str(pid),
            "name": "n",
            "description": None,
            "test_type": "welch_t_test",
            "column_name": "x",
            "options_json": None,
            "left_dataset_id": str(uuid.uuid4()),
            "right_dataset_id": str(uuid.uuid4()),
            "left_dataset_name": "L",
            "right_dataset_name": "R",
            "created_by_user_id": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        "runs": [],
        "comparison_note": None,
    }
    response = _client().get(f"/projects/{pid}/tests/saved/{sid}")
    assert response.status_code == 200


@patch("service_comparisons.router.update_saved_statistical_test")
def test_patch_saved_test(patch_fn) -> None:
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    patch_fn.return_value = {
        "id": str(sid),
        "project_id": str(pid),
        "name": "new",
        "description": None,
        "test_type": "welch_t_test",
        "column_name": "x",
        "options_json": None,
        "left_dataset_id": str(uuid.uuid4()),
        "right_dataset_id": str(uuid.uuid4()),
        "left_dataset_name": "L",
        "right_dataset_name": "R",
        "created_by_user_id": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    response = _client().patch(f"/projects/{pid}/tests/saved/{sid}", json={"name": "new"})
    assert response.status_code == 200


@patch("service_comparisons.router.run_saved_statistical_test")
def test_post_run_saved(run_fn) -> None:
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    run_fn.return_value = {
        "id": str(uuid.uuid4()),
        "saved_test_id": str(sid),
        "project_id": str(pid),
        "status": "succeeded",
        "executed_by_user_id": str(uuid.uuid4()),
        "result": None,
        "error_message": None,
        "warnings_json": None,
        "created_at": "2026-01-01T00:00:00Z",
    }
    response = _client().post(f"/projects/{pid}/tests/saved/{sid}/run")
    assert response.status_code == 200


@patch("service_comparisons.router.list_saved_statistical_test_runs")
def test_get_saved_runs(list_fn) -> None:
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    list_fn.return_value = {"items": []}
    response = _client().get(f"/projects/{pid}/tests/saved/{sid}/runs")
    assert response.status_code == 200
