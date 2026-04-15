from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_comparisons.router import build_router
from shared_python.errors import NotFoundError, register_exception_handlers


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


@patch("service_comparisons.router.get_dataset_comparison_summary")
def test_dataset_compare_route_returns_payload(get_cmp) -> None:
    pid = uuid.uuid4()
    lid = uuid.uuid4()
    rid = uuid.uuid4()
    get_cmp.return_value = {
        "left_dataset": {
            "id": str(lid),
            "name": "A",
            "is_derived": False,
            "row_count": 1,
            "column_count": 2,
        },
        "right_dataset": {
            "id": str(rid),
            "name": "B",
            "is_derived": True,
            "row_count": 1,
            "column_count": 2,
        },
        "row_count_delta": 0,
        "column_count_delta": 0,
        "profile_delta": {
            "duplicate_row_count_before": None,
            "duplicate_row_count_after": None,
            "completeness_score_before": None,
            "completeness_score_after": None,
        },
        "schema_delta": {"added_columns": [], "removed_columns": [], "changed_type_columns": []},
        "lineage_context": {
            "related_by_parent_child": True,
            "parent_dataset_id": str(lid),
            "created_from_pipeline_id": None,
            "related_run_id": None,
        },
        "comparison_notes": [],
    }
    response = _client().get(f"/projects/{pid}/datasets/{lid}/compare/{rid}")
    assert response.status_code == 200
    assert response.json()["left_dataset"]["name"] == "A"


@patch("service_comparisons.router.get_run_comparison_summary")
def test_run_comparison_route(get_run) -> None:
    pid = uuid.uuid4()
    run_id = uuid.uuid4()
    get_run.return_value = {
        "run_id": str(run_id),
        "run_type": "dataset_transformation",
        "status": "succeeded",
        "pipeline_id": None,
        "base_dataset": None,
        "derived_dataset": None,
        "row_count_before": None,
        "row_count_after": None,
        "column_count_before": None,
        "column_count_after": None,
        "step_count": None,
        "summary_available": False,
        "comparison_notes": [],
        "raw_summary_present": False,
    }
    response = _client().get(f"/projects/{pid}/runs/{run_id}/comparison")
    assert response.status_code == 200


@patch("service_comparisons.router.get_dataset_comparison_summary", side_effect=NotFoundError("x"))
def test_dataset_compare_404(_get) -> None:
    response = _client().get(f"/projects/{uuid.uuid4()}/datasets/{uuid.uuid4()}/compare/{uuid.uuid4()}")
    assert response.status_code == 404
