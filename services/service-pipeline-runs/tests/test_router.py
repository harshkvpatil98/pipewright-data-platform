from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth.schemas import UserRead
from service_pipeline_runs.router import build_router
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
    app.include_router(build_router(get_db, get_current_user))
    return TestClient(app)


@patch("service_pipeline_runs.router.get_run_audit_summary")
def test_run_audit_route_returns_payload(get_run_audit_summary) -> None:
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    get_run_audit_summary.return_value = {
        "id": str(run_id),
        "run_type": "sample_orchestration",
        "status": "succeeded",
        "created_at": datetime.now(UTC).isoformat(),
        "started_at": datetime.now(UTC).isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "project_id": str(project_id),
        "triggered_by_user_id": str(uuid.uuid4()),
        "pipeline_id": None,
        "related_dataset_ids": [],
        "summary_json": {"project_slug": "x"},
        "logs_json": {"events": []},
        "highlights": {
            "stage_count": 0,
            "failed_stage": None,
            "derived_dataset_created": False,
            "ingestion_type": None,
            "transformation_type": None,
        },
        "warnings": ["Run completed successfully."],
    }
    response = _client().get(f"/projects/{project_id}/runs/{run_id}/audit")
    assert response.status_code == 200
    assert response.json()["warnings"][0] == "Run completed successfully."
