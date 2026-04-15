from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_datasets.router import build_router
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

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user))
    return TestClient(app)


@patch("service_datasets.router.get_dataset_audit_summary")
def test_dataset_audit_export_returns_html_attachment(get_summary) -> None:
    from service_datasets.schemas import (
        DatasetAuditArtifact,
        DatasetAuditLineage,
        DatasetAuditMetrics,
        DatasetAuditOwnership,
        DatasetAuditProfileHighlights,
        DatasetAuditProject,
        DatasetAuditSchemaSummary,
        DatasetAuditSummary,
    )

    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(UTC)
    get_summary.return_value = DatasetAuditSummary(
        id=dataset_id,
        name="Sales & more",
        is_derived=False,
        parent_dataset_id=None,
        project=DatasetAuditProject(id=project_id, name="Proj"),
        ownership=DatasetAuditOwnership(uploaded_by_user_id=None),
        artifact=DatasetAuditArtifact(
            file_name="x.csv",
            original_filename="x.csv",
            file_type="csv",
            file_size_bytes=10,
            file_path="a/b.csv",
        ),
        metrics=DatasetAuditMetrics(
            row_count=1,
            column_count=2,
            ingestion_status="succeeded",
            created_at=now,
            updated_at=now,
            last_profiled_at=None,
        ),
        profile_highlights=DatasetAuditProfileHighlights(
            duplicate_row_count=None,
            duplicate_row_percentage=None,
            completeness_score=None,
            high_null_columns=[],
            constant_value_columns=[],
            potential_id_columns=[],
        ),
        lineage=DatasetAuditLineage(
            created_from_pipeline_id=None,
            pipeline_run_id=None,
            parent_dataset_id=None,
        ),
        schema_summary=DatasetAuditSchemaSummary(column_count=2, sample_column_names=["a"]),
        warnings=[],
    )

    response = _client().get(f"/projects/{project_id}/datasets/{dataset_id}/audit/export?format=html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "dataset-audit-" in disposition
    assert ".html" in disposition
    body = response.text
    assert "Dataset audit report" in body
    assert "Sales &amp; more" in body or "Sales" in body


@patch("service_datasets.router.get_dataset_audit_summary", side_effect=NotFoundError("Project not found."))
def test_dataset_audit_export_enforces_ownership(_get_summary) -> None:
    response = _client().get(f"/projects/{uuid.uuid4()}/datasets/{uuid.uuid4()}/audit/export?format=html")
    assert response.status_code == 404


def test_dataset_audit_export_rejects_unknown_format() -> None:
    with patch("service_datasets.router.get_dataset_audit_summary") as get_summary:
        get_summary.side_effect = AssertionError("should not load summary")
        response = _client().get(f"/projects/{uuid.uuid4()}/datasets/{uuid.uuid4()}/audit/export?format=pdf")
    assert response.status_code == 400
