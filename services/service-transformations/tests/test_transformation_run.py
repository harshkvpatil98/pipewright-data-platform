from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_datasets.schemas import DatasetDetailRead
from service_pipeline_runs.schemas import PipelineRunRead
from service_transformations.router import build_router
from service_transformations.schemas import TransformationRunResponse
from shared_python.errors import NotFoundError, UnauthorizedError, register_exception_handlers


def _make_user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="runner",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_settings():
    s = MagicMock()
    s.preview_row_limit = 50
    s.profile_sample_value_limit = 5
    s.max_upload_size_bytes = 25 * 1024 * 1024
    return s


def _build_client():
    user = _make_user()
    db = MagicMock()
    storage = MagicMock()

    def get_db():
        return db

    def get_current_user():
        return user

    def get_storage_backend():
        return storage

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user, get_storage_backend, _make_settings()))
    return TestClient(app), db, storage, user


def _sample_run_response(project_id: uuid.UUID) -> TransformationRunResponse:
    now = datetime.now(UTC)
    pid = uuid.uuid4()
    return TransformationRunResponse(
        run=PipelineRunRead(
            id=uuid.uuid4(),
            project_id=project_id,
            triggered_by_user_id=uuid.uuid4(),
            pipeline_id=pid,
            triggered_by_username="runner",
            run_type="dataset_transformation",
            status="succeeded",
            started_at=now,
            completed_at=now,
            summary_json={"transformation_type": "dataset_transformation"},
            logs_json={"events": []},
            created_at=now,
            updated_at=now,
        ),
        dataset=DatasetDetailRead(
            id=uuid.uuid4(),
            project_id=project_id,
            source_id=None,
            uploaded_by_user_id=uuid.uuid4(),
            pipeline_run_id=uuid.uuid4(),
            parent_dataset_id=uuid.uuid4(),
            created_from_pipeline_id=pid,
            name="Pipe · derived",
            original_filename="transformed.csv",
            file_name="out.csv",
            file_type="csv",
            file_size_bytes=120,
            is_derived=True,
            status="ready",
            ingestion_status="succeeded",
            row_count=2,
            column_count=1,
            schema_snapshot=None,
            schema_json=None,
            profile_json=None,
            preview_json=None,
            ingestion_error=None,
            last_profiled_at=now,
            created_at=now,
            updated_at=now,
        ),
    )


@patch("service_transformations.router.run_saved_transformation_pipeline")
def test_run_endpoint_returns_run_and_dataset(mock_run) -> None:
    project_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    mock_run.return_value = _sample_run_response(project_id)

    client, _db, _storage, _user = _build_client()
    response = client.post(f"/projects/{project_id}/pipelines/{pipeline_id}/run")

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["run_type"] == "dataset_transformation"
    assert body["run"]["status"] == "succeeded"
    assert body["dataset"]["is_derived"] is True
    mock_run.assert_called_once()


@patch("service_transformations.run.get_dataset_model_for_project")
@patch("service_transformations.run.get_transformation_pipeline_for_project")
@patch("service_transformations.run.ensure_owned_project", side_effect=NotFoundError("Project not found."))
def test_run_pipeline_ownership(_ensure, mock_get_pipeline, mock_get_dataset) -> None:
    mock_get_pipeline.return_value = MagicMock()
    mock_get_dataset.return_value = MagicMock()
    client, _db, _storage, _user = _build_client()
    response = client.post(f"/projects/{uuid.uuid4()}/pipelines/{uuid.uuid4()}/run")
    assert response.status_code == 404


@patch("service_transformations.run.create_derived_dataset_placeholder")
@patch("service_transformations.run.create_pipeline_run")
@patch("service_transformations.run.get_dataset_model_for_project")
@patch("service_transformations.run.get_transformation_pipeline_for_project")
@patch("service_transformations.run.ensure_owned_project")
def test_run_failure_no_derived_when_step_invalid(
    _ensure,
    mock_get_pipeline,
    mock_get_dataset,
    mock_create_run,
    mock_create_derived,
) -> None:
    pipeline = MagicMock()
    pipeline.id = uuid.uuid4()
    pipeline.project_id = uuid.uuid4()
    pipeline.base_dataset_id = uuid.uuid4()
    pipeline.name = "Bad"
    pipeline.steps_json = [{"step_type": "select_columns", "config": {"columns": ["nope"]}}]

    base = MagicMock()
    base.id = pipeline.base_dataset_id
    base.name = "Base"
    base.file_path = "uploads/a.csv"
    base.file_type = "csv"

    mock_get_pipeline.return_value = pipeline
    mock_get_dataset.return_value = base

    now = datetime.now(UTC)
    run_row = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=pipeline.project_id,
        triggered_by_user_id=uuid.uuid4(),
        triggered_by_username=None,
        triggered_by_user=None,
        pipeline_id=pipeline.id,
        run_type="dataset_transformation",
        status="running",
        started_at=now,
        completed_at=None,
        summary_json=None,
        logs_json=None,
        created_at=now,
        updated_at=now,
    )
    mock_create_run.return_value = run_row

    client, _db, storage, _user = _build_client()
    storage.read_bytes.return_value = b"name,amount\na,1\n"

    response = client.post(f"/projects/{pipeline.project_id}/pipelines/{pipeline.id}/run")

    assert response.status_code == 400
    mock_create_derived.assert_not_called()


def test_run_pipeline_unauthenticated() -> None:
    def get_db():
        return MagicMock()

    def get_current_user():
        raise UnauthorizedError("Authentication required.")

    def get_storage_backend():
        return MagicMock()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user, get_storage_backend, _make_settings()))
    client = TestClient(app)

    response = client.post(f"/projects/{uuid.uuid4()}/pipelines/{uuid.uuid4()}/run")
    assert response.status_code == 401
