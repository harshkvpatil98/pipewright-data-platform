from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_ingestion.router import build_router
from shared_python.errors import BadRequestError, register_exception_handlers


def _build_test_client() -> tuple[TestClient, UserRead]:
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
    app.include_router(
        build_router(
            get_db,
            get_current_user,
            get_storage_backend,
            settings=SimpleNamespace(
                allowed_upload_extensions=["csv", "xlsx", "json"],
                max_upload_size_bytes=1024 * 1024,
                preview_row_limit=50,
                profile_sample_value_limit=5,
            ),
        )
    )
    return TestClient(app), current_user


@patch("service_ingestion.router.ingest_project_file")
def test_upload_dataset_route_accepts_multipart_uploads(ingest_project_file) -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ingest_project_file.return_value = {
        "dataset": {
            "id": str(dataset_id),
            "project_id": str(project_id),
            "source_id": None,
            "uploaded_by_user_id": None,
            "pipeline_run_id": str(run_id),
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
        },
        "run": {
            "id": str(run_id),
            "project_id": str(project_id),
            "triggered_by_user_id": str(uuid.uuid4()),
            "triggered_by_username": "platform-admin",
            "run_type": "dataset_ingestion",
            "status": "succeeded",
            "started_at": datetime.now(UTC).isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "summary_json": {"row_count": 1},
            "logs_json": {"events": []},
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    }
    client, _current_user = _build_test_client()

    response = client.post(
        f"/projects/{project_id}/datasets/upload?dataset_name=Orders%20April",
        files={"file": ("orders.csv", b"name,amount\nalpha,10\n", "text/csv")},
    )

    assert response.status_code == 201
    assert response.json()["dataset"]["name"] == "Orders April"
    upload = ingest_project_file.call_args.kwargs["upload_file"]
    assert upload.file_name == "orders.csv"
    assert upload.file_bytes.startswith(b"name,amount")


@patch("service_ingestion.router.ingest_project_file", side_effect=BadRequestError("Unsupported file type."))
def test_upload_dataset_route_surfaces_safe_validation_errors(_ingest_project_file) -> None:
    client, _current_user = _build_test_client()

    response = client.post(
        f"/projects/{uuid.uuid4()}/datasets/upload",
        files={"file": ("orders.txt", b"bad", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported file type."}
