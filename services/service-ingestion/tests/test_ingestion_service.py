from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from service_auth.schemas import UserRead
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from shared_python.errors import BadRequestError, NotFoundError


class FakeStorage:
    def __init__(self):
        self.saved = None
        self.deleted = False

    def save_upload(self, *, relative_path: str, file_bytes: bytes):
        self.saved = (relative_path, file_bytes)
        return SimpleNamespace(relative_path=relative_path, file_name=relative_path.split("/")[-1], size_bytes=len(file_bytes))

    def exists(self, relative_path: str) -> bool:
        return self.saved is not None and self.saved[0] == relative_path and not self.deleted

    def delete(self, relative_path: str) -> None:
        self.deleted = True


@patch("service_ingestion.service.ensure_owned_project")
@patch("service_ingestion.service.create_pipeline_run")
@patch("service_ingestion.service.mark_pipeline_run_running")
@patch("service_ingestion.service.mark_dataset_ingestion_running")
@patch("service_ingestion.service.mark_pipeline_run_succeeded")
@patch("service_ingestion.service.create_uploaded_dataset_placeholder")
@patch("service_ingestion.service.finalize_dataset_ingestion_success")
@pytest.mark.parametrize(
    ("file_name", "content_type", "payload"),
    [
        ("orders.csv", "text/csv", b"name,amount\nalpha,10\n"),
        ("orders.json", "application/json", b'[{"name":"alpha","amount":10}]'),
        ("orders.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", None),
    ],
)
def test_ingest_project_file_supported_upload_success(
    finalize_dataset_ingestion_success,
    create_uploaded_dataset_placeholder,
    mark_pipeline_run_succeeded,
    _mark_dataset_ingestion_running,
    _mark_pipeline_run_running,
    create_pipeline_run,
    ensure_owned_project,
    file_name,
    content_type,
    payload,
) -> None:
    project = SimpleNamespace(id=uuid.uuid4(), slug="finance-quality", status="active")
    ensure_owned_project.return_value = project
    create_pipeline_run.return_value = SimpleNamespace(id=uuid.uuid4())
    dataset = SimpleNamespace(id=uuid.uuid4(), name="orders")
    create_uploaded_dataset_placeholder.return_value = dataset
    dataset_detail = SimpleNamespace(id=dataset.id, ingestion_status="succeeded")
    run_detail = SimpleNamespace(id=uuid.uuid4(), status="succeeded")
    finalize_dataset_ingestion_success.return_value = dataset_detail
    mark_pipeline_run_succeeded.return_value = run_detail

    current_user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    upload_payload = payload if payload is not None else _build_xlsx_payload()
    response = ingest_project_file(
        object(),
        project_id=project.id,
        dataset_name="Orders April",
        upload_file=IngestionUpload(file_name=file_name, content_type=content_type, file_bytes=upload_payload),
        storage_backend=FakeStorage(),
        settings=SimpleNamespace(
            allowed_upload_extensions=["csv", "xlsx", "json"],
            max_upload_size_bytes=1024 * 1024,
            preview_row_limit=50,
            profile_sample_value_limit=5,
        ),
        current_user=current_user,
    )

    assert response.dataset.id == dataset.id
    assert response.run.status == "succeeded"
    summary_json = mark_pipeline_run_succeeded.call_args.kwargs["summary_json"]
    assert summary_json["dataset"]["row_count"] == 1
    assert summary_json["artifact"]["file_type"] in {"csv", "json", "xlsx"}


@patch("service_ingestion.service.ensure_owned_project")
def test_ingest_project_file_rejects_empty_payload(_ensure_owned_project) -> None:
    current_user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(BadRequestError, match="empty"):
        ingest_project_file(
            object(),
            project_id=uuid.uuid4(),
            dataset_name="Empty upload",
            upload_file=IngestionUpload(file_name="orders.csv", content_type="text/csv", file_bytes=b""),
            storage_backend=FakeStorage(),
            settings=SimpleNamespace(
                allowed_upload_extensions=["csv", "xlsx", "json"],
                max_upload_size_bytes=1024 * 1024,
                preview_row_limit=50,
                profile_sample_value_limit=5,
            ),
            current_user=current_user,
        )


@patch("service_ingestion.service.ensure_owned_project")
def test_ingest_project_file_rejects_unsupported_extensions(ensure_owned_project) -> None:
    ensure_owned_project.return_value = SimpleNamespace(id=uuid.uuid4(), slug="finance-quality", status="active")
    current_user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    with pytest.raises(BadRequestError, match="Unsupported file type"):
        ingest_project_file(
            object(),
            project_id=uuid.uuid4(),
            dataset_name="Bad upload",
            upload_file=IngestionUpload(file_name="orders.txt", content_type="text/plain", file_bytes=b"bad"),
            storage_backend=FakeStorage(),
            settings=SimpleNamespace(
                allowed_upload_extensions=["csv", "xlsx", "json"],
                max_upload_size_bytes=1024 * 1024,
                preview_row_limit=50,
                profile_sample_value_limit=5,
            ),
            current_user=current_user,
        )


@patch("service_ingestion.service.ensure_owned_project")
@patch("service_ingestion.service.create_pipeline_run")
@patch("service_ingestion.service.mark_pipeline_run_running")
@patch("service_ingestion.service.mark_dataset_ingestion_running")
@patch("service_ingestion.service.mark_pipeline_run_failed")
@patch("service_ingestion.service.create_uploaded_dataset_placeholder")
@patch("service_ingestion.service.finalize_dataset_ingestion_failure")
def test_ingest_project_file_marks_failed_run_on_parse_errors(
    finalize_dataset_ingestion_failure,
    create_uploaded_dataset_placeholder,
    mark_pipeline_run_failed,
    _mark_dataset_ingestion_running,
    _mark_pipeline_run_running,
    create_pipeline_run,
    ensure_owned_project,
) -> None:
    project = SimpleNamespace(id=uuid.uuid4(), slug="finance-quality", status="active")
    ensure_owned_project.return_value = project
    create_pipeline_run.return_value = SimpleNamespace(id=uuid.uuid4())
    create_uploaded_dataset_placeholder.return_value = SimpleNamespace(id=uuid.uuid4(), name="broken-json")
    finalize_dataset_ingestion_failure.return_value = SimpleNamespace(ingestion_error="Unable to parse JSON file")
    current_user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    with pytest.raises(BadRequestError, match="Unable to parse JSON file"):
        ingest_project_file(
            object(),
            project_id=project.id,
            dataset_name="Broken JSON",
            upload_file=IngestionUpload(file_name="broken.json", content_type="application/json", file_bytes=b"{"),
            storage_backend=FakeStorage(),
            settings=SimpleNamespace(
                allowed_upload_extensions=["csv", "xlsx", "json"],
                max_upload_size_bytes=1024 * 1024,
                preview_row_limit=50,
                profile_sample_value_limit=5,
            ),
            current_user=current_user,
        )

    summary_json = mark_pipeline_run_failed.call_args.kwargs["summary_json"]
    assert summary_json["dataset"]["name"] == "broken-json"
    assert summary_json["failure_stage"] == "parse"


@patch("service_ingestion.service.ensure_owned_project", side_effect=NotFoundError("Project not found."))
def test_ingest_project_file_enforces_project_ownership(_ensure_owned_project) -> None:
    current_user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    with pytest.raises(NotFoundError, match="Project not found."):
        ingest_project_file(
            object(),
            project_id=uuid.uuid4(),
            dataset_name="Orders April",
            upload_file=IngestionUpload(
                file_name="orders.csv",
                content_type="text/csv",
                file_bytes=b"name,amount\nalpha,10\n",
            ),
            storage_backend=FakeStorage(),
            settings=SimpleNamespace(
                allowed_upload_extensions=["csv", "xlsx", "json"],
                max_upload_size_bytes=1024 * 1024,
                preview_row_limit=50,
                profile_sample_value_limit=5,
            ),
            current_user=current_user,
        )


def _build_xlsx_payload() -> bytes:
    import io

    stream = io.BytesIO()
    dataframe = pd.DataFrame([{"name": "alpha", "amount": 10}])
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="Orders", index=False)
    return stream.getvalue()
