from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_datasets.router import build_router
from shared_python.errors import register_exception_handlers


def _build_test_client() -> TestClient:
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
    app.include_router(build_router(get_db, get_current_user))
    return TestClient(app)


@patch("service_datasets.router.get_dataset_by_project")
def test_dataset_detail_route_returns_dataset(get_dataset_by_project) -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    get_dataset_by_project.return_value = {
        "id": str(dataset_id),
        "project_id": str(project_id),
        "source_id": None,
        "uploaded_by_user_id": None,
        "pipeline_run_id": None,
        "parent_dataset_id": None,
        "created_from_pipeline_id": None,
        "is_derived": False,
        "name": "Orders April",
        "original_filename": "orders.csv",
        "file_name": "safe-orders.csv",
        "file_type": "csv",
        "file_size_bytes": 21,
        "status": "ready",
        "ingestion_status": "succeeded",
        "row_count": 1,
        "column_count": 2,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "schema_snapshot": {"columns": []},
        "schema_json": {"columns": [], "ordered_columns": []},
        "profile_json": {"row_count": 1},
        "preview_json": {"columns": ["name"], "rows": [{"name": "alpha"}]},
        "ingestion_error": None,
        "last_profiled_at": datetime.now(UTC).isoformat(),
    }
    client = _build_test_client()

    response = client.get(f"/projects/{project_id}/datasets/{dataset_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(dataset_id)


@patch("service_datasets.router.get_dataset_preview")
def test_dataset_preview_route_returns_preview(get_dataset_preview) -> None:
    dataset_id = uuid.uuid4()
    get_dataset_preview.return_value = {
        "dataset_id": str(dataset_id),
        "columns": ["name", "amount"],
        "rows": [{"name": "alpha", "amount": 10}],
    }
    client = _build_test_client()

    response = client.get(f"/projects/{uuid.uuid4()}/datasets/{dataset_id}/preview")

    assert response.status_code == 200
    assert response.json()["rows"][0]["amount"] == 10


@patch("service_datasets.router.get_dataset_profile")
def test_dataset_profile_route_returns_profile(get_dataset_profile) -> None:
    dataset_id = uuid.uuid4()
    get_dataset_profile.return_value = {
        "dataset_id": str(dataset_id),
        "profile": {
            "row_count": 1,
            "column_count": 2,
            "quality_flags": {"high_null_columns": [], "constant_value_columns": [], "potential_id_columns": [], "mixed_type_suspicions": []},
        },
    }
    client = _build_test_client()

    response = client.get(f"/projects/{uuid.uuid4()}/datasets/{dataset_id}/profile")

    assert response.status_code == 200
    assert response.json()["profile"]["column_count"] == 2


@patch("service_datasets.router.get_dataset_audit_summary")
def test_dataset_audit_route_returns_summary(get_dataset_audit_summary) -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    get_dataset_audit_summary.return_value = {
        "id": str(dataset_id),
        "name": "Orders",
        "is_derived": False,
        "parent_dataset_id": None,
        "project": {"id": str(project_id), "name": "Demo"},
        "ownership": {"uploaded_by_user_id": None},
        "artifact": {
            "file_name": "a.csv",
            "original_filename": "a.csv",
            "file_type": "csv",
            "file_size_bytes": 10,
            "file_path": "safe/rel.csv",
        },
        "metrics": {
            "row_count": 1,
            "column_count": 2,
            "ingestion_status": "succeeded",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "last_profiled_at": None,
        },
        "profile_highlights": {
            "duplicate_row_count": None,
            "duplicate_row_percentage": None,
            "completeness_score": None,
            "high_null_columns": [],
            "constant_value_columns": [],
            "potential_id_columns": [],
        },
        "lineage": {
            "created_from_pipeline_id": None,
            "pipeline_run_id": None,
            "parent_dataset_id": None,
        },
        "schema_summary": {"column_count": 2, "sample_column_names": ["a"]},
        "warnings": ["Dataset profile has not been generated."],
    }
    client = _build_test_client()
    response = client.get(f"/projects/{project_id}/datasets/{dataset_id}/audit")
    assert response.status_code == 200
    body = response.json()
    assert body["warnings"][0] == "Dataset profile has not been generated."
    assert body["project"]["name"] == "Demo"
