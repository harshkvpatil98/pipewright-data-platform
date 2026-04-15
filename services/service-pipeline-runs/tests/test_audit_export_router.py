from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_pipeline_runs.router import build_router
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


@patch("service_pipeline_runs.router.get_run_audit_summary")
def test_run_audit_export_returns_html_attachment(get_summary) -> None:
    from service_pipeline_runs.schemas import RunAuditHighlights, RunAuditSummary

    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    get_summary.return_value = RunAuditSummary(
        id=run_id,
        run_type="sample_orchestration",
        status="succeeded",
        created_at=now,
        started_at=now,
        completed_at=now,
        project_id=project_id,
        triggered_by_user_id=uuid.uuid4(),
        pipeline_id=None,
        related_dataset_ids=[],
        summary_json={"k": "v"},
        logs_json={"events": []},
        highlights=RunAuditHighlights(),
        warnings=[],
    )

    response = _client().get(f"/projects/{project_id}/runs/{run_id}/audit/export?format=html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "attachment" in response.headers["content-disposition"]
    assert "run-audit-" in response.headers["content-disposition"]
    assert "Pipeline run audit report" in response.text


@patch("service_pipeline_runs.router.get_run_audit_summary", side_effect=NotFoundError("Project not found."))
def test_run_audit_export_enforces_ownership(_get_summary) -> None:
    response = _client().get(f"/projects/{uuid.uuid4()}/runs/{uuid.uuid4()}/audit/export?format=html")
    assert response.status_code == 404


def test_run_audit_export_rejects_unknown_format() -> None:
    with patch("service_pipeline_runs.router.get_run_audit_summary") as get_summary:
        get_summary.side_effect = AssertionError("should not load summary")
        response = _client().get(f"/projects/{uuid.uuid4()}/runs/{uuid.uuid4()}/audit/export?format=pdf")
    assert response.status_code == 400
