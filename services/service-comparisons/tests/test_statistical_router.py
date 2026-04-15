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


@patch("service_comparisons.router.run_dataset_statistical_test")
def test_post_statistical_test_returns_payload(run_test) -> None:
    pid = uuid.uuid4()
    lid = uuid.uuid4()
    rid = uuid.uuid4()
    run_test.return_value = {
        "test_type": "welch_t_test",
        "column_name": "x",
        "left_dataset": {"id": str(lid), "name": "L", "sample_size": 10},
        "right_dataset": {"id": str(rid), "name": "R", "sample_size": 10},
        "statistic": 1.2,
        "p_value": 0.2,
        "effect_summary": "test",
        "assumptions_notes": [],
        "interpretation": "none",
        "warnings": ["Null values were excluded before testing."],
        "left_mean": 1.0,
        "right_mean": 2.0,
        "left_proportion": None,
        "right_proportion": None,
        "category_count": None,
    }
    response = _client().post(
        f"/projects/{pid}/datasets/{lid}/tests/{rid}",
        json={"test_type": "welch_t_test", "column_name": "x"},
    )
    assert response.status_code == 200
    assert response.json()["p_value"] == 0.2
